"""Cliente HTTP con reintentos, cookies, rangos y descargas reanudables."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .errors import DownloadError, NetworkError


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

ProgressCallback = Callable[[int, int | None], None]

# Algunos nodos de googlevideo rechazan con 403 las peticiones sin Range o con
# rangos demasiado grandes. Descargar en bloques acotados de 1 MiB evita ese
# bloqueo y además permite reanudar con más precisión.
RANGE_SIZE = 1024 * 1024

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.I)


def _content_range_total(value: str | None) -> int | None:
    """Extrae el tamaño total de una cabecera Content-Range."""
    if not value:
        return None
    match = _CONTENT_RANGE_RE.search(value)
    if not match:
        return None
    total = match.group(3)
    if total == "*":
        return None
    try:
        return int(total)
    except ValueError:
        return None


def load_netscape_cookies(session: requests.Session, path: str | Path) -> int:
    """Carga cookies en formato Netscape (el que exporta el navegador)."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"No existe el archivo de cookies: {file_path}")
    count = 0
    for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, _flag, cookie_path, _secure, _expires, name, value = fields[:7]
        domain = domain.lstrip(".")
        try:
            session.cookies.set(
                name,
                value,
                domain=domain,
                path=cookie_path or "/",
            )
            count += 1
        except (ValueError, KeyError):
            continue
    return count


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 5,
        proxy: str | None = None,
        cookies: str | Path | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        retry = Retry(
            total=self.retries,
            connect=self.retries,
            read=self.retries,
            status=self.retries,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=16,
            pool_maxsize=16,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        if cookies:
            load_netscape_cookies(self.session, cookies)

    def _timeout(self) -> tuple[float, float]:
        return (min(self.timeout, 30.0), max(self.timeout, 30.0))

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout())
        try:
            return self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise NetworkError(f"Error de red: {exc}") from exc

    def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> str:
        response = self.request("GET", url, headers=headers)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NetworkError(f"HTTP {response.status_code}: {url}") from exc
        return response.content.decode(encoding, errors="replace")

    def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        response = self.request("GET", url, headers=headers)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NetworkError(f"HTTP {response.status_code}: {url}") from exc
        return response.content

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.request("POST", url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise NetworkError(f"HTTP {response.status_code}: {url}") from exc
        try:
            return response.json()
        except ValueError as exc:
            raise NetworkError(f"Respuesta no válida de YouTube: {url}") from exc

    def stream_download(
        self,
        url: str,
        destination: str | Path,
        *,
        expected_size: int | None = None,
        progress: ProgressCallback | None = None,
        headers: dict[str, str] | None = None,
        resume: bool = True,
        chunk_size: int = 256 * 1024,
        range_size: int = RANGE_SIZE,
    ) -> int:
        """Descarga a un .part en bloques con Range y renombra al terminar.

        Se pide un rango acotado en cada petición: algunos nodos de
        googlevideo devuelven HTTP 403 si se solicita el archivo completo o un
        rango abierto (``bytes=0-``). Los bloques de 1 MiB evitan ese bloqueo y
        permiten reanudar con precisión.
        """
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")

        total = int(expected_size) if expected_size else None
        if resume and part.exists():
            done = part.stat().st_size
        else:
            done = 0
            try:
                part.unlink()
            except FileNotFoundError:
                pass

        if total is not None and done > total:
            # Archivo .part corrupto o más grande que el tamaño esperado.
            try:
                part.unlink()
            except FileNotFoundError:
                pass
            done = 0

        if total is not None and done >= total:
            if part.exists():
                os.replace(part, dest)
            if progress:
                progress(total, total)
            return total

        attempts = self.retries + 1
        failures = 0
        completed = False
        last_error: Exception | None = None
        step = max(1, int(range_size))
        timeout = (min(self.timeout, 30.0), max(self.timeout, 60.0))

        while True:
            end = done + step - 1
            if total is not None:
                end = min(end, total - 1)

            request_headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Encoding": "identity",
                **(headers or {}),
                "Range": f"bytes={done}-{end}",
            }

            try:
                with self.session.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=timeout,
                ) as response:
                    status = response.status_code

                    if status == 416:
                        if done == 0:
                            raise DownloadError(
                                "El servidor no tiene datos para este archivo."
                            )
                        completed = True
                        break

                    if status not in (200, 206):
                        if status in (401, 403, 404, 410):
                            raise DownloadError(
                                f"El servidor rechazó la descarga (HTTP {status}). "
                                "El enlace puede haber caducado; vuelve a intentarlo."
                            )
                        raise DownloadError(
                            f"HTTP {status} al descargar el archivo"
                        )

                    if status == 206 and total is None:
                        total = _content_range_total(
                            response.headers.get("Content-Range")
                        )

                    if status == 200 and done > 0:
                        # El servidor ignoró el Range: hay que reescribir.
                        done = 0

                    request_start = done
                    requested = end - request_start + 1
                    received = 0
                    mode = "ab" if done > 0 else "wb"
                    if progress:
                        progress(done, total)

                    with open(part, mode) as handle:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            done += len(chunk)
                            received += len(chunk)
                            if progress:
                                progress(done, total)

                    if status == 200:
                        # Respuesta completa: no se puede pedir más.
                        if total is not None and done < total:
                            raise DownloadError(
                                f"Descarga incompleta: {done} de {total} bytes"
                            )
                        if total is None:
                            total = done
                        completed = True
                        break

                    # status == 206: bloque parcial.
                    if received == 0:
                        raise DownloadError(
                            "El servidor devolvió una respuesta vacía; "
                            "vuelve a intentarlo."
                        )
                    if total is not None:
                        if done >= total:
                            completed = True
                            break
                        # Queda más archivo: se pide el siguiente bloque.
                    elif received < requested:
                        # Sin total conocido, un bloque corto marca el final.
                        total = done
                        completed = True
                        break

                    failures = 0
                    continue

            except DownloadError as exc:
                # Los errores 4xx no se reintentan.
                text = str(exc)
                if "HTTP 4" in text or "rechazó" in text or "no tiene datos" in text:
                    raise
                last_error = exc
            except (requests.RequestException, OSError) as exc:
                last_error = exc

            if part.exists():
                done = part.stat().st_size
            else:
                done = 0
            if total is not None and done >= total:
                completed = True
                break

            failures += 1
            if failures >= attempts:
                break
            time.sleep(min(2.0 ** (failures - 1), 10.0))

        if not completed or not part.exists():
            raise DownloadError(
                f"No se pudo descargar después de {attempts} intentos: {last_error}"
            )

        os.replace(part, dest)
        final_done = dest.stat().st_size
        if total is None:
            total = final_done
        if progress:
            progress(final_done, total)
        return final_done


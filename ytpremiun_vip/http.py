"""Cliente HTTP con reintentos, cookies, rangos y descargas reanudables."""

from __future__ import annotations

import json
import os
import queue
import re
import threading
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
# rangos demasiado grandes. Descargar en bloques acotados evita ese bloqueo y
# además permite reanudar con más precisión.
RANGE_SIZE = 1024 * 1024

# En modo paralelo se usa un bloque algo mayor y varias conexiones. Se probó
# que googlevideo acepta rangos de 2 MiB sin problema; si un servidor devuelve
# la respuesta completa (HTTP 200) se vuelve automáticamente al modo secuencial.
PARALLEL_RANGE_SIZE = 2 * 1024 * 1024
DEFAULT_CONNECTIONS = 6

_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.I)


class _RangeNotSupported(Exception):
    """El servidor ignoró la cabecera Range y devolvió el archivo completo."""


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

        # Cada hilo de descarga usa su propia sesión: requests.Session no es
        # completamente segura para compartir entre hilos.
        self._local = threading.local()

    def _timeout(self) -> tuple[float, float]:
        return (min(self.timeout, 30.0), max(self.timeout, 30.0))

    def _download_timeout(self) -> tuple[float, float]:
        return (min(self.timeout, 30.0), max(self.timeout, 60.0))

    def _build_session(self) -> requests.Session:
        """Crea una sesión nueva con la misma configuración que la principal."""
        session = requests.Session()
        session.headers.update(self.session.headers)
        session.proxies.update(self.session.proxies)
        session.cookies.update(self.session.cookies)
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
            pool_connections=8,
            pool_maxsize=8,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _thread_session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._build_session()
            self._local.session = session
        return session

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

    # ------------------------------------------------------------- descargas
    def _probe_ranges(
        self, url: str, headers: dict[str, str] | None
    ) -> tuple[int | None, bool]:
        """Consulta si el servidor admite Range y cuál es el tamaño total."""
        request_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Encoding": "identity",
            **(headers or {}),
            "Range": "bytes=0-0",
        }
        try:
            with self.session.get(
                url,
                headers=request_headers,
                stream=True,
                timeout=self._download_timeout(),
            ) as response:
                if response.status_code == 206:
                    return (
                        _content_range_total(response.headers.get("Content-Range")),
                        True,
                    )
                if response.status_code == 200:
                    length = response.headers.get("Content-Length")
                    try:
                        total = int(length) if length else None
                    except ValueError:
                        total = None
                    return total, False
        except requests.RequestException:
            return None, False
        return None, False

    def _fetch_range(
        self,
        url: str,
        start: int,
        end: int,
        *,
        headers: dict[str, str] | None,
        attempts: int,
        chunk_size: int,
        session: requests.Session,
    ) -> bytes:
        """Descarga un rango cerrado y lo devuelve en memoria."""
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            request_headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Encoding": "identity",
                **(headers or {}),
                "Range": f"bytes={start}-{end}",
            }
            try:
                with session.get(
                    url,
                    headers=request_headers,
                    stream=True,
                    timeout=self._download_timeout(),
                ) as response:
                    status = response.status_code
                    if status == 200:
                        raise _RangeNotSupported()
                    if status == 416:
                        raise DownloadError(
                            "El servidor no tiene datos para este archivo."
                        )
                    if status != 206:
                        if status in (401, 403, 404, 410):
                            raise DownloadError(
                                f"El servidor rechazó la descarga (HTTP {status}). "
                                "El enlace puede haber caducado; vuelve a intentarlo."
                            )
                        raise DownloadError(
                            f"HTTP {status} al descargar el archivo"
                        )
                    data = bytearray()
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            data.extend(chunk)
                    return bytes(data)
            except _RangeNotSupported:
                raise
            except DownloadError as exc:
                text = str(exc)
                if "rechazó" in text or "no tiene datos" in text:
                    raise
                last_error = exc
            except (requests.RequestException, OSError) as exc:
                last_error = exc
            if attempt < attempts:
                time.sleep(min(2.0 ** (attempt - 1), 10.0))
        raise DownloadError(
            f"No se pudo descargar el bloque {start}-{end}: {last_error}"
        )

    def _parallel_download(
        self,
        url: str,
        destination: Path,
        part: Path,
        total: int,
        *,
        progress: ProgressCallback | None,
        headers: dict[str, str] | None,
        chunk_size: int,
        connections: int,
        attempts: int,
    ) -> int:
        """Descarga el archivo con varias conexiones y reanudación por bloques."""
        range_size = PARALLEL_RANGE_SIZE
        count = (total + range_size - 1) // range_size
        state_path = part.with_name(part.name + ".state")

        completed: set[int] = set()
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                if (
                    data.get("total") == total
                    and data.get("chunk_size") == range_size
                ):
                    completed = {
                        int(index)
                        for index in data.get("completed", [])
                        if 0 <= int(index) < count
                    }
            except (OSError, ValueError, TypeError):
                completed = set()

        if not part.exists():
            completed = set()
            part.touch()
        elif not state_path.exists():
            # Compatibilidad con el .part secuencial de versiones anteriores:
            # esos bytes sí son contiguos y se pueden conservar.
            done = part.stat().st_size
            completed = set(range(min(count, done // range_size)))
            if done >= total:
                completed = set(range(count))

        def chunk_length(index: int) -> int:
            start = index * range_size
            return min(total, start + range_size) - start

        done_bytes = sum(chunk_length(index) for index in completed)
        if progress:
            progress(done_bytes, total)

        pending = [index for index in range(count) if index not in completed]
        if not pending:
            os.replace(part, destination)
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            if progress:
                progress(total, total)
            return total

        tasks: queue.Queue[int] = queue.Queue()
        for index in pending:
            tasks.put(index)

        lock = threading.Lock()
        errors: list[BaseException] = []
        saved_at = [0.0]
        stop = threading.Event()

        def save_state() -> None:
            payload = {
                "total": total,
                "chunk_size": range_size,
                "completed": sorted(completed),
            }
            temporary = state_path.with_name(state_path.name + ".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, state_path)

        def worker() -> None:
            try:
                session = self._thread_session()
                with open(part, "r+b") as handle:
                    while not stop.is_set():
                        try:
                            index = tasks.get_nowait()
                        except queue.Empty:
                            return
                        start = index * range_size
                        end = min(total - 1, start + range_size - 1)
                        data = self._fetch_range(
                            url,
                            start,
                            end,
                            headers=headers,
                            attempts=attempts,
                            chunk_size=chunk_size,
                            session=session,
                        )
                        expected = end - start + 1
                        if len(data) != expected:
                            raise DownloadError(
                                f"Bloque incompleto: {len(data)} de {expected} bytes"
                            )
                        handle.seek(start)
                        handle.write(data)
                        handle.flush()
                        with lock:
                            completed.add(index)
                            done_bytes = sum(
                                chunk_length(item) for item in completed
                            )
                            if progress:
                                progress(done_bytes, total)
                            now = time.monotonic()
                            if (
                                now - saved_at[0] >= 1.0
                                or len(completed) == count
                            ):
                                save_state()
                                saved_at[0] = now
            except BaseException as exc:  # se propaga al hilo principal
                with lock:
                    errors.append(exc)
                while True:
                    try:
                        tasks.get_nowait()
                    except queue.Empty:
                        break

        workers = min(max(1, connections), len(pending))
        # El estado se crea antes de escribir bloques: así un .part sin estado
        # solo puede venir del modo secuencial antiguo.
        with lock:
            save_state()
        threads = [
            threading.Thread(
                target=worker,
                name=f"ytpremiun-dl-{i}",
                daemon=True,
            )
            for i in range(workers)
        ]
        for thread in threads:
            thread.start()
        try:
            for thread in threads:
                while thread.is_alive():
                    thread.join(timeout=0.25)
        except BaseException:
            # Ctrl+C u otra interrupción: se detienen los hilos y se guarda
            # el estado para poder reanudar sin repetir bloques.
            stop.set()
            while True:
                try:
                    tasks.get_nowait()
                except queue.Empty:
                    break
            for thread in threads:
                thread.join(timeout=5)
            with lock:
                try:
                    save_state()
                except OSError:
                    pass
            raise

        if errors:
            with lock:
                try:
                    save_state()
                except OSError:
                    pass
            first = errors[0]
            if isinstance(first, _RangeNotSupported):
                raise first
            raise DownloadError(str(first))

        if len(completed) < count:
            with lock:
                try:
                    save_state()
                except OSError:
                    pass
            raise DownloadError(
                "La descarga quedó incompleta; vuelve a intentarlo para reanudar."
            )

        os.replace(part, destination)
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        if progress:
            progress(total, total)
        return total

    def _sequential_download(
        self,
        url: str,
        destination: Path,
        part: Path,
        total: int | None,
        *,
        progress: ProgressCallback | None,
        headers: dict[str, str] | None,
        resume: bool,
        chunk_size: int,
        range_size: int,
        attempts: int,
    ) -> int:
        """Descarga secuencial en bloques (modo de compatibilidad)."""
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
                os.replace(part, destination)
            if progress:
                progress(total, total)
            return total

        failures = 0
        completed = False
        last_error: Exception | None = None
        step = max(1, int(range_size))
        timeout = self._download_timeout()

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

        os.replace(part, destination)
        final_done = destination.stat().st_size
        if total is None:
            total = final_done
        if progress:
            progress(final_done, total)
        return final_done

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
        connections: int = 1,
    ) -> int:
        """Descarga a un .part y renombra al terminar.

        Con ``connections > 1`` usa varias conexiones en paralelo y guarda un
        archivo de estado para reanudar sin repetir los bloques ya bajados. Si
        el servidor no admite rangos, vuelve automáticamente al modo secuencial
        de bloques de 1 MiB.
        """
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        state_path = part.with_name(part.name + ".state")

        total = int(expected_size) if expected_size else None
        attempts = self.retries + 1
        requested_connections = max(1, min(int(connections), 16))

        if requested_connections > 1:
            probe_total, ranges_ok = self._probe_ranges(url, headers)
            if probe_total is not None:
                total = probe_total
            if ranges_ok and total is not None:
                try:
                    return self._parallel_download(
                        url,
                        dest,
                        part,
                        total,
                        progress=progress,
                        headers=headers,
                        chunk_size=chunk_size,
                        connections=requested_connections,
                        attempts=attempts,
                    )
                except _RangeNotSupported:
                    # El servidor ignora Range: no se puede reanudar en
                    # paralelo. Se empieza de cero en modo secuencial.
                    try:
                        part.unlink()
                    except FileNotFoundError:
                        pass
                    try:
                        state_path.unlink()
                    except FileNotFoundError:
                        pass
                    total = None

        return self._sequential_download(
            url,
            dest,
            part,
            total,
            progress=progress,
            headers=headers,
            resume=resume,
            chunk_size=chunk_size,
            range_size=range_size,
            attempts=attempts,
        )

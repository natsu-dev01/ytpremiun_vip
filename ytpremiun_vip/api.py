"""API de alto nivel de ytpremiun-vip para bots y otros programas.

Uso típico desde un bot de WhatsApp escrito en Python::

    from ytpremiun_vip import descargar_audio, descargar_video

    cancion = descargar_audio("https://youtu.be/VIDEO", carpeta="media")
    print(cancion.archivo)

    video = descargar_video("https://youtu.be/VIDEO", carpeta="media")
    print(video.archivo)

Todas las funciones son síncronas. Si tu bot usa ``asyncio``, ejecútalas en un
hilo aparte con ``asyncio.to_thread`` para no bloquear el bucle de eventos.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .downloader import Downloader, Options, Result
from .errors import ExtractionError, YtPremiunVipError
from .formats import format_table
from .http import DEFAULT_CONNECTIONS, HttpClient
from .innertube import InnertubeClient, VideoInfo
from .urls import parse_input, video_url


@dataclass
class Opciones:
    """Configuración de una descarga.

    Los valores por defecto están pensados para un bot: sin salida por consola
    y sin barra de progreso. Cambia ``silencioso`` y ``progreso`` si quieres
    ver la actividad en la terminal.
    """

    carpeta: str | Path = "downloads"
    plantilla: str = "%(title)s [%(id)s].%(ext)s"
    formato: str | None = None
    solo_audio: bool = False
    formato_audio: str = "mp3"
    calidad_audio: str = "192K"
    contenedor: str = "mp4"
    subtitulos: bool = False
    idiomas_subtitulos: str | None = None
    formato_subtitulos: str = "srt"
    subtitulos_auto: bool = False
    playlist: bool = True
    elementos_playlist: str | None = None
    max_descargas: int | None = None
    historial: str | Path | None = None
    nombres_ascii: bool = False
    sobrescribir: bool = False
    conservar_temporales: bool = False
    silencioso: bool = True
    progreso: bool = False
    reintentos: int = 5
    timeout: float = 20.0
    conexiones: int = DEFAULT_CONNECTIONS
    proxy: str | None = None
    cookies: str | Path | None = None

    def a_options(self) -> Options:
        """Convierte la configuración pública al ``Options`` interno."""
        return Options(
            output_template=self.plantilla,
            paths=Path(self.carpeta),
            format_spec=self.formato,
            audio_only=self.solo_audio,
            audio_format=self.formato_audio,
            audio_quality=self.calidad_audio,
            merge_output_format=self.contenedor,
            write_subs=self.subtitulos,
            sub_langs=self.idiomas_subtitulos,
            sub_format=self.formato_subtitulos,
            write_auto_subs=self.subtitulos_auto,
            playlist=self.playlist,
            playlist_items=self.elementos_playlist,
            max_downloads=self.max_descargas,
            archive=Path(self.historial) if self.historial else None,
            restrict_filenames=self.nombres_ascii,
            force_overwrites=self.sobrescribir,
            keep_files=self.conservar_temporales,
            quiet=self.silencioso,
            no_progress=not self.progreso,
            verbose=False,
            retries=self.reintentos,
            timeout=self.timeout,
            connections=self.conexiones,
            proxy=self.proxy,
            cookies=Path(self.cookies) if self.cookies else None,
        )


@dataclass
class Descarga:
    """Resultado de un video o de un elemento de una playlist."""

    id: str
    url: str
    titulo: str
    autor: str = ""
    duracion: int = 0
    estado: str = "ok"  # ok | omitido | fallido
    archivos: list[Path] = field(default_factory=list)
    error: str | None = None
    info: VideoInfo | None = None
    playlist_id: str | None = None
    playlist_titulo: str | None = None
    playlist_indice: int | None = None

    @property
    def ok(self) -> bool:
        """True si el archivo está disponible (descargado u omitido)."""
        return self.estado in {"ok", "omitido"}

    @property
    def archivo(self) -> Path | None:
        """Primer archivo generado (el video o audio final)."""
        return self.archivos[0] if self.archivos else None

    def to_dict(self) -> dict[str, Any]:
        """Representación serializable, útil para logs o respuestas JSON."""
        return {
            "id": self.id,
            "url": self.url,
            "titulo": self.titulo,
            "autor": self.autor,
            "duracion": self.duracion,
            "estado": self.estado,
            "ok": self.ok,
            "archivo": str(self.archivo) if self.archivo else None,
            "archivos": [str(path) for path in self.archivos],
            "error": self.error,
            "playlist_id": self.playlist_id,
            "playlist_titulo": self.playlist_titulo,
            "playlist_indice": self.playlist_indice,
        }


def _ajustar(opciones: Opciones | None, **overrides: Any) -> Opciones:
    base = opciones if opciones is not None else Opciones()
    limpio = {key: value for key, value in overrides.items() if value is not None}
    return replace(base, **limpio)


def _entradas(urls: str | Iterable[str]) -> list[str]:
    if isinstance(urls, str):
        return [urls]
    return [str(url) for url in urls]


def _convertir(result: Result) -> Descarga:
    job = result.job
    info = result.info
    estados = {"ok": "ok", "skipped": "omitido", "failed": "fallido"}
    return Descarga(
        id=job.video_id,
        url=job.url,
        titulo=info.title if info else (job.entry_title or job.video_id),
        autor=info.author if info else "",
        duracion=info.length_seconds if info else 0,
        estado=estados.get(result.status, result.status),
        archivos=list(result.paths),
        error=result.error,
        info=info,
        playlist_id=job.playlist_id,
        playlist_titulo=job.playlist_title,
        playlist_indice=job.playlist_index,
    )


def _ejecutar(urls: str | Iterable[str], opciones: Opciones) -> list[Descarga]:
    downloader = Downloader(opciones.a_options())
    jobs, errores = downloader.discover(_entradas(urls))

    resultados = [
        Descarga(
            id="",
            url=raw,
            titulo="",
            estado="fallido",
            error=str(error),
        )
        for raw, error in errores
    ]
    if jobs:
        resultados.extend(_convertir(result) for result in downloader.run(jobs))
    return resultados


def _una(url: str, opciones: Opciones) -> Descarga:
    resultados = _ejecutar(url, opciones)
    if not resultados:
        raise ExtractionError("No se encontró ningún video para descargar.")
    for resultado in resultados:
        if not resultado.ok:
            raise YtPremiunVipError(
                resultado.error or f"No se pudo descargar {resultado.url}"
            )
    return resultados[0]


def descargar(
    urls: str | Iterable[str],
    *,
    opciones: Opciones | None = None,
    carpeta: str | Path | None = None,
    solo_audio: bool | None = None,
    formato_audio: str | None = None,
    calidad_audio: str | None = None,
    formato: str | None = None,
    contenedor: str | None = None,
    subtitulos: bool | None = None,
    idiomas_subtitulos: str | None = None,
    playlist: bool | None = None,
    elementos_playlist: str | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
    conexiones: int | None = None,
    silencioso: bool | None = None,
) -> list[Descarga]:
    """Descarga una o varias URLs y devuelve un resultado por cada video.

    Acepta videos, playlists y listas de URLs. Los fallos de un elemento no
    detienen el resto: revísalos con ``resultado.ok`` y ``resultado.error``.
    """
    ajustadas = _ajustar(
        opciones,
        carpeta=carpeta,
        solo_audio=solo_audio,
        formato_audio=formato_audio,
        calidad_audio=calidad_audio,
        formato=formato,
        contenedor=contenedor,
        subtitulos=subtitulos,
        idiomas_subtitulos=idiomas_subtitulos,
        playlist=playlist,
        elementos_playlist=elementos_playlist,
        cookies=cookies,
        proxy=proxy,
        conexiones=conexiones,
        silencioso=silencioso,
    )
    return _ejecutar(urls, ajustadas)


def descargar_video(
    url: str,
    *,
    opciones: Opciones | None = None,
    carpeta: str | Path | None = None,
    formato: str | None = None,
    contenedor: str | None = None,
    playlist: bool | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
    conexiones: int | None = None,
    silencioso: bool | None = None,
) -> Descarga:
    """Descarga un solo video (ignora ``list=`` salvo que pidas la playlist)."""
    ajustadas = _ajustar(
        opciones,
        carpeta=carpeta,
        solo_audio=False,
        formato=formato,
        contenedor=contenedor,
        playlist=False if playlist is None else playlist,
        cookies=cookies,
        proxy=proxy,
        conexiones=conexiones,
        silencioso=silencioso,
    )
    return _una(url, ajustadas)


def descargar_audio(
    url: str,
    *,
    opciones: Opciones | None = None,
    carpeta: str | Path | None = None,
    formato_audio: str | None = None,
    calidad_audio: str | None = None,
    playlist: bool | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
    conexiones: int | None = None,
    silencioso: bool | None = None,
) -> Descarga:
    """Descarga un video como audio (MP3 por defecto)."""
    ajustadas = _ajustar(
        opciones,
        carpeta=carpeta,
        solo_audio=True,
        formato_audio=formato_audio,
        calidad_audio=calidad_audio,
        playlist=False if playlist is None else playlist,
        cookies=cookies,
        proxy=proxy,
        conexiones=conexiones,
        silencioso=silencioso,
    )
    return _una(url, ajustadas)


def descargar_playlist(
    url: str,
    *,
    opciones: Opciones | None = None,
    carpeta: str | Path | None = None,
    solo_audio: bool | None = None,
    formato_audio: str | None = None,
    calidad_audio: str | None = None,
    elementos_playlist: str | None = None,
    max_descargas: int | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
    conexiones: int | None = None,
    silencioso: bool | None = None,
) -> list[Descarga]:
    """Descarga una playlist completa (o los elementos indicados)."""
    ajustadas = _ajustar(
        opciones,
        carpeta=carpeta,
        solo_audio=solo_audio,
        formato_audio=formato_audio,
        calidad_audio=calidad_audio,
        playlist=True,
        elementos_playlist=elementos_playlist,
        max_descargas=max_descargas,
        cookies=cookies,
        proxy=proxy,
        conexiones=conexiones,
        silencioso=silencioso,
    )
    return _ejecutar(url, ajustadas)


def obtener_info(
    url: str,
    *,
    opciones: Opciones | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
) -> VideoInfo:
    """Obtiene los metadatos del video sin descargarlo."""
    ajustadas = _ajustar(opciones, cookies=cookies, proxy=proxy)
    parsed = parse_input(url)
    if not parsed.video_id:
        raise ExtractionError(
            "La URL solo contiene una playlist; indica un video concreto."
        )
    http = HttpClient(
        timeout=ajustadas.timeout,
        retries=ajustadas.reintentos,
        proxy=ajustadas.proxy,
        cookies=Path(ajustadas.cookies) if ajustadas.cookies else None,
    )
    info = InnertubeClient(http).get_video(parsed.video_id)
    if not info.webpage_url:
        info.webpage_url = video_url(info.id)
    return info


def listar_formatos(
    url: str,
    *,
    opciones: Opciones | None = None,
    cookies: str | Path | None = None,
    proxy: str | None = None,
) -> str:
    """Devuelve la tabla de formatos disponibles como texto."""
    info = obtener_info(url, opciones=opciones, cookies=cookies, proxy=proxy)
    return format_table(info.formats)

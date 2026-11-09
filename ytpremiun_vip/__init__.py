"""ytpremiun-vip: descargador de YouTube propio, sin usar yt-dlp.

Expone una API de librería pensada para bots y otros programas::

    from ytpremiun_vip import descargar_audio

    resultado = descargar_audio("https://youtu.be/VIDEO", carpeta="media")
    print(resultado.archivo)
"""

from __future__ import annotations

from .api import (
    Descarga,
    Opciones,
    descargar,
    descargar_audio,
    descargar_playlist,
    descargar_video,
    listar_formatos,
    obtener_info,
)
from .errors import (
    DownloadError,
    ExtractionError,
    MediaError,
    NetworkError,
    UnsupportedError,
    YtPremiunVipError,
)

__version__ = "0.4.0"

__all__ = [
    "__version__",
    "Descarga",
    "Opciones",
    "descargar",
    "descargar_audio",
    "descargar_playlist",
    "descargar_video",
    "listar_formatos",
    "obtener_info",
    "YtPremiunVipError",
    "NetworkError",
    "ExtractionError",
    "UnsupportedError",
    "DownloadError",
    "MediaError",
]

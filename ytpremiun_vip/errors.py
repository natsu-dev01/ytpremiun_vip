"""Errores propios de ytpremiun_vip."""

from __future__ import annotations


class YtPremiunVipError(Exception):
    """Error base de la aplicación."""


class NetworkError(YtPremiunVipError):
    """Fallo de red al contactar con YouTube."""


class ExtractionError(YtPremiunVipError):
    """No se pudo extraer la información del video o de la lista."""


class UnsupportedError(YtPremiunVipError):
    """El contenido no se puede descargar (directo, privado, DRM...)."""


class DownloadError(YtPremiunVipError):
    """Fallo al descargar un archivo."""


class MediaError(YtPremiunVipError):
    """Fallo al procesar multimedia con ffmpeg."""


class FFmpegNotFoundError(MediaError):
    """ffmpeg no está instalado o no se encuentra en el PATH."""

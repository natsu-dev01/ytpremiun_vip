/**
 * Errores del motor nativo de ytpremiun-vip.
 *
 * Todas las excepciones heredan de `YtPremiunError`, que es el nombre que
 * usaba el wrapper de Node.js, así que `catch (error) { if (error instanceof
 * YtPremiunError) ... }` sigue funcionando.
 */

"use strict";

class YtPremiunError extends Error {
  constructor(mensaje, { codigo = null, stderr = "", resultados = [], cause } = {}) {
    super(mensaje);
    this.name = this.constructor.name;
    this.codigo = codigo;
    this.stderr = stderr;
    this.resultados = resultados;
    if (cause !== undefined) this.cause = cause;
  }
}

class YtPremiunVipError extends YtPremiunError {}

class NetworkError extends YtPremiunVipError {}

class ExtractionError extends YtPremiunVipError {}

class UnsupportedError extends ExtractionError {}

class DownloadError extends YtPremiunVipError {}

class MediaError extends YtPremiunVipError {}

class FFmpegNotFoundError extends MediaError {}

class RangeNotSupportedError extends DownloadError {}

module.exports = {
  YtPremiunError,
  YtPremiunVipError,
  NetworkError,
  ExtractionError,
  UnsupportedError,
  DownloadError,
  MediaError,
  FFmpegNotFoundError,
  RangeNotSupportedError,
};

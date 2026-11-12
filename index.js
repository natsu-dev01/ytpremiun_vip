/**
 * ytpremiun-vip — descargador de YouTube para Node.js.
 *
 * El motor está implementado íntegramente en JavaScript: no necesita Python,
 * `requests` ni ningún paquete externo obligatorio. Usa la API InnerTube de
 * YouTube, descarga por rangos en paralelo y, si hace falta unir video+audio o
 * convertir audio, utiliza ffmpeg (preferiblemente el binario de la dependencia
 * opcional `ffmpeg-static`).
 *
 * La API pública mantiene los mismos nombres y el mismo formato de resultados
 * que la versión anterior del wrapper:
 *
 *   const { descargarAudio } = require("ytpremiun-vip");
 *   const audio = await descargarAudio("https://youtu.be/VIDEO", {
 *     carpeta: "media",
 *     formatoAudio: "mp3",
 *   });
 *   console.log(audio.archivo);
 */

"use strict";

const api = require("./lib/api");
const {
  YtPremiunError,
  YtPremiunVipError,
  NetworkError,
  ExtractionError,
  UnsupportedError,
  DownloadError,
  MediaError,
  FFmpegNotFoundError,
  RangeNotSupportedError,
} = require("./lib/errors");

module.exports = {
  ...api,
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

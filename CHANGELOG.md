# Changelog

Todos los cambios importantes de **ytpremiun-vip** se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el versionado sigue [SemVer](https://semver.org/lang/es/).

## [0.1.0] - 2026-11-07

### Añadido

- Motor propio basado en la API InnerTube, sin yt-dlp ni pytube.
- Cliente principal `VISIONOS` con `visitorData` y clientes de respaldo
  `ANDROID`, `IOS` y `ANDROID_VR`.
- Descarga de video MP4 y unión con audio mediante ffmpeg.
- Extracción de audio en MP3, M4A, OPUS, WAV y FLAC.
- Descarga de playlists, selección de elementos y eliminación de duplicados.
- Cola de varias URLs y lectura desde archivo de texto.
- Subtítulos manuales y automáticos en SRT, VTT y XML.
- Descargas reanudables por bloques `Range` y archivo de historial.
- API de librería para bots: `descargar`, `descargar_video`,
  `descargar_audio`, `descargar_playlist`, `obtener_info` y
  `listar_formatos`.
- Wrapper oficial de Node.js instalable con npm (`index.js`, `index.d.ts` y
  `package.json`) para bots de `whatsapp-web.js`.
- Modo `--json` con rutas, estado y errores para integraciones en Node.js.
- Ejemplo de bot para `whatsapp-web.js` en `examples/bot_whatsapp.js`.
- Documentación en español, tests unitarios y CI con GitHub Actions.

### Corregido

- El error `HTTP 403` que aparecía después del primer MiB al usar clientes
  móviles antiguos. Ahora el cliente `VISIONOS` sirve el archivo completo.

### Seguridad

- No se incluyen cookies ni credenciales en el repositorio.

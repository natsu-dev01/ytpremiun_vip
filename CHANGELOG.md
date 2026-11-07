# Changelog

Todos los cambios importantes de **ytpremiun-vip** se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el versionado sigue [SemVer](https://semver.org/lang/es/).

## [0.3.0] - 2026-11-07

### Añadido

- Dependencia `imageio-ffmpeg`: `pip install` trae un binario de FFmpeg
  incluido, así que ya no hace falta instalarlo ni configurar el `PATH`.
- `find_ffmpeg()` detecta primero `FFMPEG` y el `PATH`, después el binario
  incluido y por último las rutas habituales de Windows.
- `extract_audio()` copia el archivo directamente cuando la extensión de
  origen y destino coinciden (por ejemplo M4A a M4A), sin ejecutar FFmpeg.
- Tests del binario incluido y de la copia directa sin FFmpeg.

### Cambiado

- El mensaje de error de FFmpeg ahora explica cómo reinstalar el paquete o
  definir la variable `FFMPEG`.
- Documentación de requisitos, instalación y wrapper de Node.js actualizada.

## [0.2.0] - 2026-11-07

### Añadido

- Descarga paralela por rangos con `--connections` (6 conexiones por defecto).
  Se puede volver al modo secuencial con `--connections 1`.
- Reanudación por bloques con un archivo `.part.state`, incluso si se
  interrumpe la descarga con Ctrl+C.
- Parámetros `conexiones` en la API de Python y `conexiones`/`connections` en
  el wrapper de Node.js.
- Pruebas de descarga paralela, reanudación y vuelta al modo secuencial.

### Cambiado

- El cliente HTTP usa una sesión independiente por hilo para evitar compartir
  `requests.Session` entre conexiones.
- Si el servidor ignora la cabecera `Range` y devuelve todo el archivo, la
  descarga vuelve automáticamente al modo secuencial.

### Rendimiento

- Pruebas reales en Windows con 6 conexiones (1 y 2 horas):
  - audio M4A de 1 h (55,6 MiB): de 15,2 s a 5,5 s.
  - audio M4A de 2 h (113,6 MiB): de 33,6 s a 9,2 s.
  - video 144p de 2 h (36,5 MiB): de 13,5 s a 4,7 s.

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
  `package.json`) para bots de Baileys y `whatsapp-web.js`.
- Modo `--json` con rutas, estado y errores para integraciones en Node.js.
- Ejemplo de bot para `whatsapp-web.js` en `examples/bot_whatsapp.js`.
- Ejemplo de bot para Baileys en `examples/bot_baileys.js`.
- Documentación en español, tests unitarios y CI con GitHub Actions.

### Corregido

- El error `HTTP 403` que aparecía después del primer MiB al usar clientes
  móviles antiguos. Ahora el cliente `VISIONOS` sirve el archivo completo.

### Seguridad

- No se incluyen cookies ni credenciales en el repositorio.

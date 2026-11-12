<p align="center">
  <img src="assets/ytpremiun-vip.jpeg" alt="ytpremiun-vip" width="800">
</p>

<h1 align="center">ytpremiun-vip</h1>

[![Tests](https://github.com/natsu-dev01/ytpremiun_vip/actions/workflows/tests.yml/badge.svg)](https://github.com/natsu-dev01/ytpremiun_vip/actions/workflows/tests.yml)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Node.js 18+](https://img.shields.io/badge/node.js-18%2B-green.svg)](https://nodejs.org/)

Descargador de YouTube escrito desde cero. **No usa yt-dlp** (ni pytube, ni
youtube-dl): habla directamente con la API interna de YouTube (InnerTube), elige
los formatos y descarga las URLs que el propio reproductor utiliza.

Está disponible de dos formas con el mismo comportamiento:

- **Paquete npm (Node.js 18+):** motor completo en JavaScript. **No necesita
  Python.**
- **Paquete pip (Python 3.10+):** implementación original en Python.

Permite:

- Descargar **video MP4** (con audio unido) o el contenedor que prefieras.
- Extraer **solo audio** en MP3, M4A, OPUS, FLAC o WAV.
- Descargar **playlists** completas o solo algunos elementos.
- Encolar **varias URLs** a la vez, incluso desde un archivo de texto.
- Descargar **subtítulos** manuales y automáticos en SRT, VTT o XML.
- Reanudar descargas interrumpidas y recordar lo ya descargado con un archivo
  de historial.
- Integrarse como **librería** en bots y otros programas (`descargar_audio`,
  `descargar_video`, `descargar_playlist`).
- Usarse desde **Node.js** con el paquete npm incluido, sin instalar Python
  (`npm install https://github.com/natsu-dev01/ytpremiun_vip`).

> ⚠️ **Aviso legal:** descarga únicamente contenido propio, de dominio público
> o para el que tengas permiso. Respeta los Términos de Servicio de YouTube y
> los derechos de autor de cada obra.

---

## Requisitos

### Paquete npm (Node.js)

| Requisito | Detalle |
| --- | --- |
| Node.js | 18 o superior |
| ffmpeg | Opcional. `npm install` instala `ffmpeg-static` automáticamente. |

El paquete npm **no necesita Python**: el motor (InnerTube, selección de
formatos, descargas por rangos, playlists y subtítulos) está implementado en
JavaScript dentro de `lib/`. FFmpeg solo hace falta para unir video+audio o
convertir audio; si no está disponible, los formatos progresivos y las pistas
M4A directas siguen funcionando.

### Paquete pip (Python)

| Requisito | Detalle |
| --- | --- |
| Python | 3.10 o superior |
| `requests` | Se instala con el paquete |
| `ffmpeg` | Se instala automáticamente con `imageio-ffmpeg` |

### FFmpeg

En **npm**, `ffmpeg-static` se instala como dependencia opcional y el motor usa
ese binario automáticamente. Si ya tienes FFmpeg instalado, se usa ese primero
(variable `FFMPEG` o `PATH`). Puedes omitir la dependencia con
`npm install --omit=optional` y definir `FFMPEG` o instalar ffmpeg en el
sistema.

En **pip**, el paquete incluye **imageio-ffmpeg**, que trae un binario de FFmpeg
al instalarse. No necesitas instalarlo ni configurar el `PATH`.

Si prefieres instalarlo manualmente:

- **Windows:** descárgalo de <https://ffmpeg.org/download.html>, descomprímelo
  y añade la carpeta `bin` al `PATH`. También se detectan automáticamente
  `C:\ffmpeg\bin\ffmpeg.exe` y `C:\Program Files\ffmpeg\bin\ffmpeg.exe`.
- **macOS:** `brew install ffmpeg`
- **Debian/Ubuntu:** `sudo apt install ffmpeg`

Puedes indicar una ruta concreta con la variable de entorno `FFMPEG`:

```bash
set FFMPEG=C:\ruta\a\ffmpeg.exe        # Windows (cmd)
$env:FFMPEG="C:\ruta\a\ffmpeg.exe"     # Windows (PowerShell)
export FFMPEG=/usr/local/bin/ffmpeg    # Linux/macOS
```

## Instalación

### Paquete Python (pip)

```bash
# 1. Clona el repositorio y entra en la carpeta
git clone https://github.com/natsu-dev01/ytpremiun_vip.git
cd ytpremiun_vip

# 2. (Recomendado) crea un entorno virtual
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS

# 3. Instala el paquete
pip install -e .

# 4. Comprueba que funciona
ytpremiun-vip --help
# Si la carpeta Scripts de Python no está en el PATH:
python -m ytpremiun_vip --help
```

`pip` instala también `imageio-ffmpeg`, que incluye el binario de FFmpeg.

Si prefieres no instalarlo, también funciona como módulo:

```bash
pip install -r requirements.txt
python -m ytpremiun_vip --help
```

### Instalación en un bot de Node.js (npm)

El paquete npm incluye el **motor nativo en JavaScript** y el comando
`ytpremiun-vip`. Instálalo desde GitHub en la carpeta de tu bot:

```bash
npm install https://github.com/natsu-dev01/ytpremiun_vip
```

También puedes usar la forma `github:`:

```bash
npm install github:natsu-dev01/ytpremiun_vip
```

**No necesitas Python, `pip` ni `requests`.** `npm install` instala además
`ffmpeg-static` como dependencia opcional para unir video+audio y convertir
audio. Si no quieres ese binario, usa `npm install --omit=optional` y define
`FFMPEG` o instala ffmpeg en el sistema.

Comprueba que todo está listo desde tu bot:

```js
const { verificar } = require("ytpremiun-vip");

console.log(await verificar());
// { ok: true, motor: "node", node: "v22...", version: "0.5.0",
//   ffmpeg: "C:\\...\\ffmpeg.exe", error: null }
```

También puedes usar el CLI sin instalarlo de forma global:

```bash
npx ytpremiun-vip --help
npx ytpremiun-vip -x --audio-format mp3 "https://youtu.be/jNQXAC9IVRw"
```

Si `ffmpeg` aparece como `null`, instala la dependencia opcional o indica la
ruta manualmente:

```bash
npm install ffmpeg-static
set FFMPEG=C:\ruta\a\ffmpeg.exe        # Windows cmd
$env:FFMPEG="C:\ruta\a\ffmpeg.exe"    # PowerShell
export FFMPEG=/usr/local/bin/ffmpeg    # Linux/macOS
```

> El paquete Python (`pip`) sigue siendo independiente y conserva sus propios
> requisitos. Elegir npm no instala nada de Python.

---

## Uso rápido

El comando `ytpremiun-vip` es el mismo en pip y en npm (`npx ytpremiun-vip`).
Los ejemplos siguientes funcionan en ambos; el paquete npm no requiere Python.

```bash
# Video MP4 con la mejor calidad (video + audio unidos)
ytpremiun-vip "https://www.youtube.com/watch?v=jNQXAC9IVRw"

# Solo audio en MP3 192 kbps
ytpremiun-vip -x "https://youtu.be/jNQXAC9IVRw"

# Audio en M4A sin recodificar (más rápido y sin pérdida)
ytpremiun-vip -x --audio-format m4a "https://youtu.be/jNQXAC9IVRw"

# Ver los formatos disponibles sin descargar
ytpremiun-vip -F "https://youtu.be/jNQXAC9IVRw"

# Elegir un formato concreto: 1080p H.264 + audio M4A
ytpremiun-vip -f "137+140" "https://youtu.be/jNQXAC9IVRw"

# Mejor video de hasta 720p + mejor audio
ytpremiun-vip -f "bv*[height<=720]+ba" "https://youtu.be/jNQXAC9IVRw"

# Playlist completa en una carpeta concreta
ytpremiun-vip -P "Mis descargas" "https://www.youtube.com/playlist?list=PL..."

# Solo los elementos 1 a 5 y el 8 de la playlist
ytpremiun-vip --playlist-items "1-5,8" "https://www.youtube.com/playlist?list=PL..."

# Descargar el video aunque la URL traiga una lista
ytpremiun-vip --no-playlist "https://www.youtube.com/watch?v=...&list=..."

# Subtítulos en español e inglés
ytpremiun-vip --write-subs --sub-langs es,en "https://youtu.be/jNQXAC9IVRw"

# Incluir también los subtítulos automáticos
ytpremiun-vip --write-subs --write-auto-subs --sub-langs all "https://youtu.be/..."

# Varias URLs desde un archivo (una por línea, # para comentarios)
ytpremiun-vip -a urls.txt

# Cola de varias URLs en un solo comando
ytpremiun-vip URL1 URL2 URL3

# Recordar lo descargado y no repetirlo en la próxima ejecución
ytpremiun-vip --download-archive historial.txt "https://www.youtube.com/playlist?list=PL..."

# Resultado en JSON con la ruta final (ideal para bots)
ytpremiun-vip -x --json "https://youtu.be/jNQXAC9IVRw"
```

---

## Velocidad de descarga

Por defecto cada archivo se descarga con **6 conexiones en paralelo** y
bloques de 2 MiB. Esto acelera bastante los videos largos porque YouTube
limita la velocidad de una sola conexión. Si tu red o un proxy no admiten
varias conexiones, usa el modo secuencial:

```bash
# Más conexiones (más rápido si tu red lo permite)
ytpremiun-vip --connections 8 "https://youtu.be/VIDEO"

# Modo secuencial clásico
ytpremiun-vip --connections 1 "https://youtu.be/VIDEO"

# En la API de Python
from ytpremiun_vip import Opciones, descargar_audio
descargar_audio("https://youtu.be/VIDEO", opciones=Opciones(conexiones=8))
```

Mejoras adicionales que se aplican solas:

- **Video y audio a la vez.** En calidades 1080p o superiores YouTube entrega
  dos pistas separadas; ahora se descargan simultáneamente en lugar de una
  detrás de otra.
- **Sin petición de sondeo.** Si YouTube ya indica el tamaño del archivo, se
  empieza a descargar directamente y se ahorra una ida y vuelta por pista.
- **Bloques de lectura de 1 MiB.** Menos llamadas internas y menos escrituras,
  especialmente con conexiones rápidas.
- **Varios videos en paralelo.** En playlists o listas de URLs puedes bajar
  varios elementos a la vez:

```bash
ytpremiun-vip -j 3 "https://www.youtube.com/playlist?list=PL..."
```

```python
from ytpremiun_vip import Opciones, descargar_playlist
descargar_playlist("https://www.youtube.com/playlist?list=PL...", trabajos=3)
```

```js
await descargarPlaylist(url, { trabajos: 3 });
```

La descarga se guarda en un archivo `.part` y un `.part.state`. Si se corta
la conexión o pulsas `Ctrl+C`, vuelve a ejecutar el mismo comando: se reanudan
solo los bloques que faltan. Si el servidor no admite rangos, la librería
vuelve automáticamente al modo secuencial.

Resultados medidos en Windows con 6 conexiones:

| Prueba | Antes (1 conexión) | Ahora (6 conexiones) |
| --- | --- | --- |
| Audio M4A 1 h (55,6 MiB) | 15,2 s | **5,5 s** |
| Audio M4A 2 h (113,6 MiB) | 33,6 s | **9,2 s** |
| Video 144p 2 h (36,5 MiB) | 13,5 s | **4,7 s** |

> La velocidad depende de tu ISP, del nodo de YouTube y de la hora. Los
> tiempos de MP3/MP4 finales incluyen además la conversión o unión con ffmpeg.

### Si el MP3 tarda más, es por la conversión

En los archivos de audio, la descarga ya es rápida; el tiempo extra de MP3 lo
consume ffmpeg al recodificar. Si no necesitas MP3, usa **M4A**: se copia el
audio original de YouTube sin recodificar (no necesita FFmpeg) y termina en
segundos.

| Audio | MP3 192K | M4A (copia directa) |
| --- | --- | --- |
| 1 h | ~20 s | **~6 s** |
| 2 h | ~38 s | **~11 s** |

```bash
ytpremiun-vip -x --audio-format m4a "https://youtu.be/VIDEO"
```

```python
descargar_audio("https://youtu.be/VIDEO", formato_audio="m4a")
```

Probar distintos niveles de compresión de MP3 (`-compression_level`) apenas
supone un 5–10 % de mejora, así que no compensa el riesgo de perder calidad.
La decodificación MP3 es un proceso ligado a la CPU: para reducir el tiempo de
forma drástica hay que evitar la recodificación.

---

## API HTTP para VPS

El repositorio incluye `api/`, un servidor HTTP nativo (sin dependencias) con
cola de trabajos, progreso, API key y entrega de archivos reanudable. Está
pensado para un VPS pequeño.

```bash
git clone https://github.com/natsu-dev01/ytpremiun_vip.git /opt/ytpremiun
bash /opt/ytpremiun/api/install.sh
```

El script instala Node.js y ffmpeg, genera la API key en
`/etc/ytpremiun-api.env` y arranca el servicio systemd `ytpremiun-api`.

```bash
curl -X POST http://IP:3000/download \
  -H "X-API-Key: TU_CLAVE" -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEO","modo":"audio"}'
```

La documentación completa (endpoints, opciones, límites y HTTPS) está en
[`api/README.md`](api/README.md).

---

## Uso como librería (bots)

### Python

El paquete se importa como `ytpremiun_vip` y está pensado para que un bot
descargue y reciba la ruta del archivo sin depender de la terminal. Por
defecto no imprime nada ni muestra barra de progreso.

```python
from ytpremiun_vip import Opciones, descargar_audio, descargar_video

# Solo audio MP3 en la carpeta del bot
cancion = descargar_audio(
    "https://youtu.be/jNQXAC9IVRw",
    carpeta="media/audio",
    calidad_audio="192K",
)
if cancion.ok:
    print(cancion.archivo)   # Path('media/audio/Titulo [id].mp3')
    print(cancion.titulo, cancion.autor, cancion.duracion)

# Video MP4 con audio unido
video = descargar_video(
    "https://youtu.be/jNQXAC9IVRw",
    carpeta="media/video",
)
print(video.archivo)

# Playlist completa o solo algunos elementos
canciones = descargar_playlist(
    "https://www.youtube.com/playlist?list=PL...",
    carpeta="media/playlist",
    solo_audio=True,
    formato_audio="m4a",
    elementos_playlist="1-5",
    max_descargas=5,
)
for item in canciones:
    if item.ok:
        print(item.playlist_indice, item.archivo)
```

Para reutilizar configuración (cookies, proxy, reintentos, subtítulos...) crea
un objeto `Opciones`:

```python
from ytpremiun_vip import Opciones, descargar

config = Opciones(
    carpeta="media",
    cookies="cookies.txt",
    reintentos=3,
    timeout=30,
    subtitulos=True,
    idiomas_subtitulos="es,en",
)

resultados = descargar(
    ["https://youtu.be/VIDEO1", "https://youtu.be/VIDEO2"],
    opciones=config,
)
for resultado in resultados:
    if not resultado.ok:
        print("Falló:", resultado.url, resultado.error)
```

### Funciones disponibles

| Función | Devuelve | Descripción |
| --- | --- | --- |
| `descargar(urls, ...)` | `list[Descarga]` | Una o varias URLs, videos o playlists. No se detiene si un elemento falla. |
| `descargar_video(url, ...)` | `Descarga` | Un video con audio. Ignora `list=` salvo que uses `playlist=True`. |
| `descargar_audio(url, ...)` | `Descarga` | Un video como audio (MP3 por defecto). |
| `descargar_playlist(url, ...)` | `list[Descarga]` | Playlist completa o los elementos indicados. |
| `obtener_info(url, ...)` | `VideoInfo` | Metadatos del video sin descargar. |
| `listar_formatos(url, ...)` | `str` | Tabla de formatos disponibles como texto. |

Los parámetros más usados son `carpeta`, `formato_audio`, `calidad_audio`,
`formato` (selector), `contenedor`, `conexiones`, `trabajos` (varios videos a
la vez), `subtitulos`, `cookies`, `proxy`, `silencioso`, `opciones`.

### Resultado de una descarga

Cada `Descarga` expone:

| Campo | Significado |
| --- | --- |
| `ok` | `True` si el archivo está disponible (descargado u omitido). |
| `estado` | `ok`, `omitido` o `fallido`. |
| `id`, `url`, `titulo`, `autor`, `duracion` | Datos del video. |
| `archivo` | Primer archivo final (`Path`) o `None`. |
| `archivos` | Todos los archivos, incluidos subtítulos. |
| `error` | Mensaje de error si falló. |
| `playlist_id`, `playlist_titulo`, `playlist_indice` | Datos de la playlist. |
| `to_dict()` | Versión serializable para logs o JSON. |

`descargar()` devuelve los fallos dentro de la lista (revisa `resultado.ok`);
las funciones de un solo elemento (`descargar_video`, `descargar_audio`)
lanzan `YtPremiunVipError` si la descarga falla.

Las funciones de Python son síncronas. En un bot con `asyncio`, ejecútalas en
un hilo para no bloquear el bucle:

```python
import asyncio
from ytpremiun_vip import descargar_audio

resultado = await asyncio.to_thread(
    descargar_audio,
    "https://youtu.be/jNQXAC9IVRw",
    carpeta="media",
)
```

### Node.js

El paquete npm expone las mismas funciones como promesas y **no ejecuta
Python**. No necesitas `child_process` ni analizar la salida de la terminal:

```js
const { descargarAudio, descargarVideo } = require("ytpremiun-vip");

const audio = await descargarAudio("https://youtu.be/jNQXAC9IVRw", {
  carpeta: "media",
  formatoAudio: "mp3",
  calidadAudio: "192K",
});
console.log(audio.archivo); // ruta final del archivo

const video = await descargarVideo("https://youtu.be/jNQXAC9IVRw", {
  carpeta: "media",
  contenedor: "mp4",
});
console.log(video.archivo);
```

El paquete solo descarga y devuelve la ruta; el envío por WhatsApp depende de
tu librería. Tienes ejemplos completos para:

- [Baileys](examples/bot_baileys.js) (`@whiskeysockets/baileys`).
- [`whatsapp-web.js`](examples/bot_whatsapp.js).

### Funciones del paquete npm (Node.js)

| Función | Devuelve | Descripción |
| --- | --- | --- |
| `descargar(urls, opciones)` | `Promise<Resultado[]>` | Una o varias URLs. No lanza excepción si falla un elemento. |
| `descargarAudio(url, opciones)` | `Promise<Resultado>` | Audio (MP3 por defecto). Lanza `YtPremiunError` si falla. |
| `descargarVideo(url, opciones)` | `Promise<Resultado>` | Video con audio. Lanza `YtPremiunError` si falla. |
| `descargarPlaylist(url, opciones)` | `Promise<Resultado[]>` | Playlist completa o los elementos indicados. |
| `obtenerInfo(url, opciones)` | `Promise<InfoVideo>` | Metadatos del video sin descargar. |
| `listarFormatos(url, opciones)` | `Promise<string>` | Tabla de formatos disponibles. |
| `verificar()` | `Promise<Verificacion>` | Comprueba el motor Node y ffmpeg; no requiere Python. |

Las opciones del paquete npm usan nombres en español: `carpeta`, `formato`,
`formatoAudio`, `calidadAudio`, `contenedor`, `playlist`,
`elementosPlaylist`, `subtitulos`, `cookies`, `proxy`, `conexiones`,
`trabajos`, `timeout`, `reintentos`, entre otras. Cada resultado tiene `ok`,
`estado`, `titulo`, `autor`, `duracion`, `archivo`, `archivos` y `error`,
exactamente igual que la API de Python.

---

## Opciones

| Opción | Descripción |
| --- | --- |
| `URL...` | Una o más URLs de YouTube (video, `youtu.be`, Shorts, directo terminado o playlist). |
| `-a, --batch-file ARCHIVO` | Lee URLs de un archivo de texto, una por línea. |
| `-P, --paths CARPETA` | Carpeta de salida. Por defecto `downloads`. |
| `-o, --output PLANTILLA` | Plantilla del nombre de archivo. Por defecto `%(title)s [%(id)s].%(ext)s`. |
| `-f, --format SELECTOR` | Selector de formato. Por defecto `bv*+ba/b`. |
| `-F, --list-formats` | Muestra la tabla de formatos y no descarga. |
| `-x, --extract-audio` | Descarga solo el audio. |
| `--audio-format FORMATO` | `mp3`, `m4a`, `opus`, `wav`, `flac` o `best`. Por defecto `mp3`. |
| `--audio-quality BITRATE` | Bitrate al recodificar (`128K`, `192K`, `320K`...). Por defecto `192K`. |
| `--merge-output-format` | Contenedor al unir video+audio: `mp4`, `mkv` o `webm`. Por defecto `mp4`. |
| `--write-subs, --subs` | Descarga subtítulos. |
| `--sub-langs IDIOMAS` | Idiomas separados por coma (`es,en`) o `all`. Por defecto, el idioma del audio. |
| `--sub-format FORMATO` | `srt`, `vtt` o `xml`. Por defecto `srt`. |
| `--write-auto-subs` | Incluye subtítulos automáticos (ASR). |
| `--playlist / --no-playlist` | Descarga la playlist de la URL (por defecto) o solo el video. |
| `--playlist-items LISTA` | Elementos a descargar: `1-5,8,10-`. |
| `--max-downloads N` | Máximo de videos en esta ejecución. |
| `--download-archive ARCHIVO` | Archivo con IDs ya descargados para omitirlos. |
| `--restrict-filenames` | Nombres de archivo solo ASCII. |
| `--force-overwrites` | Sobrescribe archivos existentes. |
| `--keep-files` | Conserva los archivos temporales de video/audio. |
| `--no-progress` | Oculta la barra de progreso. |
| `-q, --quiet` | Modo silencioso. |
| `-v, --verbose` | Muestra trazas detalladas de errores. |
| `--retries N` | Reintentos por descarga. Por defecto `5`. |
| `--connections N` | Conexiones en paralelo por descarga. Por defecto `6`; usa `1` para el modo secuencial. |
| `-j, --jobs N` | Videos que se descargan a la vez en playlists o listas de URLs. Por defecto `1`. |
| `--timeout SEGUNDOS` | Timeout de red. Por defecto `20`. |
| `--proxy URL` | Proxy HTTP/SOCKS. |
| `--cookies ARCHIVO` | Cookies en formato Netscape (exportadas del navegador). |
| `--print-json` | Imprime los metadatos del video en JSON. |
| `--json` | Imprime el resultado de las descargas en JSON (rutas, estado y errores). Ideal para bots; silencia la salida normal. |
| `--flat-playlist` | Imprime las URLs de la playlist sin descargar. |
| `--simulate` | Muestra qué se descargaría, sin descargar. |
| `--version` | Muestra la versión. |

### Plantilla de nombres

Puedes usar los siguientes campos en `-o`:

| Campo | Significado |
| --- | --- |
| `%(title)s` | Título del video |
| `%(id)s` | ID de YouTube |
| `%(ext)s` | Extensión final |
| `%(uploader)s`, `%(channel)s` | Autor/canal |
| `%(channel_id)s` | ID del canal |
| `%(duration)s`, `%(duration_string)s` | Duración en segundos o `HH:MM:SS` |
| `%(upload_date)s` | Fecha `AAAAMMDD` |
| `%(view_count)s` | Visualizaciones |
| `%(playlist_id)s`, `%(playlist_title)s` | Datos de la playlist |
| `%(playlist_index)03d` | Índice con ceros a la izquierda |
| `%(resolution)s`, `%(height)s`, `%(fps)s` | Datos del formato |
| `%(format_id)s` | itag del formato |

Ejemplos:

```bash
# Organizar por canal y fecha
ytpremiun-vip -o "%(uploader)s/%(upload_date)s - %(title)s.%(ext)s" URL

# Nombres seguros para cualquier sistema
ytpremiun-vip --restrict-filenames -o "%(title)s.%(ext)s" URL

# Numerar los elementos de una playlist
ytpremiun-vip -o "%(playlist_index)03d - %(title)s.%(ext)s" "https://.../playlist?list=..."
```

La plantilla se sanea automáticamente: caracteres prohibidos en Windows,
nombres reservados (`CON`, `NUL`, `COM1`...) y rutas que intenten escapar de la
carpeta de salida.

---

## Formatos

`-F` muestra una tabla con los itags disponibles:

```text
  ID  TIPO         EXT   RES        FPS  VCODEC              ACODEC             TAMAÑO  NOTA
 137  video        mp4   1080p       30  avc1.640028         -                  45.2 MiB  1080p
 140  audio        m4a   audio          - mp4a.40.2          128 kbps            4.1 MiB  medium
  18  video+audio  mp4   360p        30  avc1.42001E         mp4a.40.2           9.8 MiB  360p
```

Selectores habituales:

| Selector | Resultado |
| --- | --- |
| `bv*+ba/b` | Mejor video + mejor audio; si no hay pistas separadas, el mejor progresivo. |
| `best` | Mejor formato progresivo (video+audio). |
| `worst` | Peor formato con video. |
| `bestaudio` | Mejor pista solo audio. |
| `137+140` | itag de video + itag de audio. |
| `bv*[height<=1080]+ba` | Mejor video de 1080p o menos + mejor audio. |
| `bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]` | Fuerza MP4/M4A. |
| `bestvideo[height>=720]` | Solo video (sin audio) de 720p o más. |

Filtros disponibles: `height`, `width`, `fps`, `ext`, `vcodec`, `acodec`,
`filesize`, `tbr`, `abr`, `itag`. Operadores: `=`, `!=`, `<`, `<=`, `>`, `>=`,
`^=` (empieza por), `$=` (termina en), `*=` (contiene).

Cuando el video y el audio van separados, se descargan **a la vez** a
`.ytpremiun-vip-tmp/` y se unen con ffmpeg **sin recodificar**. Si el MP4 falla, se
reintenta automáticamente en MKV.

---

## Playlists

- Se detectan por el parámetro `list=` de la URL.
- `--no-playlist` descarga solo el video de la URL.
- `--playlist-items` acepta rangos abiertos: `1-5,8,10-`.
- `--max-downloads` limita cuántos se procesan.
- `--flat-playlist` lista las URLs sin descargar.
- Si la URL es solo una playlist (sin `v=`), se descarga la lista completa.
- Se eliminan duplicados automáticamente.

```bash
# Ver las primeras URLs de una playlist
ytpremiun-vip --flat-playlist --playlist-items 1-10 "https://.../playlist?list=PL..."

# Descargar solo el audio de una playlist
ytpremiun-vip -x --audio-format mp3 "https://.../playlist?list=PL..."
```

## Subtítulos

- Por defecto se descarga el idioma del audio; usa `--sub-langs` para elegir.
- `--write-auto-subs` incluye los generados automáticamente por YouTube.
- `--sub-format` admite `srt`, `vtt` o `xml` (timedtext original).
- Los archivos se guardan junto al video: `Título [id].es.srt`,
  `Título [id].es.auto.srt`...

```bash
ytpremiun-vip --write-subs --sub-langs "es,en" URL
ytpremiun-vip --write-subs --write-auto-subs --sub-langs all --sub-format vtt URL
```

---

## Cómo funciona

1. **Descubrimiento.** La URL se parsea para obtener el ID del video y/o de la
   playlist.
2. **InnerTube.** Se consulta `youtubei/v1/player` con el cliente `VISIONOS`
   (visionOS) y, como respaldo, `ANDROID`, `IOS` y `ANDROID_VR`. El cliente
   principal devuelve URLs directas de los streams, sin exigir el descifrado de
   firmas (`signatureCipher`) ni el intérprete de JavaScript que usan otros
   clientes.

   `VISIONOS` necesita que la sesión tenga un `visitorData`: la primera vez se
   hace un `GET` a `https://www.youtube.com/`, se extrae ese identificador del
   HTML y se envía en la cabecera `X-Goog-Visitor-Id` junto con
   `X-Youtube-Client-Name` y `X-Youtube-Client-Version`. Sin `visitorData`,
   YouTube responde `LOGIN_REQUIRED` («Sign in to confirm you're not a bot»).
   Ese `GET` también crea las cookies de visitante que ligan la sesión a las
   URLs firmadas.
3. **Selección.** Se clasifican los formatos (progresivos, solo video, solo
   audio), se aplican filtros y se elige la mejor combinación.
4. **Descarga.** Cada pista se descarga por HTTPS a un archivo `.part`
   reanudable. Si la conexión se corta, se reintenta con `Range` desde el
   último byte.
5. **Procesado.** ffmpeg une video+audio, remuxa contenedores o extrae y
   convierte el audio. Los archivos temporales se eliminan al terminar.
6. **Subtítulos.** Se descarga el `timedtext` de YouTube y se convierte de
   XML/JSON3/VTT a SRT o VTT.

### Estructura del proyecto

```text
.
├── index.js           API pública del paquete npm
├── index.d.ts         Tipos TypeScript del paquete npm
├── package.json       Metadatos del paquete npm
├── bin/
│   └── ytpremiun-vip.js  CLI nativo de Node.js (sin Python)
├── api/               API HTTP para VPS
│   ├── README.md        Endpoints y despliegue
│   ├── install.sh       Instalación en Ubuntu
│   ├── server.js        Servidor nativo (sin dependencias)
│   └── ytpremiun-api.service
├── lib/               Motor nativo de Node.js (sin Python)
│   ├── api.js           API de alto nivel
│   ├── cli.js           Argumentos, opciones y resumen final
│   ├── downloader.js    Cola, orquestación, archivo de historial
│   ├── errors.js        Excepciones propias
│   ├── formats.js       Selector de formatos y tabla -F
│   ├── http.js          Reintentos, cookies, descargas reanudables
│   ├── innertube.js     Cliente VISIONOS (+ respaldos) y parseo
│   ├── media.js         Integración con ffmpeg
│   ├── playlist.js      Lectura y paginación de playlists
│   ├── progress.js      Barra de progreso
│   ├── subtitles.js     Parseo y conversión de subtítulos
│   ├── urls.js          Parseo de URLs de YouTube
│   └── utils.js         Plantillas, saneado y utilidades
├── pyproject.toml     Metadatos del paquete pip
├── requirements.txt   Dependencias de Python (solo pip)
├── LICENSE            Licencia MIT
├── README.md          Documentación
├── examples/          Ejemplos (Baileys, whatsapp-web.js)
├── test/              Tests del paquete npm
├── tests/             Tests del paquete Python
└── ytpremiun_vip/     Implementación del paquete pip (Python)
    ├── __init__.py      Versión y API pública
    ├── __main__.py      Punto de entrada (python -m ytpremiun_vip)
    ├── api.py           API de librería para bots (descargar_audio, etc.)
    ├── cli.py           Argumentos, opciones y resumen final
    ├── downloader.py    Cola, orquestación, archivo de historial
    ├── errors.py        Excepciones propias
    ├── formats.py       Selector de formatos y tabla -F
    ├── http.py          Reintentos, cookies, descargas reanudables
    ├── innertube.py     Cliente VISIONOS (+ respaldos) y parseo de respuestas
    ├── media.py         Integración con ffmpeg
    ├── playlist.py      Lectura y paginación de playlists
    ├── progress.py      Barra de progreso
    ├── subtitles.py     Parseo y conversión de subtítulos
    ├── urls.py          Parseo de URLs de YouTube
    └── utils.py         Plantillas, saneado y utilidades
```

---

## Tests

El proyecto incluye tests unitarios que no necesitan red.

Paquete npm (Node.js, sin Python):

```bash
npm test
```

Cubren la API pública, `_buildArgs`, parseo de URLs y argumentos, selección de
formatos, plantillas de nombres, subtítulos y el verificador.

Paquete Python:

```bash
python -m unittest discover -s tests -v
```

Cubren parseo de URLs, plantillas, selección de formatos, playlists,
subtítulos, cliente HTTP, comandos de ffmpeg, flujo de descarga, API de
librería y CLI. Hay un test de integración con ffmpeg que se omite
automáticamente si no está instalado.

---

## Limitaciones

- **Directos en vivo:** no se descargan. Espera a que el directo termine.
- **Contenido privado, con DRM o que exige pago:** no es accesible.
- **Restricción por edad o verificación de bot:** puede requerir cookies de una
  sesión iniciada (`--cookies cookies.txt`). Si `VISIONOS` responde
  `LOGIN_REQUIRED`, el programa agota los clientes de respaldo y sugiere usar
  cookies.
- **Videos que solo ofrecen SABR:** algunos clientes web ya no entregan URLs
  directas. `VISIONOS` suele evitarlo, pero YouTube cambia sus APIs con
  frecuencia; si un video falla, prueba a actualizar los `clientVersion` de
  `lib/innertube.js` (npm) o `ytpremiun_vip/innertube.py` (pip).
- **Clientes móviles antiguos:** `ANDROID`, `IOS` y `ANDROID_VR` pueden entregar
  enlaces que solo sirven el primer MiB y luego responden `HTTP 403`. Por eso
  son solo respaldo: el cliente principal es `VISIONOS`, que sirve el archivo
  completo en bloques `Range` de 1 MiB.
- **Firmas cifradas:** el código no descifra `signatureCipher` con el player JS.
  Solo acepta respuestas con URL directa (las de los clientes móviles).
- **Playlists muy grandes:** se sigue el token de continuación hasta 100
  páginas. Si una lista supera ese límite, usa `--playlist-items` o divide la
  descarga.
- **Subtítulos:** dependen de que el video los tenga disponibles; los
  automáticos pueden tener peor calidad.
- **Unión de pistas:** FFmpeg se instala como dependencia opcional en npm
  (`ffmpeg-static`) y con `imageio-ffmpeg` en pip. Si aun así falta, no se
  pueden unir video+audio ni convertir audio (los formatos progresivos y las
  pistas M4A directas sí funcionan).

## Problemas frecuentes

| Problema | Solución |
| --- | --- |
| `ffmpeg no está instalado o no se encuentra en el PATH` | En npm ejecuta `npm install ffmpeg-static`; en pip reinstala con `pip install -e .` (incluye `imageio-ffmpeg`). También puedes definir `FFMPEG`. |
| `HTTP 403` al descargar | La URL caducó o el cliente quedó bloqueado. Vuelve a ejecutar el comando; si persiste, actualiza los `clientVersion` de `lib/innertube.js` o `innertube.py`, o usa `--cookies cookies.txt`. |
| `YouTube pidió iniciar sesión (o detectó un bot)` | Exporta cookies del navegador y usa `--cookies cookies.txt`. |
| `No se encontró un formato que coincida` | Ejecuta `-F` y elige un itag válido. |
| El video se guarda como `.mkv` | El contenedor MP4 no admitía los códecs; usa `--merge-output-format mkv` para evitar el aviso. |
| La descarga se corta | Se reanuda automáticamente; puedes relanzar el comando y continuará desde `.part`. |

---

## Contribuir

Las contribuciones son bienvenidas. Antes de enviar cambios:

1. Abre una *issue* para cambios grandes y acuerda el enfoque.
2. Ejecuta los tests: `npm test` y `python -m unittest discover -s tests -v`.
3. Añade tests para el comportamiento nuevo o corregido.
4. Mantén el código y la documentación en español.

Lee [`CONTRIBUTING.md`](CONTRIBUTING.md) para el entorno de desarrollo, el
estilo y las normas. Para problemas de seguridad, sigue [`SECURITY.md`](SECURITY.md)
en lugar de abrir una *issue* pública.

---

## Autoría y créditos

Creado y mantenido por **natsu-dev01**.

- Repositorio: <https://github.com/natsu-dev01/ytpremiun_vip>
- Autor: [@natsu-dev01](https://github.com/natsu-dev01)

El motor se inspira en el funcionamiento público de la API InnerTube de
YouTube. El ajuste del cliente `VISIONOS` y `visitorData` toma como referencia
la PR pública [#17461 de yt-dlp](https://github.com/yt-dlp/yt-dlp/pull/17461),
pero **este proyecto no usa yt-dlp** ni incluye su código.

---

## Licencia y responsabilidad

Distribuido bajo la licencia **MIT**. Consulta [`LICENSE`](LICENSE).

Copyright © 2026 natsu-dev01.

Este proyecto es una herramienta educativa para practicar el consumo de APIs y
el procesado multimedia. No está afiliado a YouTube ni a Google. El usuario es
el único responsable del uso que haga del programa y del contenido que
descargue.

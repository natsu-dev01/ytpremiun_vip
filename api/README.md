# API de ytpremiun-vip

Servidor HTTP nativo (sin dependencias) para descargar video, audio y playlists
de YouTube desde cualquier lenguaje o bot. Usa el mismo motor que el paquete
npm: **no necesita Python**.

Pensada para VPS pequeños: cola con concurrencia limitada, limpieza automática,
API key y descarga de archivos con soporte de `Range`.

## Instalación rápida (Ubuntu 22.04/24.04)

```bash
apt-get update && apt-get install -y git
git clone https://github.com/natsu-dev01/ytpremiun_vip.git /opt/ytpremiun
bash /opt/ytpremiun/api/install.sh
```

El script:

1. Instala `ffmpeg`, `git` y Node.js 22 si hace falta.
2. Crea el usuario `ytpremiun` y `/var/lib/ytpremiun`.
3. Genera `/etc/ytpremiun-api.env` con una **API key aleatoria** (se muestra
   una sola vez).
4. Registra y arranca el servicio `ytpremiun-api` con systemd.
5. Abre el puerto en `ufw` si está activo.

Comandos útiles:

```bash
systemctl status ytpremiun-api
journalctl -u ytpremiun-api -f
cat /etc/ytpremiun-api.env      # ver la API key
```

## Configuración

Archivo `/etc/ytpremiun-api.env`:

| Variable | Por defecto | Descripción |
| --- | --- | --- |
| `PORT` | `3000` | Puerto HTTP |
| `HOST` | `0.0.0.0` | Interfaz de escucha |
| `API_KEY` | obligatoria | Clave, o varias separadas por comas |
| `DATA_DIR` | `/var/lib/ytpremiun` | Carpeta de trabajos y archivos |
| `MAX_CONCURRENT` | `1` | Descargas simultáneas (1 vCPU: dejar en 1) |
| `MAX_QUEUE` | `20` | Trabajos en cola antes de devolver 429 |
| `JOB_TTL_HOURS` | `12` | Horas antes de borrar un trabajo terminado |
| `MAX_STORAGE_GB` | `12` | Cuota de disco para archivos |
| `DEFAULT_CONNECTIONS` | `6` | Conexiones paralelas por descarga |
| `CORS_ORIGIN` | `*` | Origen permitido para navegadores |

Después de editar: `systemctl restart ytpremiun-api`.

## Autenticación

Todas las rutas salvo `/health` requieren una de estas cabeceras:

```http
X-API-Key: TU_CLAVE
Authorization: Bearer TU_CLAVE
```

## Endpoints

### `GET /health`

Público. Estado del servicio, versión, ffmpeg, cola y trabajos.

```bash
curl http://IP:3000/health
```

### `GET /info?url=...`

Metadatos y formatos del video.

```bash
curl -H "X-API-Key: TU_CLAVE" \
  "http://IP:3000/info?url=https://youtu.be/VIDEO"
```

### `GET /formats?url=...`

Formatos en JSON (`formatos`) y tabla de texto (`tabla`).

```bash
curl -H "X-API-Key: TU_CLAVE" \
  "http://IP:3000/formats?url=https://youtu.be/VIDEO"
```

### `POST /download`

Encola una descarga y responde `202` con el `id`.

```bash
curl -X POST http://IP:3000/download \
  -H "X-API-Key: TU_CLAVE" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEO","modo":"video"}'
```

Respuesta:

```json
{
  "ok": true,
  "id": "3f2a9c1b7e4d5a60",
  "estado": "en_cola",
  "consulta": "/jobs/3f2a9c1b7e4d5a60"
}
```

Campos del cuerpo:

| Campo | Tipo | Por defecto | Descripción |
| --- | --- | --- | --- |
| `url` | string | — | URL de video o playlist |
| `modo` | `video` \| `audio` | `video` | Tipo de descarga |
| `formato` | string | automático | `137+140`, `bv*+ba/b`, `18`... |
| `formatoAudio` | string | `mp3` | `mp3`, `m4a`, `opus`, `best`, `aac`, `flac`, `wav` |
| `calidadAudio` | string | `192K` | `128K`, `192K`, `320K`... |
| `contenedor` | string | `mp4` | `mp4`, `mkv`, `webm` |
| `playlist` | boolean | `false` | Descargar la playlist completa |
| `elementosPlaylist` | string | — | `1-5,8` (requiere `playlist: true`) |
| `maxDescargas` | number | — | Límite de elementos de playlist |
| `conexiones` | number | `6` | 1-16 conexiones paralelas |
| `reintentos` | number | `5` | 0-20 |
| `timeout` | number | `20` | Segundos por petición (5-120) |
| `subtitulos` | boolean | `false` | Descargar subtítulos |
| `subtitulosAuto` | boolean | `false` | Incluir subtítulos automáticos |
| `idiomasSubtitulos` | string | — | `es,en` |
| `formatoSubtitulos` | string | `srt` | `srt`, `vtt`, `json3` |
| `nombresAscii` | boolean | `false` | Nombres de archivo sin acentos |

Ejemplos:

```bash
# Audio MP3
curl -X POST http://IP:3000/download \
  -H "X-API-Key: TU_CLAVE" -H "Content-Type: application/json" \
  -d '{"url":"https://youtu.be/VIDEO","modo":"audio","formatoAudio":"mp3"}'

# Playlist, primeros 5 elementos
curl -X POST http://IP:3000/download \
  -H "X-API-Key: TU_CLAVE" -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/playlist?list=PL...","playlist":true,"elementosPlaylist":"1-5"}'
```

### `GET /jobs`

Lista resumida de trabajos. Filtro opcional: `?estado=completado`.

### `GET /jobs/:id`

Estado detallado y progreso:

```json
{
  "ok": true,
  "id": "3f2a9c1b7e4d5a60",
  "estado": "descargando",
  "progreso": {
    "fuente": "video 1080p60",
    "bytes": 52428800,
    "total": 257949696,
    "porcentaje": 20.3
  },
  "descargas": [],
  "lista_archivos": []
}
```

Estados: `en_cola`, `descargando`, `completado`, `fallido`, `cancelado`.

Al terminar, `descargas` incluye un objeto por video con `titulo`, `autor`,
`duracion`, `archivo` y `archivos`, y `lista_archivos` contiene todos los
archivos generados (video, audio y subtítulos).

### `GET /files/:id/:index`

Descarga el archivo. Soporta `Range` para reanudar:

```bash
curl -H "X-API-Key: TU_CLAVE" -OJ \
  "http://IP:3000/files/3f2a9c1b7e4d5a60/0"
```

### `DELETE /jobs/:id`

- En cola: lo cancela inmediatamente.
- Descargando: solicita la cancelación; al terminar se borran sus archivos.
- Terminado: elimina el trabajo y sus archivos.

## Seguridad y límites

- Cambia la API key si se filtra: edita `/etc/ytpremiun-api.env` y reinicia.
- El VPS de 1 vCPU/1 GB debería mantener `MAX_CONCURRENT=1`.
- Los archivos se borran a las `JOB_TTL_HOURS` horas o al superar
  `MAX_STORAGE_GB`.
- Si el proveedor tiene firewall externo, abre también el puerto allí.
- Para HTTPS, pon Caddy o Nginx delante y apunta a `127.0.0.1:3000`.

Ejemplo mínimo con Caddy (necesita un dominio):

```caddyfile
api.tudominio.com {
    reverse_proxy 127.0.0.1:3000
}
```

## Ejecución manual (desarrollo)

```bash
API_KEY=prueba DATA_DIR=./downloads-api PORT=3000 node api/server.js
curl http://127.0.0.1:3000/health
```

export type Estado = "ok" | "omitido" | "fallido";

export interface Opciones {
  /** Carpeta de salida. Por defecto `downloads`. */
  carpeta?: string;
  /** Selector de formato de video, por ejemplo `bv*[height<=720]+ba`. */
  formato?: string;
  /** Descarga solo audio cuando se usa `descargar()`. */
  soloAudio?: boolean;
  /** Formato de audio: mp3, m4a, opus, wav o flac. */
  formatoAudio?: string;
  /** Alias de `formatoAudio`. */
  audioFormat?: string;
  /** Calidad de audio, por ejemplo `192K`. */
  calidadAudio?: string;
  /** Alias de `calidadAudio`. */
  audioQuality?: string;
  /** Contenedor de salida para video: mp4, mkv o webm. */
  contenedor?: string;
  /** Descarga los subtítulos disponibles. */
  subtitulos?: boolean;
  /** Idiomas de subtítulos, por ejemplo `es,en` o `all`. */
  idiomasSubtitulos?: string;
  /** Formato de subtítulos: srt, vtt o xml. */
  formatoSubtitulos?: string;
  /** Incluye también los subtítulos automáticos. */
  subtitulosAuto?: boolean;
  /** Descarga la playlist completa si la URL tiene `list=`. */
  playlist?: boolean;
  /** Elementos de la playlist, por ejemplo `1-5,8`. */
  elementosPlaylist?: string;
  /** Máximo de elementos de una playlist. */
  maxDescargas?: number;
  /** Archivo de historial para no repetir descargas. */
  historial?: string;
  /** Nombres de archivo solo con caracteres ASCII. */
  nombresAscii?: boolean;
  /** Sobrescribe archivos existentes. */
  sobrescribir?: boolean;
  /** Conserva los archivos temporales. */
  conservarTemporales?: boolean;
  /** Reintentos por descarga. */
  reintentos?: number;
  /** Timeout de red en segundos. */
  timeout?: number;
  /** Proxy HTTP/SOCKS. */
  proxy?: string;
  /** Archivo de cookies en formato Netscape. */
  cookies?: string;
}

export interface Resultado {
  ok: boolean;
  estado: Estado;
  id: string;
  url: string;
  titulo: string;
  autor: string;
  duracion: number;
  archivo: string | null;
  archivos: string[];
  error: string | null;
  playlist_id: string | null;
  playlist_titulo: string | null;
  playlist_indice: number | null;
}

export interface InfoVideo {
  id: string;
  title: string;
  author: string;
  channel_id: string;
  length_seconds: number;
  view_count: number;
  description: string;
  keywords: string[];
  thumbnails: unknown[];
  upload_date: string;
  is_live: boolean;
  default_audio_language: string | null;
  formats: unknown[];
  subtitles: unknown[];
  source_client: string;
  webpage_url: string;
  [campo: string]: unknown;
}

export interface Verificacion {
  ok: boolean;
  python: string;
  requests?: string;
  version?: string;
  ffmpeg: string | null;
  error?: string;
}

export class YtPremiunError extends Error {
  codigo: string | number | null;
  stderr: string;
  resultados: Resultado[];
}

export function descargar(
  urls: string | string[],
  opciones?: Opciones,
): Promise<Resultado[]>;

export function descargarVideo(
  url: string,
  opciones?: Opciones,
): Promise<Resultado>;

export function descargarAudio(
  url: string,
  opciones?: Opciones,
): Promise<Resultado>;

export function descargarPlaylist(
  url: string,
  opciones?: Opciones,
): Promise<Resultado[]>;

export function obtenerInfo(
  url: string,
  opciones?: Opciones,
): Promise<InfoVideo>;

export function listarFormatos(
  url: string,
  opciones?: Opciones,
): Promise<string>;

export function verificar(): Promise<Verificacion>;

export function _buildArgs(
  urls: string | string[],
  opciones?: Opciones,
  modo?: "generic" | "video" | "audio" | "playlist",
): string[];

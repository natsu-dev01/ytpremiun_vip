/**
 * API HTTP de ytpremiun-vip.
 *
 * Servidor nativo de Node.js (sin dependencias) pensado para un VPS pequeño:
 * - Cola de trabajos con concurrencia limitada.
 * - Descargas en segundo plano y consulta de estado.
 * - Entrega de archivos con soporte de Range (reanudable).
 * - Autenticación por API key.
 * - Limpieza automática por antigüedad y por cuota de disco.
 *
 * Uso:
 *   API_KEY=... DATA_DIR=/var/lib/ytpremiun node api/server.js
 */

"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const { URL } = require("node:url");

const yt = require("../index.js");
const { formatTable } = require("../lib/formats");
const { formatKind, formatResolution } = require("../lib/innertube");

// --------------------------------------------------------------- configuración

function envInt(name, fallback, min, max) {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

const PORT = envInt("PORT", 3000, 1, 65535);
const HOST = process.env.HOST || "0.0.0.0";
const API_KEYS = String(process.env.API_KEY || "")
  .split(",")
  .map((key) => key.trim())
  .filter(Boolean);
const DATA_DIR = path.resolve(
  process.env.DATA_DIR || path.join(__dirname, "..", "downloads-api"),
);
const JOBS_DIR = path.join(DATA_DIR, "jobs");
const MAX_CONCURRENT = envInt("MAX_CONCURRENT", 1, 1, 8);
const MAX_QUEUE = envInt("MAX_QUEUE", 20, 1, 500);
const JOB_TTL_MS = envInt("JOB_TTL_HOURS", 12, 1, 168) * 60 * 60 * 1000;
const MAX_STORAGE_BYTES = envInt("MAX_STORAGE_GB", 12, 1, 1024) * 1024 ** 3;
const DEFAULT_CONNECTIONS = envInt("DEFAULT_CONNECTIONS", 6, 1, 16);
const MAX_BODY_BYTES = 1024 * 1024;

const MIME = {
  ".mp4": "video/mp4",
  ".m4v": "video/mp4",
  ".mkv": "video/x-matroska",
  ".webm": "video/webm",
  ".mov": "video/quicktime",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
  ".aac": "audio/aac",
  ".opus": "audio/ogg",
  ".ogg": "audio/ogg",
  ".flac": "audio/flac",
  ".wav": "audio/wav",
  ".srt": "application/x-subrip; charset=utf-8",
  ".vtt": "text/vtt; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
};

if (API_KEYS.length === 0) {
  console.error("[ytpremiun-api] Falta la variable API_KEY. No se inicia sin autenticación.");
  process.exit(1);
}

// -------------------------------------------------------------------- estado

const jobs = new Map();
const queue = [];
let active = 0;
let ffmpegPath = null;
let startedAt = new Date().toISOString();

// ------------------------------------------------------------------ utilidades

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function nowIso() {
  return new Date().toISOString();
}

function badRequest(message, status = 400) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function parseJson(value, field, maxLength = 200) {
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") throw badRequest(`'${field}' debe ser texto.`);
  const clean = value.trim();
  if (!clean) return null;
  if (clean.length > maxLength) {
    throw badRequest(`'${field}' es demasiado largo (máximo ${maxLength}).`);
  }
  return clean;
}

function parseBool(value, fallback = false) {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "boolean") return value;
  if (value === "true" || value === "1" || value === 1) return true;
  if (value === "false" || value === "0" || value === 0) return false;
  throw badRequest("Se esperaba un valor booleano.");
}

function parseChoice(value, choices, field, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const clean = String(value).trim().toLowerCase();
  if (!choices.includes(clean)) {
    throw badRequest(`'${field}' debe ser uno de: ${choices.join(", ")}.`);
  }
  return clean;
}

function parseInteger(value, field, fallback, min, max) {
  if (value === undefined || value === null || value === "") return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < min || number > max) {
    throw badRequest(`'${field}' debe ser un entero entre ${min} y ${max}.`);
  }
  return number;
}

function safeEqual(a, b) {
  const left = Buffer.from(String(a));
  const right = Buffer.from(String(b));
  if (left.length !== right.length) return false;
  return crypto.timingSafeEqual(left, right);
}

function authorized(req) {
  const header = req.headers["x-api-key"];
  const bearer = req.headers.authorization;
  let provided = typeof header === "string" ? header : "";
  if (!provided && typeof bearer === "string" && bearer.startsWith("Bearer ")) {
    provided = bearer.slice(7).trim();
  }
  if (!provided) return false;
  return API_KEYS.some((key) => safeEqual(provided, key));
}

function contentDisposition(filename) {
  const ascii = filename.replace(/[^\x20-\x7E]/g, "_").replace(/["\\]/g, "_");
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(filename)}`;
}

async function dirSize(directory) {
  let total = 0;
  let entries;
  try {
    entries = await fsp.readdir(directory, { withFileTypes: true });
  } catch {
    return 0;
  }
  for (const entry of entries) {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      total += await dirSize(full);
    } else if (entry.isFile()) {
      try {
        total += (await fsp.stat(full)).size;
      } catch {
        // Archivo eliminado mientras se recorría.
      }
    }
  }
  return total;
}

function publicFormat(format) {
  const size = format.filesize || format.filesize_approx || null;
  return {
    itag: format.itag,
    tipo: formatKind(format),
    ext: format.ext || null,
    resolucion: format.has_video ? formatResolution(format) : null,
    fps: format.fps || null,
    vcodec: format.vcodec && format.vcodec !== "none" ? format.vcodec : null,
    acodec: format.acodec && format.acodec !== "none" ? format.acodec : null,
    tamano: size,
    nota: format.format_note || null,
  };
}

function publicInfo(info) {
  return {
    ok: true,
    id: info.id,
    url: info.webpage_url,
    titulo: info.title,
    autor: info.author,
    canal_id: info.channel_id,
    duracion: info.length_seconds,
    vistas: info.view_count,
    fecha: info.upload_date,
    en_directo: Boolean(info.is_live),
    idioma_audio: info.default_audio_language || null,
    miniaturas: info.thumbnails,
    formatos: info.formats.map(publicFormat),
  };
}

// ------------------------------------------------------------------ trabajos

function newJobId() {
  return crypto.randomBytes(8).toString("hex");
}

function jobDir(job) {
  return path.join(JOBS_DIR, job.id);
}

function serializeJob(job) {
  return {
    id: job.id,
    estado: job.estado,
    creado: job.creado,
    iniciado: job.iniciado,
    terminado: job.terminado,
    peticion: job.peticion,
    progreso: job.progreso,
    error: job.error,
    descargas: job.descargas,
    archivos: job.archivos,
  };
}

async function persist(job) {
  await fsp.mkdir(JOBS_DIR, { recursive: true });
  const file = path.join(JOBS_DIR, `${job.id}.json`);
  const tmp = `${file}.tmp`;
  await fsp.writeFile(tmp, JSON.stringify(serializeJob(job), null, 2), "utf8");
  await fsp.rename(tmp, file);
}

function persistSoon(job) {
  if (job._persistTimer) return;
  job._persistTimer = setTimeout(() => {
    job._persistTimer = null;
    persist(job).catch((error) => {
      console.error(`[ytpremiun-api] No se pudo guardar ${job.id}: ${error.message}`);
    });
  }, 1500);
  if (typeof job._persistTimer.unref === "function") job._persistTimer.unref();
}

async function persistNow(job) {
  if (job._persistTimer) {
    clearTimeout(job._persistTimer);
    job._persistTimer = null;
  }
  await persist(job);
}

function publicJob(job, detalle = true) {
  const base = {
    id: job.id,
    estado: job.estado,
    creado: job.creado,
    iniciado: job.iniciado,
    terminado: job.terminado,
    progreso: job.progreso,
    error: job.error,
    total: job.descargas.length,
    completados: job.descargas.filter((item) => item.ok).length,
    archivos: job.archivos.length,
    peticion: job.peticion,
  };
  if (!detalle) return base;

  base.descargas = job.descargas.map((download) => {
    const indices = Array.isArray(download.archivos) ? download.archivos : [];
    return {
      ok: download.ok,
      estado: download.estado,
      id: download.id,
      url: download.url,
      titulo: download.titulo,
      autor: download.autor,
      duracion: download.duracion,
      error: download.error ?? null,
      playlist_id: download.playlist_id ?? null,
      playlist_titulo: download.playlist_titulo ?? null,
      playlist_indice: download.playlist_indice ?? null,
      archivo: indices.length > 0 ? `/files/${job.id}/${indices[0]}` : null,
      archivos: indices.map((index) => ({
        nombre: job.archivos[index].nombre,
        tamano: job.archivos[index].tamano,
        url: `/files/${job.id}/${index}`,
      })),
    };
  });
  base.lista_archivos = job.archivos.map((file, index) => ({
    nombre: file.nombre,
    tamano: file.tamano,
    url: `/files/${job.id}/${index}`,
  }));
  return base;
}

function validateDownload(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw badRequest("El cuerpo debe ser un objeto JSON.");
  }
  const url = parseJson(body.url, "url", 2048);
  if (!url) throw badRequest("Falta 'url'.");
  if (!/^https?:\/\//i.test(url)) {
    throw badRequest("'url' debe empezar por http:// o https://.");
  }

  const modo = parseChoice(body.modo, ["video", "audio"], "modo", "video");
  const playlist = parseBool(body.playlist, false);
  const conexiones = parseInteger(
    body.conexiones,
    "conexiones",
    DEFAULT_CONNECTIONS,
    1,
    16,
  );
  const reintentos = parseInteger(body.reintentos, "reintentos", 5, 0, 20);
  const timeout = parseInteger(body.timeout, "timeout", 20, 5, 120);
  const maxDescargas = parseInteger(
    body.maxDescargas,
    "maxDescargas",
    null,
    1,
    500,
  );

  let formato = parseJson(body.formato, "formato", 200);
  if (modo === "audio") formato = null;

  const formatoAudio = parseChoice(
    body.formatoAudio,
    ["mp3", "m4a", "opus", "best", "aac", "flac", "wav"],
    "formatoAudio",
    "mp3",
  );

  let calidadAudio = parseJson(body.calidadAudio, "calidadAudio", 8) || "192K";
  if (!/^\d{1,3}[Kk]?$/.test(calidadAudio)) {
    throw badRequest("'calidadAudio' debe tener el formato 128K, 192K, 320K...");
  }
  if (!/[Kk]$/.test(calidadAudio)) calidadAudio += "K";

  const contenedor = parseChoice(
    body.contenedor,
    ["mp4", "mkv", "webm"],
    "contenedor",
    "mp4",
  );

  const subtitulos = parseBool(body.subtitulos, false);
  const subtitulosAuto = parseBool(body.subtitulosAuto, false);
  const idiomasSubtitulos = parseJson(
    body.idiomasSubtitulos,
    "idiomasSubtitulos",
    100,
  );
  if (idiomasSubtitulos && !/^[a-zA-Z0-9,._\- ]+$/.test(idiomasSubtitulos)) {
    throw badRequest("'idiomasSubtitulos' solo admite códigos separados por comas.");
  }
  const formatoSubtitulos = parseChoice(
    body.formatoSubtitulos,
    ["srt", "vtt", "json3"],
    "formatoSubtitulos",
    "srt",
  );
  const nombresAscii = parseBool(body.nombresAscii, false);

  let elementosPlaylist = parseJson(
    body.elementosPlaylist,
    "elementosPlaylist",
    100,
  );
  if (elementosPlaylist) {
    if (!playlist) {
      throw badRequest("'elementosPlaylist' requiere 'playlist: true'.");
    }
    if (!/^[0-9,\-: ]+$/.test(elementosPlaylist)) {
      throw badRequest("'elementosPlaylist' debe ser algo como \"1-5,8\".");
    }
  }

  return {
    url,
    modo,
    playlist,
    elementosPlaylist,
    maxDescargas,
    formato,
    formatoAudio,
    calidadAudio,
    contenedor,
    subtitulos,
    subtitulosAuto,
    idiomasSubtitulos,
    formatoSubtitulos,
    nombresAscii,
    conexiones,
    reintentos,
    timeout,
  };
}

function buildOptions(request, job) {
  return {
    carpeta: jobDir(job),
    plantilla: "%(title)s [%(id)s].%(ext)s",
    playlist: request.playlist,
    elementosPlaylist: request.elementosPlaylist,
    maxDescargas: request.maxDescargas,
    soloAudio: request.modo === "audio",
    formato: request.formato,
    formatoAudio: request.formatoAudio,
    calidadAudio: request.calidadAudio,
    contenedor: request.contenedor,
    subtitulos: request.subtitulos,
    subtitulosAuto: request.subtitulosAuto,
    idiomasSubtitulos: request.idiomasSubtitulos,
    formatoSubtitulos: request.formatoSubtitulos,
    nombresAscii: request.nombresAscii,
    conexiones: request.conexiones,
    reintentos: request.reintentos,
    timeout: request.timeout,
    progreso: false,
    silencioso: true,
    onProgress: (event) => {
      const total = Number(event.total) || null;
      const bytes = Number(event.done) || 0;
      job.progreso = {
        fuente: event.label || "descarga",
        bytes,
        total,
        porcentaje: total
          ? Math.min(100, Math.round((bytes / total) * 1000) / 10)
          : null,
      };
      persistSoon(job);
    },
  };
}

async function registerFiles(job, results) {
  job.archivos = [];
  job.descargas = [];

  for (const result of results) {
    const rutas = Array.isArray(result.archivos) && result.archivos.length > 0
      ? result.archivos
      : result.archivo
        ? [result.archivo]
        : [];

    const indices = [];
    for (const ruta of rutas) {
      const absolute = path.resolve(String(ruta));
      let size = null;
      try {
        size = (await fsp.stat(absolute)).size;
      } catch {
        continue;
      }
      const index = job.archivos.length;
      job.archivos.push({
        ruta: absolute,
        nombre: path.basename(absolute),
        tamano: size,
      });
      indices.push(index);
    }

    job.descargas.push({
      ok: result.ok,
      estado: result.estado,
      id: result.id,
      url: result.url,
      titulo: result.titulo,
      autor: result.autor,
      duracion: result.duracion,
      error: result.error ?? null,
      playlist_id: result.playlist_id ?? null,
      playlist_titulo: result.playlist_titulo ?? null,
      playlist_indice: result.playlist_indice ?? null,
      archivos: indices,
    });
  }
}

async function runJob(job) {
  const request = job.peticion;
  job.estado = "descargando";
  job.iniciado = nowIso();
  job.progreso = {
    fuente: "iniciando",
    bytes: 0,
    total: null,
    porcentaje: null,
  };
  await persistNow(job);

  try {
    await fsp.mkdir(jobDir(job), { recursive: true });
    const results = await yt.descargar(request.url, buildOptions(request, job));
    await registerFiles(job, results);

    const conArchivo = job.descargas.filter((item) => item.archivos.length > 0);
    const fallidos = job.descargas.filter((item) => !item.ok);

    if (conArchivo.length === 0) {
      job.estado = "fallido";
      job.error =
        fallidos.find((item) => item.error)?.error ||
        "No se descargó ningún archivo.";
    } else {
      job.estado = "completado";
      job.error =
        fallidos.length > 0
          ? `${fallidos.length} de ${job.descargas.length} elemento(s) fallaron.`
          : null;
    }

    const bytes = job.archivos.reduce((sum, file) => sum + (file.tamano || 0), 0);
    job.progreso = {
      fuente: "finalizado",
      bytes,
      total: bytes,
      porcentaje: 100,
    };
  } catch (error) {
    job.estado = "fallido";
    job.error = String(error?.message || error);
    console.error(`[ytpremiun-api] ${job.id}: ${job.error}`);
  } finally {
    if (job._cancelado) {
      job.estado = "cancelado";
      job.error = "Cancelado por el usuario.";
      await fsp.rm(jobDir(job), { recursive: true, force: true }).catch(() => {});
      job.archivos = [];
      job.descargas = [];
      job.progreso = null;
    }
    job.terminado = nowIso();
    await persistNow(job).catch((error) => {
      console.error(`[ytpremiun-api] No se pudo guardar ${job.id}: ${error.message}`);
    });
  }
}

function pump() {
  while (active < MAX_CONCURRENT && queue.length > 0) {
    const id = queue.shift();
    const job = jobs.get(id);
    if (!job || job.estado !== "en_cola") continue;
    active += 1;
    runJob(job)
      .catch((error) => {
        console.error(`[ytpremiun-api] Error inesperado en ${id}: ${error.stack || error}`);
      })
      .finally(() => {
        active -= 1;
        pump();
      });
  }
}

async function enqueue(request) {
  if (queue.length >= MAX_QUEUE) {
    throw badRequest("La cola está llena; inténtalo más tarde.", 429);
  }
  const job = {
    id: newJobId(),
    estado: "en_cola",
    creado: nowIso(),
    iniciado: null,
    terminado: null,
    peticion: request,
    progreso: null,
    error: null,
    descargas: [],
    archivos: [],
  };
  jobs.set(job.id, job);
  queue.push(job.id);
  await persistNow(job);
  pump();
  return job;
}

async function removeJob(job) {
  if (job._persistTimer) {
    clearTimeout(job._persistTimer);
    job._persistTimer = null;
  }
  jobs.delete(job.id);
  await fsp.rm(jobDir(job), { recursive: true, force: true }).catch(() => {});
  await fsp.unlink(path.join(JOBS_DIR, `${job.id}.json`)).catch(() => {});
}

async function loadJobs() {
  await fsp.mkdir(JOBS_DIR, { recursive: true });
  let names;
  try {
    names = await fsp.readdir(JOBS_DIR);
  } catch {
    return;
  }

  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    const file = path.join(JOBS_DIR, name);
    try {
      const stored = JSON.parse(await fsp.readFile(file, "utf8"));
      if (!stored || typeof stored.id !== "string") continue;
      const job = {
        ...stored,
        _persistTimer: null,
        _cancelado: false,
      };
      if (job.estado === "en_cola" || job.estado === "descargando") {
        job.estado = "fallido";
        job.terminado = nowIso();
        job.error = "El servidor se reinició antes de terminar la descarga.";
        job.progreso = null;
        await persist(job);
      }
      jobs.set(job.id, job);
    } catch (error) {
      console.error(`[ytpremiun-api] Trabajo inválido ${name}: ${error.message}`);
    }
  }

  console.log(`[ytpremiun-api] ${jobs.size} trabajo(s) recuperados.`);
}

async function cleanup() {
  const now = Date.now();

  for (const job of [...jobs.values()]) {
    if (!["completado", "fallido", "cancelado"].includes(job.estado)) continue;
    const reference = Date.parse(job.terminado || job.creado);
    if (Number.isFinite(reference) && now - reference > JOB_TTL_MS) {
      await removeJob(job);
      console.log(`[ytpremiun-api] Trabajo ${job.id} eliminado por antigüedad.`);
    }
  }

  let total = 0;
  const finished = [];
  for (const job of jobs.values()) {
    const size = await dirSize(jobDir(job));
    total += size;
    if (["completado", "fallido", "cancelado"].includes(job.estado)) {
      finished.push({ job, size, reference: Date.parse(job.terminado || job.creado) || 0 });
    }
  }

  if (total > MAX_STORAGE_BYTES) {
    finished.sort((a, b) => a.reference - b.reference);
    for (const item of finished) {
      if (total <= MAX_STORAGE_BYTES) break;
      await removeJob(item.job);
      total -= item.size;
      console.log(
        `[ytpremiun-api] Trabajo ${item.job.id} eliminado por cuota de disco.`,
      );
    }
  }

  let entries = [];
  try {
    entries = await fsp.readdir(JOBS_DIR, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || jobs.has(entry.name)) continue;
    const full = path.join(JOBS_DIR, entry.name);
    try {
      const stat = await fsp.stat(full);
      if (now - stat.mtimeMs > JOB_TTL_MS) {
        await fsp.rm(full, { recursive: true, force: true });
      }
    } catch {
      // Directorio ya eliminado.
    }
  }
}

// ---------------------------------------------------------------------- HTTP

function sendJson(res, status, data, extraHeaders = {}) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    ...extraHeaders,
  });
  res.end(body);
}

function sendError(res, status, message, extraHeaders = {}) {
  sendJson(res, status, { ok: false, error: message }, extraHeaders);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let finished = false;

    const fail = (error) => {
      if (finished) return;
      finished = true;
      reject(error);
    };

    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        fail(badRequest("El cuerpo supera 1 MiB.", 413));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (finished) return;
      finished = true;
      if (chunks.length === 0) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(badRequest("El cuerpo no es JSON válido."));
      }
    });
    req.on("error", (error) => fail(error));
  });
}

async function handleInfo(res, url) {
  if (!url) throw badRequest("Falta el parámetro 'url'.");
  const info = await yt.obtenerInfo(url);
  sendJson(res, 200, publicInfo(info));
}

async function handleFormats(res, url) {
  if (!url) throw badRequest("Falta el parámetro 'url'.");
  const info = await yt.obtenerInfo(url);
  sendJson(res, 200, {
    ok: true,
    id: info.id,
    titulo: info.title,
    formatos: info.formats.map(publicFormat),
    tabla: formatTable(info.formats),
  });
}

async function handleDownload(req, res) {
  const body = await readJson(req);
  const request = validateDownload(body);
  const job = await enqueue(request);
  sendJson(
    res,
    202,
    {
      ok: true,
      id: job.id,
      estado: job.estado,
      consulta: `/jobs/${job.id}`,
    },
    { Location: `/jobs/${job.id}` },
  );
}

async function handleFile(req, res, job, index) {
  const file = job.archivos[index];
  if (!file) return sendError(res, 404, "Archivo no encontrado.");

  const filePath = path.resolve(file.ruta);
  const base = path.resolve(jobDir(job));
  if (filePath !== base && !filePath.startsWith(`${base}${path.sep}`)) {
    return sendError(res, 403, "Ruta no permitida.");
  }

  let stat;
  try {
    stat = await fsp.stat(filePath);
  } catch {
    return sendError(res, 404, "El archivo ya no está disponible.");
  }

  const total = stat.size;
  const extension = path.extname(filePath).toLowerCase();
  const headers = {
    "Content-Type": MIME[extension] || "application/octet-stream",
    "Accept-Ranges": "bytes",
    "Cache-Control": "private, max-age=3600",
    "Content-Disposition": contentDisposition(path.basename(filePath)),
    "X-Content-Type-Options": "nosniff",
  };

  let start = 0;
  let end = total - 1;
  let status = 200;

  const range = req.headers.range;
  if (typeof range === "string" && range.trim() !== "") {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (!match || (match[1] === "" && match[2] === "") || total === 0) {
      res.writeHead(416, { "Content-Range": `bytes */${total}` });
      return res.end();
    }
    if (match[1] === "") {
      const suffix = Number(match[2]);
      if (!Number.isFinite(suffix) || suffix <= 0) {
        res.writeHead(416, { "Content-Range": `bytes */${total}` });
        return res.end();
      }
      start = Math.max(0, total - suffix);
    } else {
      start = Number(match[1]);
      if (match[2] !== "") end = Math.min(Number(match[2]), total - 1);
    }
    if (!Number.isFinite(start) || start > end || start >= total) {
      res.writeHead(416, { "Content-Range": `bytes */${total}` });
      return res.end();
    }
    status = 206;
    headers["Content-Range"] = `bytes ${start}-${end}/${total}`;
  }

  headers["Content-Length"] = String(end - start + 1);
  res.writeHead(status, headers);
  if (req.method === "HEAD") return res.end();

  const stream = fs.createReadStream(filePath, { start, end });
  stream.on("error", () => {
    if (!res.headersSent) res.writeHead(500);
    res.destroy();
  });
  stream.pipe(res);
}

async function route(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const parts = url.pathname.split("/").filter(Boolean);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": process.env.CORS_ORIGIN || "*",
      "Access-Control-Allow-Methods": "GET, POST, DELETE, HEAD, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-API-Key, Authorization",
      "Access-Control-Max-Age": "86400",
    });
    return res.end();
  }

  if (parts.length === 0 && req.method === "GET") {
    return sendJson(res, 200, {
      ok: true,
      nombre: "ytpremiun-vip-api",
      version: yt.VERSION,
      endpoints: [
        "GET /health",
        "GET /info?url=...",
        "GET /formats?url=...",
        "POST /download",
        "GET /jobs",
        "GET /jobs/:id",
        "DELETE /jobs/:id",
        "GET /files/:id/:index",
      ],
    });
  }

  if (parts[0] === "health" && (req.method === "GET" || req.method === "HEAD")) {
    return sendJson(res, 200, {
      ok: true,
      version: yt.VERSION,
      node: process.version,
      ffmpeg: ffmpegPath,
      inicio: startedAt,
      uptime: Math.round(process.uptime()),
      cola: queue.length,
      activos: active,
      trabajos: jobs.size,
      limite_concurrente: MAX_CONCURRENT,
    });
  }

  if (!authorized(req)) {
    return sendError(res, 401, "API key ausente o incorrecta.");
  }

  if (parts[0] === "info" && req.method === "GET") {
    return handleInfo(res, url.searchParams.get("url"));
  }

  if (parts[0] === "formats" && req.method === "GET") {
    return handleFormats(res, url.searchParams.get("url"));
  }

  if (parts[0] === "download" && req.method === "POST") {
    return handleDownload(req, res);
  }

  if (parts[0] === "jobs" && parts.length === 1 && req.method === "GET") {
    const estado = url.searchParams.get("estado");
    const list = [...jobs.values()]
      .filter((job) => !estado || job.estado === estado)
      .sort((a, b) => Date.parse(b.creado) - Date.parse(a.creado))
      .map((job) => publicJob(job, false));
    return sendJson(res, 200, { ok: true, trabajos: list });
  }

  if (parts[0] === "jobs" && parts.length === 2) {
    const job = jobs.get(parts[1]);
    if (!job) return sendError(res, 404, "Trabajo no encontrado.");

    if (req.method === "GET") {
      return sendJson(res, 200, { ok: true, ...publicJob(job, true) });
    }

    if (req.method === "DELETE") {
      if (job.estado === "en_cola") {
        const position = queue.indexOf(job.id);
        if (position >= 0) queue.splice(position, 1);
        job.estado = "cancelado";
        job.error = "Cancelado por el usuario.";
        job.terminado = nowIso();
        await persistNow(job);
        return sendJson(res, 200, { ok: true, id: job.id, estado: job.estado });
      }
      if (job.estado === "descargando") {
        job._cancelado = true;
        await persistNow(job);
        return sendJson(res, 202, {
          ok: true,
          id: job.id,
          estado: job.estado,
          mensaje:
            "Cancelación solicitada; la descarga en curso terminará y se borrarán sus archivos.",
        });
      }
      await removeJob(job);
      return sendJson(res, 200, { ok: true, id: job.id, eliminado: true });
    }

    return sendError(res, 405, "Método no permitido.");
  }

  if (parts[0] === "files" && parts.length === 3) {
    const job = jobs.get(parts[1]);
    if (!job) return sendError(res, 404, "Trabajo no encontrado.");
    const index = Number(parts[2]);
    if (!Number.isInteger(index) || index < 0) {
      return sendError(res, 400, "Índice de archivo inválido.");
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      return sendError(res, 405, "Método no permitido.");
    }
    return handleFile(req, res, job, index);
  }

  return sendError(res, 404, "Ruta no encontrada.");
}

const server = http.createServer((req, res) => {
  const started = Date.now();
  res.on("finish", () => {
    if (req.url !== "/health") {
      console.log(
        `${req.method} ${req.url} -> ${res.statusCode} (${Date.now() - started} ms)`,
      );
    }
  });
  route(req, res).catch((error) => {
    const status = Number(error?.status) || 500;
    if (status >= 500) {
      console.error(`[ytpremiun-api] ${req.method} ${req.url}: ${error.stack || error}`);
    }
    if (!res.headersSent) {
      sendError(res, status, String(error?.message || error));
    } else {
      res.destroy();
    }
  });
});

server.keepAliveTimeout = 65_000;
server.headersTimeout = 70_000;

// ------------------------------------------------------------------- arranque

(async () => {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  await loadJobs();

  try {
    const check = await yt.verificar();
    ffmpegPath = check.ffmpeg;
  } catch {
    ffmpegPath = null;
  }

  if (!ffmpegPath) {
    console.warn(
      "[ytpremiun-api] Aviso: no se encontró ffmpeg. No se podrán unir video+audio ni convertir audio.",
    );
  }

  await cleanup();
  const timer = setInterval(() => {
    cleanup().catch((error) => {
      console.error(`[ytpremiun-api] Error en la limpieza: ${error.message}`);
    });
  }, 10 * 60 * 1000);
  timer.unref();

  server.listen(PORT, HOST, () => {
    startedAt = nowIso();
    console.log(
      `[ytpremiun-api] Escuchando en http://${HOST}:${PORT} (v${yt.VERSION}, ffmpeg: ${ffmpegPath || "no"})`,
    );
    console.log(`[ytpremiun-api] Datos en ${DATA_DIR}`);
  });

  const shutdown = (signal) => {
    console.log(`[ytpremiun-api] ${signal}: cerrando...`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 8000).unref();
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
})();

module.exports = { server };

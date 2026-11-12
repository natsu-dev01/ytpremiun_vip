/** Utilidades generales: nombres de archivo, plantillas, índices y formato. */

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const WINDOWS_RESERVED = new Set([
  "CON",
  "PRN",
  "AUX",
  "NUL",
  ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`),
]);

const ILLEGAL_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;
const TEMPLATE_RE =
  /%\(([A-Za-z_][A-Za-z0-9_]*)\)(?:(\d+)([dsif])|([dsif]))?/g;
const SIZE_RE = /^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?)i?b?\s*$/i;

/** Convierte bytes a una cadena legible (KiB, MiB...). */
function humanBytes(num) {
  if (num === null || num === undefined) return "?";
  const value = Number(num);
  if (!Number.isFinite(value) || value < 0) return "?";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let index = 0;
  let current = value;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  if (index === 0) return `${Math.trunc(current)} ${units[index]}`;
  return `${current.toFixed(1)} ${units[index]}`;
}

function humanSpeed(bytesPerSecond) {
  if (!bytesPerSecond || bytesPerSecond <= 0) return "?";
  return `${humanBytes(bytesPerSecond)}/s`;
}

/** Formatea segundos como HH:MM:SS o MM:SS. */
function humanDuration(seconds) {
  if (seconds === null || seconds === undefined) return "?";
  const total = Math.round(Number(seconds));
  if (!Number.isFinite(total) || total < 0) return "?";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const two = (value) => String(value).padStart(2, "0");
  if (hours) return `${two(hours)}:${two(minutes)}:${two(secs)}`;
  return `${two(minutes)}:${two(secs)}`;
}

function humanEta(seconds) {
  if (
    seconds === null ||
    seconds === undefined ||
    !Number.isFinite(Number(seconds)) ||
    Number(seconds) < 0 ||
    Number(seconds) > 86400 * 10
  ) {
    return "--:--";
  }
  return humanDuration(seconds);
}

/** Convierte '1.5M', '20 MiB' o '1024' a bytes. */
function parseSize(text) {
  const match = SIZE_RE.exec(String(text || ""));
  if (!match) return null;
  const multipliers = { "": 1, k: 1024, m: 1024 ** 2, g: 1024 ** 3, t: 1024 ** 4 };
  return Math.trunc(Number(match[1]) * multipliers[match[2].toLowerCase()]);
}

/** Limpia un nombre para que sea válido en Windows, macOS y Linux. */
function sanitizeFilename(name, { restrict = false, maxLength = 180 } = {}) {
  if (name === null || name === undefined) return "download";
  let text = String(name);
  if (restrict) {
    // Equivalente a unicodedata.normalize("NFKD") + encode("ascii", "ignore").
    text = text
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\x00-\x7f]/g, "");
  }
  text = text.replace(ILLEGAL_CHARS, "_");
  text = text.replace(/\s+/g, " ");
  text = text.replace(/^[ .]+|[ .]+$/g, "");
  if (!text) text = "download";

  const stem = text.split(".", 1)[0].toUpperCase();
  if (WINDOWS_RESERVED.has(stem)) text = `_${text}`;

  if (text.length > maxLength) text = text.slice(0, maxLength).replace(/[ .]+$/g, "");
  return text || "download";
}

/** Expande plantillas tipo yt-dlp: %(title)s, %(playlist_index)03d... */
function formatTemplate(template, fields) {
  return String(template).replace(
    TEMPLATE_RE,
    (match, key, width, convA, convB) => {
      const value = fields[key];
      if (value === null || value === undefined) return "";
      const conv = convA || convB;

      if (conv === "d" || conv === "i") {
        const number = Number.parseInt(value, 10);
        if (!Number.isFinite(number)) return String(value);
        if (!width) return String(number);
        const negative = number < 0;
        const digits = String(Math.abs(number)).padStart(Number(width), "0");
        return negative ? `-${digits}` : digits;
      }
      if (conv === "f") {
        const number = Number(value);
        if (!Number.isFinite(number)) return String(value);
        return number.toFixed(width ? Number(width) : 2);
      }
      return String(value);
    },
  );
}

/** Construye una ruta segura a partir de la plantilla y los metadatos. */
function buildOutputPath(
  template,
  fields,
  baseDir,
  { restrict = false, maxFilename = 180 } = {},
) {
  const safeFields = {};
  for (const [key, value] of Object.entries(fields)) {
    safeFields[key] =
      typeof value === "string"
        ? sanitizeFilename(value, { restrict, maxLength: maxFilename })
        : value;
  }

  const rendered = formatTemplate(template, safeFields).replace(/\\/g, "/");
  const parts = [];
  for (let part of rendered.split("/")) {
    part = part.trim();
    if (!part || part === ".") continue;
    if (part === "..") part = "_";
    parts.push(sanitizeFilename(part, { restrict, maxLength: maxFilename }));
  }
  if (parts.length === 0) parts.push("download");
  return path.join(String(baseDir), ...parts);
}

/** Devuelve un predicado para '--playlist-items' (1-3,7,10-). */
function parseIndexSpec(spec) {
  if (!spec || !String(spec).trim()) return null;

  const ranges = [];
  for (const rawPart of String(spec).split(",")) {
    const part = rawPart.trim();
    if (!part) continue;
    if (part.includes("-")) {
      const [startText, endText = ""] = part.split("-", 2);
      let start = startText.trim() ? Number.parseInt(startText, 10) : 1;
      let end = endText.trim() ? Number.parseInt(endText, 10) : null;
      if (!Number.isFinite(start)) continue;
      if (start <= 0) start = 1;
      if (end !== null && (!Number.isFinite(end) || end < start)) {
        if (!Number.isFinite(end)) continue;
        [start, end] = [end, start];
      }
      ranges.push([start, end]);
    } else {
      const number = Number.parseInt(part, 10);
      if (Number.isFinite(number) && number > 0) ranges.push([number, number]);
    }
  }
  if (ranges.length === 0) return null;

  return (index) =>
    ranges.some(
      ([start, end]) => start <= index && (end === null || index <= end),
    );
}

/** Lee un archivo de URLs (una por línea, # como comentario). */
function readBatchFile(filePath) {
  let text = fs.readFileSync(filePath, "utf8");
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function dedupe(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    if (seen.has(item)) continue;
    seen.add(item);
    result.push(item);
  }
  return result;
}

/** Accede a un valor anidado con una ruta 'a.b.0.c'. */
function deepGet(obj, route, fallback = null) {
  let current = obj;
  for (const part of String(route).split(".")) {
    if (!part) continue;
    if (Array.isArray(current)) {
      const index = Number.parseInt(part, 10);
      if (!Number.isFinite(index)) return fallback;
      current = current[index];
    } else if (current && typeof current === "object") {
      current = current[part];
    } else {
      return fallback;
    }
    if (current === null || current === undefined) return fallback;
  }
  return current;
}

/** Extrae texto de las estructuras típicas de YouTube. */
function textOf(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    if (typeof value.simpleText === "string") return value.simpleText;
    if (Array.isArray(value.runs)) {
      return value.runs
        .filter((run) => run && typeof run === "object")
        .map((run) => String(run.text ?? ""))
        .join("");
    }
    if (typeof value.content === "string") return value.content;
  }
  return "";
}

function safeInt(value, fallback = 0) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : fallback;
}

function safeFloat(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function truncate(text, length, suffix = "...") {
  const source = String(text);
  if (source.length <= length) return source;
  if (length <= suffix.length) return source.slice(0, length);
  return source.slice(0, length - suffix.length) + suffix;
}

/** Escapa un texto para usarlo dentro de un JSON (compatibilidad). */
function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = {
  humanBytes,
  humanSpeed,
  humanDuration,
  humanEta,
  parseSize,
  sanitizeFilename,
  formatTemplate,
  buildOutputPath,
  parseIndexSpec,
  readBatchFile,
  dedupe,
  deepGet,
  textOf,
  safeInt,
  safeFloat,
  truncate,
  isPlainObject,
};

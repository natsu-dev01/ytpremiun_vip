/** Integración con ffmpeg: merge de video+audio, remux y extracción de audio. */

"use strict";

const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const { FFmpegNotFoundError, MediaError } = require("./errors");

function bundledFfmpeg() {
  const candidates = [];
  try {
    const value = require("ffmpeg-static");
    if (value) candidates.push(typeof value === "string" ? value : value.path);
  } catch {
    // La dependencia opcional no está instalada.
  }
  try {
    const installer = require("@ffmpeg-installer/ffmpeg");
    if (installer?.path) candidates.push(installer.path);
  } catch {
    // Alternativa opcional.
  }
  return candidates.find((candidate) => candidate && fs.existsSync(candidate));
}

function findFfmpeg() {
  const candidates = [];

  if (process.env.FFMPEG) candidates.push(process.env.FFMPEG);

  const fromPath = spawnSync("ffmpeg", ["-version"], {
    windowsHide: true,
    encoding: "utf8",
  });
  if (!fromPath.error && fromPath.status === 0) candidates.push("ffmpeg");

  const bundled = bundledFfmpeg();
  if (bundled) candidates.push(bundled);

  if (process.platform === "win32") {
    candidates.push(
      "C:\\ffmpeg\\bin\\ffmpeg.exe",
      "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
      "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe",
    );
  }

  for (const candidate of candidates) {
    if (candidate && (candidate === "ffmpeg" || fs.existsSync(candidate))) {
      return candidate;
    }
  }

  throw new FFmpegNotFoundError(
    "ffmpeg no está instalado o no se encuentra en el PATH. " +
      "Instala la dependencia opcional `ffmpeg-static` (npm install ffmpeg-static), " +
      "define la variable FFMPEG con la ruta al ejecutable o instala ffmpeg en el " +
      "sistema. Sin ffmpeg no se pueden unir video+audio ni convertir a MP3; los " +
      "formatos progresivos y las pistas M4A directas sí funcionan.",
  );
}

function ffmpegAvailable() {
  try {
    findFfmpeg();
    return true;
  } catch {
    return false;
  }
}

function run(command) {
  return new Promise((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    let child;
    try {
      child = spawn(command[0], command.slice(1), {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      reject(new MediaError(`No se pudo ejecutar ffmpeg: ${error.message}`));
      return;
    }

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", (error) => {
      reject(new MediaError(`No se pudo ejecutar ffmpeg: ${error.message}`));
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      const output = (stderr || stdout || "").trim();
      const tail = output.split(/\r?\n/).slice(-10).join("\n");
      reject(new MediaError(`ffmpeg falló:\n${tail}`));
    });
  });
}

function metadataArgs(metadata) {
  const args = [];
  for (const [key, value] of Object.entries(metadata || {})) {
    if (value === null || value === undefined) continue;
    const text = String(value)
      .replace(/\x00/g, "")
      .replace(/\r/g, " ")
      .replace(/\n/g, " ")
      .trim();
    if (text) args.push("-metadata", `${key}=${text}`);
  }
  return args;
}

function baseCommand() {
  return [
    findFfmpeg(),
    "-hide_banner",
    "-loglevel",
    "error",
    "-nostdin",
    "-y",
  ];
}

/** Une una pista de video y otra de audio sin recodificar. */
async function merge(video, audio, output, metadata = null) {
  const outputPath = String(output);
  await fsp.mkdir(path.dirname(outputPath), { recursive: true });
  const command = baseCommand().concat([
    "-i",
    String(video),
    "-i",
    String(audio),
    "-map",
    "0:v:0",
    "-map",
    "1:a:0",
    "-c",
    "copy",
  ]);
  if (path.extname(outputPath).toLowerCase() === ".mp4") {
    command.push("-movflags", "+faststart");
  }
  command.push(...metadataArgs(metadata), outputPath);
  await run(command);
}

/** Cambia el contenedor sin recodificar. */
async function remux(source, output, metadata = null) {
  const outputPath = String(output);
  await fsp.mkdir(path.dirname(outputPath), { recursive: true });
  const command = baseCommand().concat([
    "-i",
    String(source),
    "-c",
    "copy",
  ]);
  if (path.extname(outputPath).toLowerCase() === ".mp4") {
    command.push("-movflags", "+faststart");
  }
  command.push(...metadataArgs(metadata), outputPath);
  await run(command);
}

function normalizeQuality(quality, fallback = "192k") {
  if (!quality) return fallback;
  const text = String(quality).trim().toLowerCase();
  if (["best", "0", "none"].includes(text)) return fallback;
  if (/^\d+$/.test(text)) return `${text}k`;
  if (text.endsWith("k") || text.endsWith("m")) return text;
  return fallback;
}

/** Extrae y convierte el audio al formato indicado. */
async function extractAudio(
  source,
  output,
  format,
  quality = "192K",
  metadata = null,
) {
  const outputPath = String(output);
  await fsp.mkdir(path.dirname(outputPath), { recursive: true });
  const target = String(format || path.extname(outputPath).slice(1)).toLowerCase();

  const codecMap = {
    mp3: "libmp3lame",
    m4a: "aac",
    aac: "aac",
    opus: "libopus",
    ogg: "libopus",
    wav: "pcm_s16le",
    flac: "flac",
  };
  const codec = codecMap[target];
  if (!codec) throw new MediaError(`Formato de audio no soportado: ${target}`);

  const sourceExt = path.extname(String(source)).slice(1).toLowerCase();
  if (sourceExt === target) {
    await fsp.copyFile(String(source), outputPath);
    return;
  }

  const copyStream =
    (sourceExt === "webm" && target === "opus") ||
    (sourceExt === "mp4" && target === "m4a");

  const command = baseCommand().concat([
    "-i",
    String(source),
    "-vn",
    "-map",
    "0:a:0",
    "-c:a",
    copyStream ? "copy" : codec,
  ]);
  if (!copyStream && ["mp3", "m4a", "aac", "opus", "ogg"].includes(target)) {
    command.push("-b:a", normalizeQuality(quality));
  }
  if ([".m4a", ".mp4"].includes(path.extname(outputPath).toLowerCase())) {
    command.push("-movflags", "+faststart");
  }
  command.push(...metadataArgs(metadata), outputPath);
  await run(command);
}

module.exports = {
  findFfmpeg,
  ffmpegAvailable,
  merge,
  remux,
  extractAudio,
  normalizeQuality,
  metadataArgs,
};

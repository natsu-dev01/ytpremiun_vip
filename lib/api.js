/**
 * API de alto nivel del motor nativo de ytpremiun-vip.
 *
 * Todos los nombres de opciones del wrapper de Node.js se mantienen
 * (`carpeta`, `formatoAudio`, `calidadAudio`, `conexiones`, `trabajos`...) y el
 * formato de los resultados es idéntico al que devolvía el wrapper de Python.
 */

"use strict";

const path = require("node:path");
const {
  ExtractionError,
  YtPremiunError,
  YtPremiunVipError,
} = require("./errors");
const { Downloader, defaultOptions } = require("./downloader");
const { formatTable } = require("./formats");
const { HttpClient } = require("./http");
const { InnertubeClient, videoInfoToDict } = require("./innertube");
const { findFfmpeg } = require("./media");
const { parseInput } = require("./urls");

const VERSION = require("../package.json").version;

const ESTADOS = { ok: "ok", skipped: "omitido", failed: "fallido" };

function normalizarOpciones(opciones = {}) {
  const base = defaultOptions();
  const valor = (keys, fallback) => {
    for (const key of keys) {
      if (opciones[key] !== undefined && opciones[key] !== null) {
        return opciones[key];
      }
    }
    return fallback;
  };

  return {
    ...base,
    outputTemplate: valor(["plantilla", "outputTemplate"], base.outputTemplate),
    paths: valor(["carpeta", "paths"], base.paths),
    formatSpec: valor(["formato", "formatSpec"], base.formatSpec),
    audioOnly: Boolean(valor(["soloAudio", "solo_audio", "audioOnly"], base.audioOnly)),
    audioFormat: valor(["formatoAudio", "audioFormat", "formato_audio"], base.audioFormat),
    audioQuality: valor(
      ["calidadAudio", "audioQuality", "calidad_audio"],
      base.audioQuality,
    ),
    mergeOutputFormat: valor(
      ["contenedor", "mergeOutputFormat", "merge_output_format"],
      base.mergeOutputFormat,
    ),
    writeSubs: Boolean(valor(["subtitulos", "writeSubs", "write_subs"], base.writeSubs)),
    subLangs: valor(["idiomasSubtitulos", "subLangs", "sub_langs"], base.subLangs),
    subFormat: valor(["formatoSubtitulos", "subFormat", "sub_format"], base.subFormat),
    writeAutoSubs: Boolean(
      valor(["subtitulosAuto", "writeAutoSubs", "write_auto_subs"], base.writeAutoSubs),
    ),
    playlist:
      opciones.playlist === undefined ? base.playlist : Boolean(opciones.playlist),
    playlistItems: valor(
      ["elementosPlaylist", "playlistItems", "playlist_items"],
      base.playlistItems,
    ),
    maxDownloads: valor(
      ["maxDescargas", "maxDownloads", "max_downloads"],
      base.maxDownloads,
    ),
    archive: valor(["historial", "archive", "downloadArchive"], base.archive),
    restrictFilenames: Boolean(
      valor(["nombresAscii", "restrictFilenames", "restrict_filenames"], base.restrictFilenames),
    ),
    forceOverwrites: Boolean(
      valor(["sobrescribir", "forceOverwrites", "force_overwrites"], base.forceOverwrites),
    ),
    keepFiles: Boolean(
      valor(["conservarTemporales", "keepFiles", "keep_files"], base.keepFiles),
    ),
    quiet:
      opciones.silencioso === undefined
        ? opciones.quiet === undefined
          ? true
          : Boolean(opciones.quiet)
        : Boolean(opciones.silencioso),
    noProgress:
      opciones.progreso === undefined
        ? opciones.noProgress === undefined
          ? true
          : Boolean(opciones.noProgress)
        : !opciones.progreso,
    verbose: Boolean(valor(["verbose", "detallado"], base.verbose)),
    retries: Number(valor(["reintentos", "retries"], base.retries)),
    timeout: Number(valor(["timeout"], base.timeout)),
    connections: Number(
      valor(["conexiones", "connections"], base.connections),
    ),
    jobs: Number(valor(["trabajos", "jobs"], base.jobs)),
    proxy: valor(["proxy"], base.proxy),
    cookies: valor(["cookies"], base.cookies),
    onProgress:
      typeof opciones.onProgress === "function"
        ? opciones.onProgress
        : base.onProgress,
  };
}

function normalizarUrls(urls) {
  const list = Array.isArray(urls) ? urls : [urls];
  const clean = list
    .filter((url) => typeof url === "string")
    .map((url) => url.trim())
    .filter(Boolean);
  if (clean.length === 0) {
    throw new YtPremiunError("Indica al menos una URL de YouTube.");
  }
  return clean;
}

function aResultadoPublico(result) {
  const job = result.job;
  const info = result.info;
  const estado = ESTADOS[result.status] || result.status;
  const archivos = (result.paths || []).map((filePath) => String(filePath));
  return {
    ok: estado === "ok" || estado === "omitido",
    estado,
    id: job.video_id,
    url: job.url,
    titulo: info ? info.title : job.entry_title || job.video_id,
    autor: info ? info.author : "",
    duracion: info ? info.length_seconds : 0,
    archivo: archivos.length > 0 ? archivos[0] : null,
    archivos,
    error: result.error ?? null,
    playlist_id: job.playlist_id ?? null,
    playlist_titulo: job.playlist_title ?? null,
    playlist_indice: job.playlist_index ?? null,
  };
}

function aErrorPublico(url, error) {
  return {
    ok: false,
    estado: "fallido",
    id: "",
    url,
    titulo: "",
    autor: "",
    duracion: 0,
    archivo: null,
    archivos: [],
    error: String(error?.message || error),
    playlist_id: null,
    playlist_titulo: null,
    playlist_indice: null,
  };
}

async function ejecutar(urls, opciones) {
  const downloader = new Downloader(opciones);
  try {
    const { jobs, errors } = await downloader.discover(urls);
    const resultados = errors.map((item) => aErrorPublico(item.url, item.error));
    if (jobs.length > 0) {
      const descargas = await downloader.run(jobs);
      resultados.push(...descargas.map(aResultadoPublico));
    }
    return resultados;
  } finally {
    downloader.close();
  }
}

async function una(url, opciones) {
  const resultados = await ejecutar([url], opciones);
  if (resultados.length === 0) {
    throw new ExtractionError("No se encontró ningún video para descargar.");
  }
  for (const resultado of resultados) {
    if (!resultado.ok) {
      throw new YtPremiunVipError(
        resultado.error || `No se pudo descargar ${resultado.url}`,
        { resultados },
      );
    }
  }
  return resultados[0];
}

/** Descarga una o varias URLs y devuelve un resultado por video. */
async function descargar(urls, opciones = {}) {
  return ejecutar(normalizarUrls(urls), normalizarOpciones(opciones));
}

/** Descarga un video con audio y lanza YtPremiunError si falla. */
async function descargarVideo(url, opciones = {}) {
  const opcionesFinales = normalizarOpciones({
    ...opciones,
    soloAudio: false,
    playlist: opciones.playlist === undefined ? false : opciones.playlist,
  });
  return una(String(url), opcionesFinales);
}

/** Descarga el audio de un video y lanza YtPremiunError si falla. */
async function descargarAudio(url, opciones = {}) {
  const opcionesFinales = normalizarOpciones({
    ...opciones,
    soloAudio: true,
    playlist: opciones.playlist === undefined ? false : opciones.playlist,
  });
  return una(String(url), opcionesFinales);
}

/** Descarga una playlist completa o los elementos indicados. */
async function descargarPlaylist(url, opciones = {}) {
  return ejecutar(
    [String(url)],
    normalizarOpciones({ ...opciones, playlist: true }),
  );
}

/** Obtiene los metadatos de un video sin descargarlo. */
async function obtenerInfo(url, opciones = {}) {
  const ajustadas = normalizarOpciones(opciones);
  const parsed = parseInput(String(url));
  if (!parsed.video_id) {
    throw new ExtractionError(
      "La URL solo contiene una playlist; indica un video concreto.",
    );
  }

  const http = new HttpClient({
    timeout: ajustadas.timeout,
    retries: ajustadas.retries,
    proxy: ajustadas.proxy,
    cookies: ajustadas.cookies,
  });
  try {
    const info = await new InnertubeClient(http).getVideo(parsed.video_id);
    if (!info.webpage_url) {
      info.webpage_url = `https://www.youtube.com/watch?v=${info.id}`;
    }
    return videoInfoToDict(info);
  } finally {
    http.close();
  }
}

/** Devuelve la tabla de formatos disponibles como texto. */
async function listarFormatos(url, opciones = {}) {
  const info = await obtenerInfo(url, opciones);
  return formatTable(info.formats);
}

/**
 * Comprueba el motor, la versión de Node y ffmpeg.
 * Devuelve { ok, motor, node, version, ffmpeg, error }.
 */
async function verificar() {
  const resultado = {
    ok: true,
    motor: "node",
    node: process.version,
    version: VERSION,
    ffmpeg: null,
    error: null,
  };
  try {
    resultado.ffmpeg = findFfmpeg();
  } catch {
    resultado.ffmpeg = null;
  }
  return resultado;
}

/** Compatibilidad: argumentos del CLI clásico (Python). */
function _buildArgs(urls, opciones = {}, modo = "generic") {
  const lista = normalizarUrls(urls);
  const args = [
    "--json",
    "-P",
    String(opciones.carpeta || "downloads"),
  ];

  const soloAudio = modo === "audio" || opciones.soloAudio === true;
  if (soloAudio) {
    args.push(
      "-x",
      "--audio-format",
      String(opciones.formatoAudio || opciones.audioFormat || "mp3"),
    );
    if (opciones.calidadAudio || opciones.audioQuality) {
      args.push(
        "--audio-quality",
        String(opciones.calidadAudio || opciones.audioQuality),
      );
    }
  } else {
    if (opciones.formato) args.push("-f", String(opciones.formato));
    if (opciones.contenedor) {
      args.push("--merge-output-format", String(opciones.contenedor));
    }
  }

  const playlistPorDefecto = modo === "generic" || modo === "playlist";
  const playlist =
    opciones.playlist === undefined ? playlistPorDefecto : opciones.playlist;
  args.push(playlist ? "--playlist" : "--no-playlist");

  if (opciones.elementosPlaylist) {
    args.push("--playlist-items", String(opciones.elementosPlaylist));
  }
  if (opciones.maxDescargas != null) {
    args.push("--max-downloads", String(opciones.maxDescargas));
  }
  if (opciones.historial) {
    args.push("--download-archive", String(opciones.historial));
  }
  if (opciones.subtitulos) {
    args.push("--write-subs");
    if (opciones.idiomasSubtitulos) {
      args.push("--sub-langs", String(opciones.idiomasSubtitulos));
    }
    if (opciones.formatoSubtitulos) {
      args.push("--sub-format", String(opciones.formatoSubtitulos));
    }
  }
  if (opciones.subtitulosAuto) args.push("--write-auto-subs");
  if (opciones.nombresAscii) args.push("--restrict-filenames");
  if (opciones.sobrescribir) args.push("--force-overwrites");
  if (opciones.conservarTemporales) args.push("--keep-files");
  if (opciones.reintentos != null) {
    args.push("--retries", String(opciones.reintentos));
  }
  const conexiones = opciones.conexiones ?? opciones.connections;
  if (conexiones != null) args.push("--connections", String(conexiones));
  const trabajos = opciones.trabajos ?? opciones.jobs;
  if (trabajos != null) args.push("--jobs", String(trabajos));
  if (opciones.timeout != null) args.push("--timeout", String(opciones.timeout));
  if (opciones.proxy) args.push("--proxy", String(opciones.proxy));
  if (opciones.cookies) args.push("--cookies", String(opciones.cookies));

  args.push(...lista);
  return args;
}

module.exports = {
  VERSION,
  normalizarOpciones,
  normalizarUrls,
  aResultadoPublico,
  aErrorPublico,
  descargar,
  descargarAudio,
  descargarPlaylist,
  descargarVideo,
  listarFormatos,
  obtenerInfo,
  verificar,
  _buildArgs,
  defaultOptions,
};

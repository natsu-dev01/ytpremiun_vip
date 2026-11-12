/** Interfaz de línea de comandos nativa de ytpremiun-vip (sin Python). */

"use strict";

const { Downloader, defaultOptions } = require("./downloader");
const { aErrorPublico, aResultadoPublico, VERSION } = require("./api");
const { YtPremiunError } = require("./errors");
const { dedupe, readBatchFile } = require("./utils");
const { DEFAULT_CONNECTIONS } = require("./http");

const BOOLEAN_FLAGS = new Set([
  "-F",
  "--list-formats",
  "-x",
  "--extract-audio",
  "--write-subs",
  "--subs",
  "--write-auto-subs",
  "--playlist",
  "--no-playlist",
  "--restrict-filenames",
  "--force-overwrites",
  "--keep-files",
  "--no-progress",
  "-q",
  "--quiet",
  "-v",
  "--verbose",
  "--print-json",
  "--json",
  "--flat-playlist",
  "--simulate",
  "--version",
  "-h",
  "--help",
]);

const VALUE_FLAGS = new Set([
  "-a",
  "--batch-file",
  "-P",
  "--paths",
  "-o",
  "--output",
  "-f",
  "--format",
  "--audio-format",
  "--audio-quality",
  "--merge-output-format",
  "--sub-langs",
  "--sub-format",
  "--playlist-items",
  "--max-downloads",
  "--download-archive",
  "--retries",
  "--connections",
  "--conexiones",
  "-j",
  "--jobs",
  "--timeout",
  "--proxy",
  "--cookies",
]);

const HELP = `ytpremiun-vip ${VERSION} — descargador de YouTube (motor Node.js, sin Python)

Uso: ytpremiun-vip [opciones] URL...

Ejemplos:
  ytpremiun-vip "https://youtu.be/VIDEO"
  ytpremiun-vip -x --audio-format mp3 URL
  ytpremiun-vip -f "bv*[height<=1080]+ba" URL
  ytpremiun-vip -F URL
  ytpremiun-vip --write-subs --sub-langs es,en URL
  ytpremiun-vip -a urls.txt -P descargas
  ytpremiun-vip --download-archive historial.txt PLAYLIST

Opciones:
  URL...                        Una o más URLs de YouTube.
  -a, --batch-file ARCHIVO      Lee URLs de un archivo (una por línea, # comentarios).
  -P, --paths CARPETA           Carpeta de salida (por defecto: downloads).
  -o, --output PLANTILLA        Plantilla del nombre (%(title)s [%(id)s].%(ext)s).
  -f, --format SELECTOR         Selector de formato (por defecto: bv*+ba/b).
  -F, --list-formats            Muestra los formatos disponibles y no descarga.
  -x, --extract-audio           Descarga solo el audio.
  --audio-format FORMATO        mp3, m4a, opus, wav, flac o best (por defecto: mp3).
  --audio-quality BITRATE       Bitrate al recodificar (por defecto: 192K).
  --merge-output-format FORMATO mp4, mkv o webm (por defecto: mp4).
  --write-subs, --subs          Descarga subtítulos.
  --sub-langs IDIOMAS           Idiomas separados por coma o all.
  --sub-format FORMATO          srt, vtt o xml (por defecto: srt).
  --write-auto-subs             Incluye subtítulos automáticos (ASR).
  --playlist / --no-playlist    Descarga la playlist de la URL o solo el video.
  --playlist-items LISTA        Elementos a descargar: 1-5,8,10-.
  --max-downloads N             Máximo de videos en esta ejecución.
  --download-archive ARCHIVO    IDs ya descargados para omitirlos.
  --restrict-filenames          Nombres de archivo solo ASCII.
  --force-overwrites            Sobrescribe archivos existentes.
  --keep-files                  Conserva los archivos temporales.
  --no-progress                 Oculta la barra de progreso.
  -q, --quiet                   Modo silencioso.
  -v, --verbose                 Muestra trazas detalladas de errores.
  --retries N                   Reintentos por descarga (por defecto: 5).
  --connections N               Conexiones en paralelo por descarga (por defecto: ${DEFAULT_CONNECTIONS}).
  -j, --jobs N                  Videos descargados a la vez (por defecto: 1).
  --timeout SEGUNDOS            Timeout de red (por defecto: 20).
  --proxy URL                   Proxy HTTP/HTTPS.
  --cookies ARCHIVO             Cookies en formato Netscape.
  --print-json                  Imprime los metadatos del video en JSON.
  --json                        Imprime el resultado de las descargas en JSON.
  --flat-playlist               Imprime las URLs de la playlist sin descargar.
  --simulate                    Muestra qué se descargaría, sin descargar.
  --version                     Muestra la versión.
  -h, --help                    Muestra esta ayuda.
`;

function fail(mensaje) {
  const error = new Error(mensaje);
  error.userError = true;
  throw error;
}

function parseInteger(value, nombre, { min = null } = {}) {
  const number = Number.parseInt(value, 10);
  if (!Number.isFinite(number) || (min !== null && number < min)) {
    fail(`${nombre} necesita un número entero válido.`);
  }
  return number;
}

function parseArgs(argv) {
  const parsed = {
    urls: [],
    batchFile: null,
    paths: "downloads",
    output: "%(title)s [%(id)s].%(ext)s",
    formatSpec: null,
    listFormats: false,
    audioOnly: false,
    audioFormat: "mp3",
    audioQuality: "192K",
    mergeOutputFormat: "mp4",
    writeSubs: false,
    subLangs: null,
    subFormat: "srt",
    writeAutoSubs: false,
    playlist: true,
    playlistItems: null,
    maxDownloads: null,
    downloadArchive: null,
    restrictFilenames: false,
    forceOverwrites: false,
    keepFiles: false,
    noProgress: false,
    quiet: false,
    verbose: false,
    retries: 5,
    connections: DEFAULT_CONNECTIONS,
    jobs: 1,
    timeout: 20.0,
    proxy: null,
    cookies: null,
    printJson: false,
    jsonResult: false,
    flatPlaylist: false,
    simulate: false,
    version: false,
    help: false,
  };

  const positionals = [];
  const readValue = (index, flag) => {
    if (index + 1 >= argv.length) fail(`Falta el valor de ${flag}.`);
    return argv[index + 1];
  };

  for (let index = 0; index < argv.length; index += 1) {
    let token = argv[index];

    if (token === "--") {
      positionals.push(...argv.slice(index + 1));
      break;
    }

    if (!token.startsWith("-") || token === "-") {
      positionals.push(token);
      continue;
    }

    let inlineValue = null;
    if (token.startsWith("--")) {
      const equals = token.indexOf("=");
      if (equals > 0) {
        inlineValue = token.slice(equals + 1);
        token = token.slice(0, equals);
      }
    }

    if (BOOLEAN_FLAGS.has(token)) {
      if (inlineValue !== null) fail(`${token} no acepta valor.`);
      switch (token) {
        case "-F":
        case "--list-formats":
          parsed.listFormats = true;
          break;
        case "-x":
        case "--extract-audio":
          parsed.audioOnly = true;
          break;
        case "--write-subs":
        case "--subs":
          parsed.writeSubs = true;
          break;
        case "--write-auto-subs":
          parsed.writeAutoSubs = true;
          break;
        case "--playlist":
          parsed.playlist = true;
          break;
        case "--no-playlist":
          parsed.playlist = false;
          break;
        case "--restrict-filenames":
          parsed.restrictFilenames = true;
          break;
        case "--force-overwrites":
          parsed.forceOverwrites = true;
          break;
        case "--keep-files":
          parsed.keepFiles = true;
          break;
        case "--no-progress":
          parsed.noProgress = true;
          break;
        case "-q":
        case "--quiet":
          parsed.quiet = true;
          break;
        case "-v":
        case "--verbose":
          parsed.verbose = true;
          break;
        case "--print-json":
          parsed.printJson = true;
          break;
        case "--json":
          parsed.jsonResult = true;
          break;
        case "--flat-playlist":
          parsed.flatPlaylist = true;
          break;
        case "--simulate":
          parsed.simulate = true;
          break;
        case "--version":
          parsed.version = true;
          break;
        case "-h":
        case "--help":
          parsed.help = true;
          break;
        default:
          break;
      }
      continue;
    }

    if (!VALUE_FLAGS.has(token)) fail(`Opción desconocida: ${token}`);

    let value = inlineValue;
    if (value === null) {
      value = readValue(index, token);
      index += 1;
    }

    switch (token) {
      case "-a":
      case "--batch-file":
        parsed.batchFile = value;
        break;
      case "-P":
      case "--paths":
        parsed.paths = value;
        break;
      case "-o":
      case "--output":
        parsed.output = value;
        break;
      case "-f":
      case "--format":
        parsed.formatSpec = value;
        break;
      case "--audio-format": {
        const format = value.toLowerCase();
        if (!["mp3", "m4a", "opus", "wav", "flac", "best"].includes(format)) {
          fail(`Formato de audio no válido: ${value}`);
        }
        parsed.audioFormat = format;
        break;
      }
      case "--audio-quality":
        parsed.audioQuality = value;
        break;
      case "--merge-output-format": {
        const format = value.toLowerCase();
        if (!["mp4", "mkv", "webm"].includes(format)) {
          fail(`Contenedor no válido: ${value}`);
        }
        parsed.mergeOutputFormat = format;
        break;
      }
      case "--sub-langs":
        parsed.subLangs = value;
        break;
      case "--sub-format": {
        const format = value.toLowerCase();
        if (!["srt", "vtt", "xml"].includes(format)) {
          fail(`Formato de subtítulos no válido: ${value}`);
        }
        parsed.subFormat = format;
        break;
      }
      case "--playlist-items":
        parsed.playlistItems = value;
        break;
      case "--max-downloads":
        parsed.maxDownloads = parseInteger(value, "--max-downloads", { min: 0 });
        break;
      case "--download-archive":
        parsed.downloadArchive = value;
        break;
      case "--retries":
        parsed.retries = parseInteger(value, "--retries", { min: 0 });
        break;
      case "--connections":
      case "--conexiones":
        parsed.connections = parseInteger(value, "--connections", { min: 1 });
        break;
      case "-j":
      case "--jobs":
        parsed.jobs = parseInteger(value, "--jobs", { min: 1 });
        break;
      case "--timeout": {
        const number = Number(value);
        if (!Number.isFinite(number) || number <= 0) {
          fail("--timeout necesita un número de segundos válido.");
        }
        parsed.timeout = number;
        break;
      }
      case "--proxy":
        parsed.proxy = value;
        break;
      case "--cookies":
        parsed.cookies = value;
        break;
      default:
        break;
    }
  }

  parsed.urls = positionals;
  return parsed;
}

function optionsFromArgs(args) {
  return defaultOptions({
    outputTemplate: args.output,
    paths: args.paths,
    formatSpec: args.formatSpec,
    audioOnly: args.audioOnly,
    audioFormat: args.audioFormat,
    audioQuality: args.audioQuality,
    mergeOutputFormat: args.mergeOutputFormat,
    writeSubs: args.writeSubs,
    subLangs: args.subLangs,
    subFormat: args.subFormat,
    writeAutoSubs: args.writeAutoSubs,
    playlist: args.playlist,
    playlistItems: args.playlistItems,
    maxDownloads: args.maxDownloads,
    archive: args.downloadArchive,
    restrictFilenames: args.restrictFilenames,
    forceOverwrites: args.forceOverwrites,
    keepFiles: args.keepFiles,
    quiet: args.quiet || args.jsonResult,
    noProgress: args.noProgress || args.jsonResult,
    verbose: args.verbose,
    retries: args.retries,
    timeout: args.timeout,
    connections: args.connections,
    jobs: args.jobs,
    proxy: args.proxy,
    cookies: args.cookies,
    listFormats: args.listFormats,
    printJson: args.printJson,
    flatPlaylist: args.flatPlaylist,
    simulate: args.simulate,
  });
}

async function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (error) {
    process.stderr.write(`ERROR: ${error.message}\n`);
    return 2;
  }

  if (args.help) {
    process.stdout.write(HELP);
    return 0;
  }
  if (args.version) {
    process.stdout.write(`ytpremiun-vip ${VERSION}\n`);
    return 0;
  }

  let inputs = [...args.urls];
  if (args.batchFile) {
    try {
      inputs = [...readBatchFile(args.batchFile), ...inputs];
    } catch (error) {
      process.stderr.write(
        `ERROR: no se pudo leer ${args.batchFile}: ${error.message}\n`,
      );
      return 2;
    }
  }
  inputs = dedupe(inputs);
  if (inputs.length === 0) {
    process.stderr.write(
      "ERROR: Indica al menos una URL o usa -a/--batch-file.\n" +
        "Usa --help para ver las opciones.\n",
    );
    return 2;
  }

  const options = optionsFromArgs(args);
  const downloader = new Downloader(options);
  try {
    const { jobs, errors } = await downloader.discover(inputs);

    let salida;
    if (args.jsonResult) {
      salida = errors.map((item) => aErrorPublico(item.url, item.error));
    } else {
      for (const item of errors) {
        process.stderr.write(`ERROR ${item.url}: ${item.error.message}\n`);
      }
      salida = [];
    }

    if (jobs.length === 0) {
      if (args.jsonResult) {
        process.stdout.write(`${JSON.stringify(salida, null, 2)}\n`);
      } else {
        process.stderr.write("No hay nada que descargar.\n");
      }
      return 1;
    }

    if (args.flatPlaylist) {
      if (args.jsonResult) {
        process.stdout.write(
          `${JSON.stringify(
            {
              urls: jobs.map((job) => job.url),
              errores: errors.map((item) => ({
                url: item.url,
                error: item.error.message,
              })),
            },
            null,
            2,
          )}\n`,
        );
      } else {
        for (const job of jobs) process.stdout.write(`${job.url}\n`);
      }
      return errors.length > 0 ? 1 : 0;
    }

    const results = await downloader.run(jobs);

    if (args.jsonResult) {
      salida.push(...results.map(aResultadoPublico));
      process.stdout.write(`${JSON.stringify(salida, null, 2)}\n`);
      return salida.every((item) => item.ok) ? 0 : 1;
    }

    const ok = results.filter((result) => result.status === "ok").length;
    const skipped = results.filter((result) => result.status === "skipped").length;
    const failed = results.filter((result) => result.status === "failed").length;

    process.stdout.write(
      `\nResumen: ${ok} correctos, ${skipped} omitidos, ${failed} fallidos\n`,
    );
    for (const result of results) {
      if (result.status === "failed") {
        process.stderr.write(`  ✗ ${result.job.url}: ${result.error}\n`);
      }
    }

    return failed === 0 && errors.length === 0 ? 0 : 1;
  } catch (error) {
    if (error instanceof YtPremiunError || error?.userError) {
      process.stderr.write(`ERROR: ${error.message}\n`);
    } else {
      process.stderr.write(`ERROR: ${error?.stack || error}\n`);
    }
    return 1;
  } finally {
    downloader.close();
  }
}

module.exports = { main, parseArgs, optionsFromArgs, HELP };

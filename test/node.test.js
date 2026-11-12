"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  YtPremiunError,
  YtPremiunVipError,
  ExtractionError,
  _buildArgs,
  verificar,
} = require("../index.js");
const { parseArgs } = require("../lib/cli");
const { selectFormat } = require("../lib/formats");
const { parseTimedtext } = require("../lib/subtitles");
const { parseInput } = require("../lib/urls");
const { buildOutputPath } = require("../lib/utils");

const URL = "https://youtu.be/jNQXAC9IVRw";

test("audio usa mp3 y no descarga la playlist", () => {
  const args = _buildArgs(URL, { carpeta: "media" }, "audio");
  assert.equal(args.at(-1), URL);
  assert.ok(args.includes("-x"));
  assert.equal(args[args.indexOf("--audio-format") + 1], "mp3");
  assert.ok(args.includes("--no-playlist"));
  assert.equal(args[args.indexOf("-P") + 1], "media");
});

test("audio respeta formato y calidad", () => {
  const args = _buildArgs(URL, { formatoAudio: "m4a", calidadAudio: "320K" }, "audio");
  assert.equal(args[args.indexOf("--audio-format") + 1], "m4a");
  assert.equal(args[args.indexOf("--audio-quality") + 1], "320K");
});

test("video activa playlist si se pide", () => {
  const args = _buildArgs(URL, { playlist: true, contenedor: "mkv" }, "video");
  assert.ok(args.includes("--playlist"));
  assert.equal(args[args.indexOf("--merge-output-format") + 1], "mkv");
});

test("mapea cookies, subtítulos e historial", () => {
  const args = _buildArgs(
    URL,
    {
      cookies: "cookies.txt",
      subtitulos: true,
      idiomasSubtitulos: "es,en",
      subtitulosAuto: true,
      historial: "historial.txt",
      maxDescargas: 3,
      reintentos: 2,
      timeout: 10,
    },
    "video",
  );
  assert.equal(args[args.indexOf("--cookies") + 1], "cookies.txt");
  assert.ok(args.includes("--write-subs"));
  assert.equal(args[args.indexOf("--sub-langs") + 1], "es,en");
  assert.ok(args.includes("--write-auto-subs"));
  assert.equal(args[args.indexOf("--download-archive") + 1], "historial.txt");
  assert.equal(args[args.indexOf("--max-downloads") + 1], "3");
  assert.equal(args[args.indexOf("--retries") + 1], "2");
  assert.equal(args[args.indexOf("--timeout") + 1], "10");
});

test("mapea conexiones en paralelo", () => {
  const args = _buildArgs(URL, { conexiones: 8 }, "audio");
  assert.equal(args[args.indexOf("--connections") + 1], "8");
  const alias = _buildArgs(URL, { connections: 3 }, "video");
  assert.equal(alias[alias.indexOf("--connections") + 1], "3");
});

test("mapea trabajos en paralelo", () => {
  const args = _buildArgs(URL, { trabajos: 3 }, "playlist");
  assert.equal(args[args.indexOf("--jobs") + 1], "3");
  const alias = _buildArgs(URL, { jobs: 2 }, "playlist");
  assert.equal(alias[alias.indexOf("--jobs") + 1], "2");
});

test("acepta varias URLs", () => {
  const args = _buildArgs([URL, "https://youtu.be/dQw4w9WgXcQ"], {}, "generic");
  assert.deepEqual(args.slice(-2), [URL, "https://youtu.be/dQw4w9WgXcQ"]);
});

test("rechaza una lista vacía", () => {
  assert.throws(() => _buildArgs([], {}), YtPremiunError);
});

test("parseInput reconoce vídeos, playlists y Shorts", () => {
  assert.deepEqual(parseInput("https://youtu.be/jNQXAC9IVRw"), {
    raw: "https://youtu.be/jNQXAC9IVRw",
    video_id: "jNQXAC9IVRw",
    playlist_id: null,
  });

  const conLista = parseInput(
    "https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL1234567890",
  );
  assert.equal(conLista.video_id, "jNQXAC9IVRw");
  assert.equal(conLista.playlist_id, "PL1234567890");

  const soloPlaylist = parseInput(
    "https://www.youtube.com/playlist?list=PL1234567890",
  );
  assert.equal(soloPlaylist.video_id, null);
  assert.equal(soloPlaylist.playlist_id, "PL1234567890");

  const shorts = parseInput("https://youtube.com/shorts/dQw4w9WgXcQ?feature=share");
  assert.equal(shorts.video_id, "dQw4w9WgXcQ");

  assert.throws(() => parseInput("https://example.com/video"), /YouTube/);
});

const FORMATOS = [
  {
    itag: 137,
    ext: "mp4",
    has_video: true,
    has_audio: false,
    url: "https://example.com/137",
    height: 1080,
    width: 1920,
    fps: 30,
    vcodec: "avc1.640028",
    acodec: "none",
    bitrate: 4_000_000,
    audio_bitrate: null,
    filesize: 40_000_000,
  },
  {
    itag: 140,
    ext: "m4a",
    has_video: false,
    has_audio: true,
    url: "https://example.com/140",
    height: null,
    width: null,
    fps: null,
    vcodec: "none",
    acodec: "mp4a.40.2",
    bitrate: null,
    audio_bitrate: 128_000,
    filesize: 4_000_000,
  },
  {
    itag: 18,
    ext: "mp4",
    has_video: true,
    has_audio: true,
    url: "https://example.com/18",
    height: 360,
    width: 640,
    fps: 30,
    vcodec: "avc1.42001E",
    acodec: "mp4a.40.2",
    bitrate: 500_000,
    audio_bitrate: 96_000,
    filesize: 9_000_000,
  },
];

test("selectFormat elige la mejor pista de vídeo y audio", () => {
  const seleccion = selectFormat(FORMATOS, "bv*+ba/b", {
    mergeExt: "mp4",
    audioExtPref: "m4a",
  });
  assert.equal(seleccion.video.itag, 137);
  assert.equal(seleccion.audio.itag, 140);
  assert.equal(seleccion.requiresMerge, true);
});

test("selectFormat acepta itags y filtros", () => {
  const porItag = selectFormat(FORMATOS, "18", { mergeExt: "mp4" });
  assert.equal(porItag.progressive.itag, 18);

  const filtrado = selectFormat(FORMATOS, "bv*[height<=720]+ba/b", {
    mergeExt: "mp4",
    audioExtPref: "m4a",
  });
  assert.equal(filtrado.progressive.itag, 18);
});

test("selectFormat extrae solo audio", () => {
  const seleccion = selectFormat(FORMATOS, null, {
    audioOnly: true,
    audioExtPref: "m4a",
  });
  assert.equal(seleccion.audio.itag, 140);
  assert.equal(seleccion.hasVideo, false);
});

test("buildOutputPath sanea nombres y conserva la carpeta", () => {
  const ruta = buildOutputPath(
    "%(title)s [%(id)s].%(ext)s",
    { title: 'A/B: "prueba"', id: "abc123", ext: "mp4" },
    "media",
  );
  assert.match(ruta.replace(/\\/g, "/"), /^media\/A_B_ _prueba_ \[abc123\]\.mp4$/);
});

test("parseTimedtext convierte XML, VTT y JSON3", () => {
  const xml =
    '<transcript><text start="1.5" dur="2">Hola &amp; adiós</text></transcript>';
  assert.deepEqual(parseTimedtext(xml), [
    { start: 1.5, end: 3.5, text: "Hola & adiós" },
  ]);

  const vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHola\n";
  assert.deepEqual(parseTimedtext(vtt), [
    { start: 1, end: 3, text: "Hola" },
  ]);

  const json3 = JSON.stringify({
    events: [{ tStartMs: 1000, dDurationMs: 2000, segs: [{ utf8: "Hola" }] }],
  });
  assert.deepEqual(parseTimedtext(json3), [
    { start: 1, end: 3, text: "Hola" },
  ]);
});

test("parseArgs interpreta opciones cortas, largas e inline", () => {
  const args = parseArgs([
    "-x",
    "--audio-format=m4a",
    "-P",
    "media",
    "-j",
    "3",
    "--connections",
    "2",
    "--write-subs",
    "--sub-langs",
    "es,en",
    URL,
  ]);
  assert.equal(args.audioOnly, true);
  assert.equal(args.audioFormat, "m4a");
  assert.equal(args.paths, "media");
  assert.equal(args.jobs, 3);
  assert.equal(args.connections, 2);
  assert.equal(args.writeSubs, true);
  assert.equal(args.subLangs, "es,en");
  assert.deepEqual(args.urls, [URL]);
});

test("parseArgs rechaza opciones desconocidas y valores inválidos", () => {
  assert.throws(() => parseArgs(["--inventada"]), /desconocida/);
  assert.throws(() => parseArgs(["--connections", "0"]), /entero válido/);
  assert.throws(() => parseArgs(["--audio-format", "ogg"]), /no válido/);
});

test("verificar informa del motor Node sin exigir Python", async () => {
  const estado = await verificar();
  assert.equal(estado.ok, true);
  assert.equal(estado.motor, "node");
  assert.match(estado.node, /^v\d+/);
  assert.equal(typeof estado.version, "string");
  assert.ok(estado.ffmpeg === null || typeof estado.ffmpeg === "string");
  assert.equal(estado.error, null);
});

test("los errores nativos heredan de YtPremiunError", () => {
  const error = new ExtractionError("sin formatos");
  assert.ok(error instanceof YtPremiunError);
  assert.ok(error instanceof YtPremiunVipError);
  assert.equal(error.name, "ExtractionError");
});

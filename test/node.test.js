"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { YtPremiunError, _buildArgs } = require("../index.js");

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

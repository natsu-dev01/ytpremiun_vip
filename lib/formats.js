/** Selección de formatos de video/audio y tabla para --list-formats. */

"use strict";

const { ExtractionError } = require("./errors");
const {
  formatResolution,
  formatSizeEstimate,
  formatKind,
} = require("./innertube");
const { humanBytes, parseSize } = require("./utils");

class NoMatchError extends Error {}

const FILTER_RE =
  /\[([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|!=|\^=|\$=|\*|=|<|>)\s*([^\]]*)\]/g;
const TOKEN_RE = /^([A-Za-z0-9_*!]+)((?:\[[^\]]*\])*)$/;

const AUDIO_BASES = new Set([
  "bestaudio",
  "ba",
  "bestaudio*",
  "ba*",
  "worstaudio",
  "wa",
  "worstaudio*",
  "wa*",
]);
const STRICT_AUDIO_BASES = new Set(["bestaudio", "ba", "worstaudio", "wa"]);
const VIDEO_BASES = new Set([
  "bestvideo",
  "bv",
  "bestvideo*",
  "bv*",
  "worstvideo",
  "wv",
  "worstvideo*",
  "wv*",
]);
const STRICT_VIDEO_BASES = new Set(["bestvideo", "bv", "worstvideo", "wv"]);

function makeSelection({ video = null, audio = null, progressive = null } = {}) {
  return {
    video,
    audio,
    progressive,
    get requiresMerge() {
      return (
        this.progressive === null && this.video !== null && this.audio !== null
      );
    },
    get hasVideo() {
      return this.progressive !== null || this.video !== null;
    },
    get hasAudio() {
      return (
        this.progressive !== null ||
        this.audio !== null ||
        (this.video !== null && this.video.has_audio)
      );
    },
    get primary() {
      return this.progressive || this.video || this.audio;
    },
  };
}

function alternatives(spec) {
  return String(spec)
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean);
}

function parseToken(token) {
  const match = TOKEN_RE.exec(String(token).trim());
  if (!match) throw new NoMatchError(`formato no válido: ${token}`);
  const base = match[1].toLowerCase();
  const filters = [];
  for (const filter of match[2].matchAll(FILTER_RE)) {
    filters.push([
      filter[1].toLowerCase(),
      filter[2],
      filter[3].trim().replace(/^['"]|['"]$/g, ""),
    ]);
  }
  return { base, filters };
}

function actualValue(format, field) {
  if (field === "itag" || field === "format_id" || field === "id") {
    return format.itag;
  }
  if (field === "height") return format.height;
  if (field === "width") return format.width;
  if (field === "fps") return format.fps;
  if (field === "tbr" || field === "bitrate") {
    return format.bitrate ? format.bitrate / 1000.0 : null;
  }
  if (field === "abr" || field === "audio_bitrate") {
    return format.audio_bitrate ? format.audio_bitrate / 1000.0 : null;
  }
  if (field === "filesize" || field === "filesize_approx" || field === "size") {
    return formatSizeEstimate(format);
  }
  if (field === "ext") return format.ext;
  if (field === "vcodec") return format.vcodec || "none";
  if (field === "acodec") return format.acodec || "none";
  if (field === "protocol") return "https";
  if (field === "resolution") return formatResolution(format);
  if (field === "audio_channels") return null;
  return null;
}

const NUMERIC_FIELDS = new Set([
  "itag",
  "format_id",
  "id",
  "height",
  "width",
  "fps",
  "tbr",
  "bitrate",
  "abr",
  "audio_bitrate",
  "filesize",
  "filesize_approx",
  "size",
]);

function filterMatches(format, field, op, value) {
  const actual = actualValue(format, field);
  if (actual === null || actual === undefined) return false;

  if (NUMERIC_FIELDS.has(field)) {
    let wanted;
    if (field === "filesize" || field === "filesize_approx" || field === "size") {
      wanted = parseSize(value);
      if (wanted === null) wanted = Number(value);
    } else {
      wanted = Number(value);
    }
    if (!Number.isFinite(wanted)) return false;
    const current = Number(actual);
    if (op === "<") return current < wanted;
    if (op === "<=") return current <= wanted;
    if (op === ">") return current > wanted;
    if (op === ">=") return current >= wanted;
    if (op === "=") return current === wanted;
    if (op === "!=") return current !== wanted;
    return false;
  }

  const actualText = String(actual).toLowerCase();
  const wantedText = String(value).toLowerCase();
  if (op === "=") return actualText === wantedText;
  if (op === "!=") return actualText !== wantedText;
  if (op === "^=") return actualText.startsWith(wantedText);
  if (op === "$=") return actualText.endsWith(wantedText);
  if (op === "*=") return actualText.includes(wantedText);
  if (op === "<") return actualText < wantedText;
  if (op === "<=") return actualText <= wantedText;
  if (op === ">") return actualText > wantedText;
  if (op === ">=") return actualText >= wantedText;
  return false;
}

function applyFilters(formats, filters) {
  let pool = formats;
  for (const [field, op, value] of filters) {
    pool = pool.filter((format) => filterMatches(format, field, op, value));
  }
  return pool;
}

function videoKey(format, mergeExt) {
  const extPref = format.ext === mergeExt ? 1 : 0;
  const avcPref = String(format.vcodec || "").toLowerCase().startsWith("avc")
    ? 2
    : 0;
  return [
    format.height || 0,
    format.fps || 0,
    extPref,
    avcPref,
    format.bitrate || 0,
    format.has_audio ? 1 : 0,
  ];
}

function audioKey(format, audioExtPref) {
  const extPref = audioExtPref && format.ext === audioExtPref ? 1 : 0;
  return [
    extPref,
    format.audio_bitrate || format.bitrate || 0,
    format.filesize || 0,
  ];
}

function compareKeys(left, right) {
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const a = left[index];
    const b = right[index];
    if (a < b) return -1;
    if (a > b) return 1;
  }
  return 0;
}

function pickSorted(pool, key, reverse) {
  const decorated = pool.map((format) => ({ format, key: key(format) }));
  decorated.sort((a, b) => compareKeys(a.key, b.key));
  if (reverse) decorated.reverse();
  return decorated.length > 0 ? decorated[0].format : null;
}

function selectToken(
  formats,
  token,
  { mergeExt, audioExtPref, role = "any" } = {},
) {
  const { base, filters } = parseToken(token);

  let pool;
  let key;
  let reverse;

  if (base === "best" || base === "b") {
    pool = formats.filter((format) => format.has_video);
    const progressive = pool.filter((format) => format.has_audio);
    if (progressive.length > 0) pool = progressive;
    key = (format) => videoKey(format, mergeExt);
    reverse = true;
  } else if (base === "worst" || base === "w") {
    pool = formats.filter((format) => format.has_video);
    key = (format) => videoKey(format, mergeExt);
    reverse = false;
  } else if (AUDIO_BASES.has(base)) {
    pool = formats.filter((format) => format.has_audio);
    if (STRICT_AUDIO_BASES.has(base)) {
      pool = pool.filter((format) => !format.has_video);
    }
    key = (format) => audioKey(format, audioExtPref);
    reverse = !base.startsWith("worst");
  } else if (VIDEO_BASES.has(base)) {
    pool = formats.filter((format) => format.has_video);
    if (STRICT_VIDEO_BASES.has(base)) {
      pool = pool.filter((format) => !format.has_audio);
    }
    key = (format) => videoKey(format, mergeExt);
    reverse = !base.startsWith("worst");
  } else if (/^\d+$/.test(base)) {
    const itag = Number.parseInt(base, 10);
    pool = formats.filter((format) => format.itag === itag);
    key = (format) => [format.itag];
    reverse = false;
  } else if (base === "all" || base === "*") {
    pool = [...formats];
    key = (format) => videoKey(format, mergeExt);
    reverse = true;
  } else {
    throw new NoMatchError(`formato desconocido: ${token}`);
  }

  pool = applyFilters(pool, filters);
  if (role === "video") pool = pool.filter((format) => format.has_video);
  else if (role === "audio") pool = pool.filter((format) => format.has_audio);
  if (pool.length === 0) return null;
  return pickSorted(pool, key, reverse);
}

function selectAudio(formats, spec, audioExtPref) {
  const errors = [];
  for (const alternative of alternatives(spec)) {
    const token = alternative.split("+", 1)[0].trim();
    try {
      const format = selectToken(formats, token, {
        mergeExt: "mp4",
        audioExtPref,
        role: "audio",
      });
      if (format !== null) return format;
      errors.push(`sin coincidencias para ${token}`);
    } catch (error) {
      if (!(error instanceof NoMatchError)) throw error;
      errors.push(error.message);
    }
  }

  const audioFormats = formats.filter((format) => format.has_audio);
  if (audioFormats.length > 0) {
    return pickSorted(audioFormats, (format) => audioKey(format, audioExtPref), true);
  }
  throw new ExtractionError(
    `No hay ningún formato de audio disponible. ${errors.join("; ")}`,
  );
}

function selectAlternative(formats, alternative, { mergeExt, audioExtPref }) {
  const tokens = String(alternative)
    .split("+")
    .map((token) => token.trim())
    .filter(Boolean);
  if (tokens.length === 0) throw new NoMatchError("alternativa vacía");
  if (tokens.length > 2) {
    throw new NoMatchError(`demasiados '+' en ${alternative}`);
  }

  if (tokens.length === 2) {
    const video = selectToken(formats, tokens[0], {
      mergeExt,
      audioExtPref,
      role: "video",
    });
    const audio = selectToken(formats, tokens[1], {
      mergeExt,
      audioExtPref,
      role: "audio",
    });
    if (video === null || audio === null) {
      throw new NoMatchError(`sin coincidencias para ${alternative}`);
    }
    if (video.has_audio) return makeSelection({ progressive: video });
    return makeSelection({ video, audio });
  }

  const token = tokens[0];
  const { base } = parseToken(token);

  if (AUDIO_BASES.has(base)) {
    const format = selectToken(formats, token, {
      mergeExt,
      audioExtPref,
      role: "audio",
    });
    if (format === null) throw new NoMatchError(`sin coincidencias para ${token}`);
    return makeSelection({ audio: format });
  }

  if (VIDEO_BASES.has(base) || base === "worst" || base === "w") {
    const format = selectToken(formats, token, {
      mergeExt,
      audioExtPref,
      role: "video",
    });
    if (format === null) throw new NoMatchError(`sin coincidencias para ${token}`);
    if (format.has_video && format.has_audio) {
      return makeSelection({ progressive: format });
    }
    if (format.has_video) return makeSelection({ video: format });
    return makeSelection({ audio: format });
  }

  if (base === "best" || base === "b") {
    const format = selectToken(formats, token, {
      mergeExt,
      audioExtPref,
      role: "video",
    });
    if (format === null) throw new NoMatchError(`sin coincidencias para ${token}`);
    if (format.has_audio) return makeSelection({ progressive: format });
    const audio = selectToken(formats, "bestaudio", {
      mergeExt,
      audioExtPref,
      role: "audio",
    });
    return makeSelection({ video: format, audio });
  }

  const format = selectToken(formats, token, {
    mergeExt,
    audioExtPref,
    role: "any",
  });
  if (format === null) throw new NoMatchError(`sin coincidencias para ${token}`);
  if (format.has_video && format.has_audio) {
    return makeSelection({ progressive: format });
  }
  if (format.has_video) return makeSelection({ video: format });
  return makeSelection({ audio: format });
}

/** Selecciona formatos. Lanza ExtractionError si nada coincide. */
function selectFormat(
  formats,
  spec = null,
  {
    audioOnly = false,
    mergeExt = "mp4",
    audioExtPref = null,
  } = {},
) {
  const usable = formats.filter((format) => format && format.url);
  if (usable.length === 0) {
    throw new ExtractionError("El video no tiene formatos descargables.");
  }

  if (audioOnly) {
    const selected = selectAudio(usable, spec || "bestaudio/best", audioExtPref);
    return makeSelection({ audio: selected });
  }

  const requested = spec || "bv*+ba/b";
  const errors = [];
  for (const alternative of alternatives(requested)) {
    try {
      const selection = selectAlternative(usable, alternative, {
        mergeExt,
        audioExtPref,
      });
      if (selection.primary !== null) return selection;
    } catch (error) {
      if (!(error instanceof NoMatchError)) throw error;
      errors.push(error.message);
    }
  }

  const detail = errors.length > 0 ? errors.join("; ") : "ninguna alternativa válida";
  throw new ExtractionError(
    `No se encontró un formato que coincida con '${requested}'. ${detail}`,
  );
}

function formatTable(formats) {
  const video = formats
    .filter((format) => format.has_video)
    .sort((a, b) => (a.height || 0) - (b.height || 0) || (a.fps || 0) - (b.fps || 0));
  const audio = formats
    .filter((format) => !format.has_video && format.has_audio)
    .sort(
      (a, b) =>
        (b.audio_bitrate || b.bitrate || 0) -
        (a.audio_bitrate || a.bitrate || 0),
    );
  const rows = [...video, ...audio];

  const header =
    `${"ID".padStart(4)}  ${"TIPO".padEnd(11)}  ${"EXT".padEnd(4)}  ` +
    `${"RES".padEnd(9)}  ${"FPS".padStart(3)}  ${"VCODEC".padEnd(18)}  ` +
    `${"ACODEC".padEnd(14)}  ${"TAMAÑO".padStart(9)}  NOTA`;
  const lines = [header, "-".repeat(header.length)];
  for (const format of rows) {
    const size = formatSizeEstimate(format);
    lines.push(
      `${String(format.itag).padStart(4)}  ${formatKind(format).padEnd(11)}  ` +
        `${format.ext.padEnd(4)}  ${formatResolution(format).padEnd(9)}  ` +
        `${String(format.fps || 0).padStart(3)}  ` +
        `${(format.vcodec || "-").padEnd(18)}  ` +
        `${(format.acodec || "-").padEnd(14)}  ` +
        `${(size ? humanBytes(size) : "?").padStart(9)}  ` +
        `${format.quality_label || format.audio_quality || ""}`,
    );
  }
  return lines.join("\n");
}

module.exports = {
  NoMatchError,
  makeSelection,
  selectFormat,
  formatTable,
  videoKey,
  audioKey,
  parseToken,
};

/** Descarga y conversión de subtítulos de YouTube. */

"use strict";

const fsp = require("node:fs/promises");
const path = require("node:path");
const { safeFloat } = require("./utils");

const NAMED_ENTITIES = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

function decodeEntities(text) {
  return String(text || "").replace(
    /&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g,
    (match, entity) => {
      if (entity[0] === "#") {
        const hex = entity[1] === "x" || entity[1] === "X";
        const code = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
        if (Number.isFinite(code)) {
          try {
            return String.fromCodePoint(code);
          } catch {
            return match;
          }
        }
        return match;
      }
      const value = NAMED_ENTITIES[entity.toLowerCase()];
      return value !== undefined ? value : match;
    },
  );
}

function cleanText(text) {
  let value = decodeEntities(text || "");
  value = value.replace(/[\u200b\ufeff]/g, "").replace(/\xa0/g, " ");
  value = value.replace(/[ \t]+/g, " ");
  value = value.replace(/\n{3,}/g, "\n\n");
  return value.trim();
}

function stripTags(text) {
  return String(text || "").replace(/<[^>]*>/g, "");
}

function getAttribute(attributes, name) {
  const regex = new RegExp(`(?:^|\\s)${name}\\s*=\\s*"([^"]*)"`, "i");
  const match = regex.exec(attributes || "");
  return match ? decodeEntities(match[1]) : null;
}

function parseJson3(payload) {
  const cues = [];
  for (const event of payload.events || []) {
    if (!event || typeof event !== "object") continue;
    const start = safeFloat(event.tStartMs) / 1000.0;
    const duration = safeFloat(event.dDurationMs) / 1000.0;
    const text = cleanText(
      (event.segs || [])
        .filter((segment) => segment && typeof segment === "object")
        .map((segment) => String(segment.utf8 ?? ""))
        .join(""),
    );
    if (!text) continue;
    cues.push({ start, end: start + duration, text });
  }
  return cues;
}

function parseSrtLike(payload) {
  const cues = [];
  const timeRe =
    /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/;
  for (const block of String(payload).trim().split(/\r?\n\r?\n/)) {
    const lines = block.split(/\r?\n/);
    let match = null;
    let timeIndex = -1;
    for (let index = 0; index < lines.length; index += 1) {
      match = timeRe.exec(lines[index]);
      if (match) {
        timeIndex = index;
        break;
      }
    }
    if (!match) continue;
    const start =
      Number(match[1]) * 3600 +
      Number(match[2]) * 60 +
      Number(match[3]) +
      Number(match[4].padEnd(3, "0")) / 1000.0;
    const end =
      Number(match[5]) * 3600 +
      Number(match[6]) * 60 +
      Number(match[7]) +
      Number(match[8].padEnd(3, "0")) / 1000.0;
    const text = cleanText(lines.slice(timeIndex + 1).join("\n"));
    if (text) cues.push({ start, end, text });
  }
  return cues;
}

function parseXml(payload) {
  const cues = [];
  const elements = String(payload).matchAll(
    /<(p|text)\b([^>]*)>([\s\S]*?)<\/\1>/gi,
  );
  for (const element of elements) {
    const tag = element[1].toLowerCase();
    const attributes = element[2];
    const inner = stripTags(element[3]);
    if (tag === "p") {
      const startRaw = getAttribute(attributes, "t");
      if (startRaw === null) continue;
      const start = safeFloat(startRaw) / 1000.0;
      const duration = safeFloat(getAttribute(attributes, "d")) / 1000.0;
      const text = cleanText(inner);
      if (text) cues.push({ start, end: start + duration, text });
    } else {
      const startRaw = getAttribute(attributes, "start");
      if (startRaw === null) continue;
      const start = safeFloat(startRaw);
      const duration = safeFloat(getAttribute(attributes, "dur"));
      const text = cleanText(inner);
      if (text) cues.push({ start, end: start + duration, text });
    }
  }
  return cues;
}

/** Convierte XML timedtext, JSON3 o VTT/SRT a una lista de cues. */
function parseTimedtext(payload) {
  if (!payload || !String(payload).trim()) return [];
  const text = String(payload);

  if (text.trimStart().startsWith("{")) {
    try {
      return parseJson3(JSON.parse(text));
    } catch {
      return [];
    }
  }

  if (text.includes("-->") && !/<p\b|<text\b/i.test(text)) {
    return parseSrtLike(text);
  }

  const cues = parseXml(text);
  if (cues.length > 0) return cues;
  return parseSrtLike(text);
}

function srtTime(seconds) {
  const totalMs = Math.max(0, Math.round(Number(seconds) * 1000));
  const hours = Math.floor(totalMs / 3_600_000);
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000);
  const secs = Math.floor((totalMs % 60_000) / 1000);
  const millis = totalMs % 1000;
  const two = (value) => String(value).padStart(2, "0");
  return `${two(hours)}:${two(minutes)}:${two(secs)},${String(millis).padStart(
    3,
    "0",
  )}`;
}

function vttTime(seconds) {
  return srtTime(seconds).replace(",", ".");
}

function cuesToSrt(cues) {
  const blocks = cues.map(
    (cue, index) =>
      `${index + 1}\n${srtTime(cue.start)} --> ${srtTime(cue.end)}\n${cue.text}`,
  );
  return blocks.join("\n\n") + (blocks.length > 0 ? "\n" : "");
}

function cuesToVtt(cues) {
  const blocks = ["WEBVTT", ""];
  for (const cue of cues) {
    blocks.push(
      `${vttTime(cue.start)} --> ${vttTime(cue.end)}\n${cue.text}\n`,
    );
  }
  return blocks.join("\n");
}

function languageMatches(code, wanted) {
  const current = String(code || "").toLowerCase();
  const target = String(wanted || "").toLowerCase();
  if (!current || !target) return false;
  if (current === target) return true;
  const currentBase = current.split("-")[0];
  const targetBase = target.split("-")[0];
  return (
    currentBase === targetBase ||
    current.startsWith(`${target}-`) ||
    target.startsWith(`${current}-`)
  );
}

function selectTracks(tracks, langs, includeAuto, defaultLanguage) {
  if (!tracks || tracks.length === 0) return [];

  let wanted;
  if (langs && String(langs).trim()) {
    if (String(langs).trim().toLowerCase() === "all") {
      wanted = null;
    } else {
      wanted = String(langs)
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
    }
  } else {
    const fallback = defaultLanguage || tracks[0].language_code;
    wanted = [fallback];
  }

  const selected = [];
  const seen = new Set();
  for (const track of tracks) {
    if (track.is_auto && !includeAuto) continue;
    if (
      wanted !== null &&
      !wanted.some((language) =>
        languageMatches(track.language_code, language),
      )
    ) {
      continue;
    }
    const key = `${track.language_code}\u0000${track.is_auto}`;
    if (seen.has(key)) continue;
    seen.add(key);
    selected.push(track);
  }

  // Si no hay pista manual para el idioma pedido, usa la automática.
  if (selected.length === 0 && includeAuto) {
    for (const track of tracks) {
      if (
        wanted !== null &&
        !wanted.some((language) =>
          languageMatches(track.language_code, language),
        )
      ) {
        continue;
      }
      selected.push(track);
      break;
    }
  }
  return selected;
}

function subtitlePath(base, track, fmt) {
  let suffix = `.${track.language_code}`;
  if (track.is_auto) suffix += ".auto";
  return `${base}${suffix}.${fmt}`;
}

async function downloadSubtitle(
  track,
  http,
  base,
  fmt,
  { force = false } = {},
) {
  const destination = subtitlePath(base, track, fmt);
  if (!force) {
    try {
      await fsp.access(destination);
      return destination;
    } catch {
      // Se descarga.
    }
  }

  const payload = await http.getBytes(track.base_url, {
    headers: {
      Referer: "https://www.youtube.com/",
      "Accept-Language": "en-US,en;q=0.9",
    },
  });
  const text = payload.toString("utf8");

  if (fmt === "xml") {
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await fsp.writeFile(destination, text, "utf8");
    return destination;
  }

  const cues = parseTimedtext(text);
  if (cues.length === 0) return null;

  const content = fmt === "srt" ? cuesToSrt(cues) : cuesToVtt(cues);
  await fsp.mkdir(path.dirname(destination), { recursive: true });
  await fsp.writeFile(destination, content, "utf8");
  return destination;
}

module.exports = {
  cleanText,
  decodeEntities,
  parseJson3,
  parseSrtLike,
  parseXml,
  parseTimedtext,
  cuesToSrt,
  cuesToVtt,
  selectTracks,
  subtitlePath,
  downloadSubtitle,
};

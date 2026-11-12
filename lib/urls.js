/** Interpretación de URLs e identificadores de YouTube. */

"use strict";

const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;
const ALLOWED_HOSTS = new Set([
  "youtube.com",
  "youtu.be",
  "youtube-nocookie.com",
  "youtube.googleapis.com",
]);

function isVideoId(value) {
  return Boolean(value && VIDEO_ID_RE.test(String(value)));
}

function cleanHost(host) {
  let cleaned = String(host || "")
    .toLowerCase()
    .replace(/^\.+|\.+$/g, "");
  for (const prefix of ["www.", "m.", "music."]) {
    if (cleaned.startsWith(prefix)) cleaned = cleaned.slice(prefix.length);
  }
  return cleaned;
}

/** Acepta IDs, youtu.be, /watch, /shorts, /embed, /live y playlists. */
function parseInput(text) {
  const raw = String(text || "").trim();
  if (!raw) throw new Error("La URL está vacía");

  if (VIDEO_ID_RE.test(raw)) {
    return { raw, video_id: raw, playlist_id: null };
  }

  const candidate = raw.includes("://") ? raw : `https://${raw}`;
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error(`No es una URL de YouTube: ${raw}`);
  }

  const host = cleanHost(parsed.hostname);
  if (!ALLOWED_HOSTS.has(host)) {
    throw new Error(`No es una URL de YouTube: ${raw}`);
  }

  let playlistId = parsed.searchParams.get("list");
  let videoId = null;

  if (host === "youtu.be") {
    const first = parsed.pathname.replace(/^\/+|\/+$/g, "").split("/")[0];
    if (isVideoId(first)) videoId = first;
  } else {
    const fromQuery = parsed.searchParams.get("v");
    if (isVideoId(fromQuery)) videoId = fromQuery;
    if (!videoId) {
      const parts = parsed.pathname.split("/").filter(Boolean);
      if (
        parts.length >= 2 &&
        ["shorts", "embed", "live", "v"].includes(parts[0]) &&
        isVideoId(parts[1])
      ) {
        videoId = parts[1];
      }
    }
  }

  if (playlistId !== null) {
    playlistId = playlistId.trim();
    if (!playlistId) playlistId = null;
  }

  if (!videoId && !playlistId) {
    throw new Error(`No se encontró un video ni una playlist en: ${raw}`);
  }

  return { raw, video_id: videoId, playlist_id: playlistId };
}

function videoUrl(videoId) {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

function playlistUrl(playlistId) {
  return `https://www.youtube.com/playlist?list=${playlistId}`;
}

module.exports = {
  VIDEO_ID_RE,
  isVideoId,
  parseInput,
  videoUrl,
  playlistUrl,
};

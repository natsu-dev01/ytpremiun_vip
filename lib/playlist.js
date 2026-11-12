/** Lectura de listas de reproducción de YouTube. */

"use strict";

const { ExtractionError, NetworkError } = require("./errors");
const { DEFAULT_USER_AGENT } = require("./http");
const { isVideoId, playlistUrl } = require("./urls");
const { deepGet, textOf } = require("./utils");

const BROWSE_API = "https://www.youtube.com/youtubei/v1/browse";
const INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8";

const WEB_CLIENT = {
  clientName: "WEB",
  clientVersion: "2.20250101.00.00",
  hl: "en",
  gl: "US",
};

function* walk(node) {
  if (Array.isArray(node)) {
    for (const value of node) yield* walk(value);
  } else if (node && typeof node === "object") {
    yield node;
    for (const value of Object.values(node)) yield* walk(value);
  }
}

function lockupTitle(lockup) {
  const paths = [
    "metadata.lockupMetadataViewModel.title.content",
    "metadata.lockupMetadataViewModel.title.simpleText",
    "metadata.lockupMetadataViewModel.title.runs",
  ];
  for (const route of paths) {
    const text = textOf(deepGet(lockup, route));
    if (text) return text;
  }
  return "";
}

function playlistTitle(data) {
  const candidates = [
    "metadata.playlistMetadataRenderer.title",
    "header.playlistHeaderRenderer.title",
    "header.pageHeaderViewModel.title.content",
    "sidebar.playlistSidebarRenderer.items.0.playlistSidebarPrimaryInfoRenderer.title",
  ];
  for (const route of candidates) {
    const text = textOf(deepGet(data, route));
    if (text) return text;
  }
  return "";
}

function collectEntries(data) {
  const found = [];
  for (const node of walk(data)) {
    const lockup = node.lockupViewModel;
    if (lockup && typeof lockup === "object") {
      const videoId = lockup.contentId;
      if (isVideoId(videoId)) found.push([videoId, lockupTitle(lockup)]);
      continue;
    }
    const renderer = node.playlistVideoRenderer;
    if (renderer && typeof renderer === "object") {
      const videoId = renderer.videoId;
      if (isVideoId(videoId)) {
        found.push([videoId, textOf(renderer.title)]);
      }
    }
  }
  return found;
}

function findContinuation(data) {
  for (const node of walk(data)) {
    const item = node.continuationItemRenderer;
    if (item && typeof item === "object") {
      const token = deepGet(
        item,
        "continuationEndpoint.continuationCommand.token",
      );
      if (token) return String(token);
    }
  }

  const tokens = [];
  for (const node of walk(data)) {
    const command = node.continuationCommand;
    if (command && typeof command === "object" && command.token) {
      tokens.push(String(command.token));
    }
  }
  return tokens.length > 0 ? tokens[tokens.length - 1] : null;
}

/** Extrae el primer objeto JSON que aparece después de un marcador. */
function extractJsonAfter(text, marker) {
  const index = String(text).indexOf(marker);
  if (index < 0) return null;
  const start = String(text).indexOf("{", index);
  if (start < 0) return null;

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let position = start; position < text.length; position += 1) {
    const char = text[position];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') {
      inString = true;
      continue;
    }
    if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, position + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

class PlaylistClient {
  constructor(http) {
    this.http = http;
  }

  async fetch(playlistId, { maxItems = null } = {}) {
    const url = `${playlistUrl(playlistId)}&hl=en&gl=US`;
    let html;
    try {
      html = await this.http.getText(url, {
        headers: {
          "User-Agent": DEFAULT_USER_AGENT,
          "Accept-Language": "en-US,en;q=0.9",
        },
      });
    } catch (error) {
      if (error instanceof NetworkError) {
        throw new ExtractionError(
          `No se pudo abrir la playlist ${playlistId}: ${error.message}`,
        );
      }
      throw error;
    }

    const data = extractJsonAfter(html, "ytInitialData");
    if (!data || typeof data !== "object") {
      throw new ExtractionError(
        `No se pudo leer la playlist ${playlistId}. ` +
          "Puede ser privada, inexistente o requerir inicio de sesión.",
      );
    }

    const title = playlistTitle(data) || playlistId;
    const entries = [];
    const seen = new Set();
    let warning = null;

    const append = (found) => {
      for (const [videoId, entryTitle] of found) {
        if (seen.has(videoId)) continue;
        seen.add(videoId);
        entries.push({
          video_id: videoId,
          title: entryTitle || videoId,
          index: entries.length + 1,
          url: `https://www.youtube.com/watch?v=${videoId}`,
        });
      }
    };

    append(collectEntries(data));
    let token = findContinuation(data);
    let pages = 0;
    while (
      token &&
      (maxItems === null || entries.length < maxItems) &&
      pages < 100
    ) {
      let continuationData;
      try {
        continuationData = await this._browse(token);
      } catch (error) {
        if (error instanceof NetworkError) {
          warning = `No se pudo continuar la playlist: ${error.message}`;
          break;
        }
        throw error;
      }
      append(collectEntries(continuationData));
      token = findContinuation(continuationData);
      pages += 1;
    }

    if (maxItems !== null) entries.length = Math.min(entries.length, maxItems);

    if (entries.length === 0) {
      throw new ExtractionError(
        `La playlist ${playlistId} está vacía o no es accesible.`,
      );
    }

    return { id: playlistId, title, entries, warning };
  }

  async _browse(token) {
    const body = {
      context: { client: { ...WEB_CLIENT } },
      continuation: token,
    };
    const headers = {
      "Content-Type": "application/json",
      "User-Agent": DEFAULT_USER_AGENT,
      Origin: "https://www.youtube.com",
      Referer: "https://www.youtube.com/",
    };
    return this.http.postJson(
      `${BROWSE_API}?key=${INNERTUBE_KEY}&prettyPrint=false`,
      body,
      { headers },
    );
  }
}

module.exports = {
  BROWSE_API,
  INNERTUBE_KEY,
  PlaylistClient,
  extractJsonAfter,
  collectEntries,
  findContinuation,
};

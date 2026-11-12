/** Extracción de videos de YouTube mediante la API InnerTube (sin yt-dlp). */

"use strict";

const {
  ExtractionError,
  UnsupportedError,
} = require("./errors");
const { DEFAULT_USER_AGENT } = require("./http");
const { deepGet, safeFloat, safeInt, textOf } = require("./utils");

const INNERTUBE_API = "https://www.youtube.com/youtubei/v1/player";
const INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8";

const VISIONOS_USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) " +
  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15";

const VISITOR_DATA_RE = /"VISITOR_DATA"\s*:\s*"([^"]+)"/;

const MIME_EXT = {
  "video/mp4": "mp4",
  "video/webm": "webm",
  "video/3gpp": "3gp",
  "video/quicktime": "mov",
  "audio/mp4": "m4a",
  "audio/webm": "webm",
  "audio/mpeg": "mp3",
  "audio/ogg": "ogg",
  "audio/wav": "wav",
  "audio/flac": "flac",
};

const AUDIO_CODEC_PREFIXES = [
  "mp4a",
  "opus",
  "vorbis",
  "ac-3",
  "ec-3",
  "flac",
  "pcm",
  "mp3",
];

const CLIENTS = [
  {
    name: "visionos",
    client: {
      clientName: "VISIONOS",
      clientVersion: "1.02",
      deviceMake: "Apple",
      deviceModel: "RealityDevice17,1",
      userAgent: VISIONOS_USER_AGENT,
      osName: "visionOS",
      osVersion: "26.5.23O471",
      hl: "en",
      timeZone: "UTC",
      utcOffsetMinutes: 0,
    },
    userAgent: VISIONOS_USER_AGENT,
    clientId: 101,
  },
  {
    name: "android",
    client: {
      clientName: "ANDROID",
      clientVersion: "20.10.38",
      androidSdkVersion: 30,
      osName: "Android",
      osVersion: "11",
      hl: "en",
    },
    userAgent: "com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip",
    clientId: 3,
  },
  {
    name: "ios",
    client: {
      clientName: "IOS",
      clientVersion: "20.10.4",
      deviceModel: "iPhone16,2",
      osName: "iPhone",
      osVersion: "18.3.2.22D82",
      hl: "en",
    },
    userAgent:
      "com.google.ios.youtube/20.10.4 " +
      "(iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)",
    clientId: 5,
  },
  {
    name: "android_vr",
    client: {
      clientName: "ANDROID_VR",
      clientVersion: "1.62.27",
      deviceMake: "Oculus",
      deviceModel: "Quest 3",
      androidSdkVersion: 32,
      osName: "Android",
      osVersion: "12",
      hl: "en",
    },
    userAgent:
      "com.google.android.apps.youtube.vr.oculus/1.62.27 " +
      "(Linux; U; Android 12; GB) gzip",
    clientId: 28,
  },
];

function formatResolution(format) {
  if (format.has_video && format.height) {
    const suffix = format.fps && format.fps >= 50 ? String(format.fps) : "";
    return `${format.height}p${suffix}`;
  }
  if (format.has_video) return format.quality_label || "video";
  return "audio";
}

function formatSizeEstimate(format) {
  if (format.filesize) return format.filesize;
  if (format.bitrate && format.duration) {
    return Math.trunc((format.bitrate * format.duration) / 8);
  }
  return null;
}

function formatKind(format) {
  if (format.has_video && format.has_audio) return "video+audio";
  if (format.has_video) return "video";
  return "audio";
}

function formatCodecSummary(format) {
  const video = format.vcodec || "-";
  const audio = format.acodec || "-";
  if (!format.has_video) return audio;
  if (!format.has_audio) return video;
  return `${video} / ${audio}`;
}

function videoInfoToDict(info) {
  return {
    id: info.id,
    title: info.title,
    author: info.author,
    channel_id: info.channel_id,
    length_seconds: info.length_seconds,
    view_count: info.view_count,
    description: info.description,
    keywords: [...info.keywords],
    thumbnails: [...info.thumbnails],
    upload_date: info.upload_date,
    is_live: info.is_live,
    default_audio_language: info.default_audio_language,
    formats: info.formats.map((format) => ({ ...format })),
    subtitles: info.subtitles.map((track) => ({ ...track })),
    source_client: info.source_client,
    webpage_url:
      info.webpage_url ||
      `https://www.youtube.com/watch?v=${encodeURIComponent(info.id)}`,
  };
}

class InnertubeClient {
  constructor(http, { verbose = false } = {}) {
    this.http = http;
    this.verbose = verbose;
    this._visitorData = null;
    this._visitorPromise = null;
  }

  _ensureVisitorData() {
    if (this._visitorPromise) return this._visitorPromise;
    this._visitorPromise = (async () => {
      try {
        const page = await this.http.getText("https://www.youtube.com/", {
          headers: { "User-Agent": DEFAULT_USER_AGENT },
        });
        const match = VISITOR_DATA_RE.exec(page);
        if (match) this._visitorData = match[1];
      } catch {
        this._visitorData = null;
      }
      return this._visitorData;
    })();
    return this._visitorPromise;
  }

  async getVideo(videoId) {
    const errors = [];
    for (const client of CLIENTS) {
      let payload;
      try {
        payload = await this._player(videoId, client);
      } catch (error) {
        errors.push(`${client.name}: ${error.message}`);
        continue;
      }

      const status = deepGet(payload, "playabilityStatus.status");
      if (status !== "OK") {
        const reason =
          deepGet(payload, "playabilityStatus.reason") ||
          status ||
          "desconocido";
        errors.push(`${client.name}: ${status} (${reason})`);
        continue;
      }

      let info;
      try {
        info = this._parsePlayer(payload, videoId, client.name);
      } catch (error) {
        if (error instanceof UnsupportedError) throw error;
        errors.push(`${client.name}: ${error.message}`);
        continue;
      }

      if (info.formats.length > 0) return info;
      errors.push(`${client.name}: no devolvió formatos descargables`);
    }

    const detail = errors.length > 0 ? errors.join("; ") : "respuesta vacía";
    let hint = "";
    const joined = detail.toLowerCase();
    if (
      joined.includes("login_required") ||
      joined.includes("bot") ||
      joined.includes("sign in")
    ) {
      hint =
        " YouTube pidió iniciar sesión (o detectó un bot). " +
        "Prueba a pasar cookies con cookies (formato Netscape).";
    }
    throw new ExtractionError(
      `No se pudo extraer el video ${videoId}: ${detail}.${hint}`,
    );
  }

  async _player(videoId, client) {
    const body = {
      context: { client: { ...client.client } },
      videoId,
      contentCheckOk: true,
      racyCheckOk: true,
    };
    const headers = {
      "Content-Type": "application/json",
      "User-Agent": client.userAgent,
      Accept:
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-us,en;q=0.5",
      Origin: "https://www.youtube.com",
      Referer: `https://www.youtube.com/watch?v=${videoId}`,
    };
    if (client.clientId !== null && client.clientId !== undefined) {
      headers["X-Youtube-Client-Name"] = String(client.clientId);
      headers["X-Youtube-Client-Version"] = String(
        client.client.clientVersion ?? "",
      );
    }
    const visitorData = await this._ensureVisitorData();
    if (visitorData) headers["X-Goog-Visitor-Id"] = visitorData;

    return this.http.postJson(
      `${INNERTUBE_API}?key=${INNERTUBE_KEY}&prettyPrint=false`,
      body,
      { headers },
    );
  }

  _parsePlayer(payload, videoId, clientName) {
    const details = payload.videoDetails || {};
    if (!details || Object.keys(details).length === 0) {
      throw new ExtractionError("la respuesta no incluye videoDetails");
    }

    if (details.isLive) {
      throw new UnsupportedError(
        "No se pueden descargar directos en vivo. Espera a que termine el directo.",
      );
    }

    const length = safeInt(details.lengthSeconds);
    const rawFormats = [
      ...(deepGet(payload, "streamingData.formats") || []),
      ...(deepGet(payload, "streamingData.adaptiveFormats") || []),
    ];

    const formats = [];
    const seenItags = new Set();
    for (const raw of rawFormats) {
      if (!raw || typeof raw !== "object") continue;
      const format = parseFormat(raw, clientName, length);
      if (format === null || seenItags.has(format.itag)) continue;
      seenItags.add(format.itag);
      formats.push(format);
    }

    if (formats.length === 0) {
      throw new ExtractionError(
        "no hay URLs directas utilizables (puede que YouTube esté " +
          "forzando streaming SABR para este video)",
      );
    }

    const microformat =
      deepGet(payload, "microformat.playerMicroformatRenderer") || {};
    const published =
      microformat.publishDate || microformat.uploadDate || "";
    const uploadDate = published ? published.slice(0, 10).replace(/-/g, "") : "";

    let thumbnails = deepGet(details, "thumbnail.thumbnails") || [];
    if (!Array.isArray(thumbnails)) thumbnails = [];

    const subtitles = [];
    const tracks =
      deepGet(
        payload,
        "captions.playerCaptionsTracklistRenderer.captionTracks",
      ) || [];
    for (const track of tracks) {
      if (!track || typeof track !== "object") continue;
      const baseUrl = track.baseUrl || track.base_url;
      const language = track.languageCode || track.lang;
      if (!baseUrl || !language) continue;
      const kind = track.kind ?? null;
      subtitles.push({
        language_code: String(language),
        name: textOf(track.name) || String(language),
        base_url: String(baseUrl),
        kind,
        is_auto: kind === "asr",
      });
    }

    return {
      id: videoId,
      title: textOf(details.title) || videoId,
      author: textOf(details.author) || "",
      channel_id: textOf(details.channelId) || "",
      length_seconds: length,
      view_count: safeInt(details.viewCount),
      description: textOf(details.shortDescription) || "",
      keywords: Array.isArray(details.keywords) ? [...details.keywords] : [],
      thumbnails,
      upload_date: uploadDate,
      is_live: Boolean(details.isLive),
      default_audio_language: details.defaultAudioLanguage ?? null,
      formats,
      subtitles,
      source_client: clientName,
      webpage_url: `https://www.youtube.com/watch?v=${videoId}`,
    };
  }
}

function extractUrl(raw) {
  const direct = raw.url;
  if (direct) return String(direct);

  const cipher = raw.signatureCipher || raw.cipher;
  if (!cipher) return null;
  const params = new URLSearchParams(String(cipher));
  const url = params.get("url");
  if (!url) return null;
  // Si la firma viene aparte (parámetro s) haría falta descifrarla con el
  // player JS. Los clientes móviles devuelven la URL completa.
  if (params.get("s")) return null;
  return url;
}

function parseFormat(raw, clientName, duration) {
  const url = extractUrl(raw);
  if (!url) return null;

  const mimeFull = String(raw.mimeType || "");
  const mimeType = mimeFull.split(";", 1)[0].trim().toLowerCase();
  const codecsMatch = /codecs="([^"]+)"/.exec(mimeFull);
  const codecs = codecsMatch ? codecsMatch[1] : "";
  const parts = codecs
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

  let vcodec = null;
  let acodec = null;
  if (mimeType.startsWith("audio/")) {
    acodec = parts.length > 0 ? parts[0] : "unknown";
  } else if (parts.length > 0) {
    if (parts.length >= 2) {
      vcodec = parts[0];
      acodec = parts[1];
    } else {
      const token = parts[0].toLowerCase();
      if (AUDIO_CODEC_PREFIXES.some((prefix) => token.startsWith(prefix))) {
        acodec = parts[0];
      } else {
        vcodec = parts[0];
      }
    }
  }

  let qualityLabel = raw.qualityLabel ?? null;
  let audioQuality = raw.audioQuality ?? null;
  if (
    typeof audioQuality === "string" &&
    audioQuality.startsWith("AUDIO_QUALITY_")
  ) {
    audioQuality = audioQuality.slice("AUDIO_QUALITY_".length).toLowerCase();
  }

  const hasVideo = Boolean(
    mimeType.startsWith("video/") ||
      qualityLabel ||
      raw.width ||
      raw.height,
  );
  const hasAudio = Boolean(
    mimeType.startsWith("audio/") ||
      audioQuality ||
      raw.audioBitrate ||
      acodec,
  );
  if (!hasVideo && !hasAudio) return null;
  const isProgressive = hasVideo && hasAudio;

  let height = safeInt(raw.height);
  if (!height && qualityLabel) {
    const match = /(\d{2,5})p/.exec(String(qualityLabel));
    if (match) height = Number.parseInt(match[1], 10);
  }
  let fps = safeInt(raw.fps);
  if (!fps && qualityLabel) {
    const match = /p(\d{2,3})/.exec(String(qualityLabel));
    if (match) fps = Number.parseInt(match[1], 10);
  }

  const bitrate = safeFloat(raw.bitrate) || null;
  const audioBitrate =
    safeFloat(raw.audioBitrate) ||
    (hasAudio && !hasVideo ? bitrate : null);
  const filesize = safeInt(raw.contentLength) || null;

  let ext = MIME_EXT[mimeType];
  if (!ext) ext = mimeType.includes("/") ? mimeType.split("/").pop() : "bin";

  return {
    itag: safeInt(raw.itag),
    url,
    mime_type: mimeType,
    ext,
    vcodec,
    acodec,
    width: safeInt(raw.width) || null,
    height: height || null,
    fps: fps || null,
    bitrate,
    audio_bitrate: audioBitrate,
    quality_label: qualityLabel ? String(qualityLabel) : null,
    audio_quality: audioQuality ? String(audioQuality) : null,
    filesize,
    duration: duration ? Number(duration) : null,
    has_video: hasVideo,
    has_audio: hasAudio,
    is_progressive: isProgressive,
    source_client: clientName,
    language: raw.language ?? null,
    note: raw.quality ? String(raw.quality) : null,
  };
}

module.exports = {
  INNERTUBE_API,
  INNERTUBE_KEY,
  CLIENTS,
  InnertubeClient,
  formatResolution,
  formatSizeEstimate,
  formatKind,
  formatCodecSummary,
  videoInfoToDict,
  extractUrl,
  parseFormat,
};

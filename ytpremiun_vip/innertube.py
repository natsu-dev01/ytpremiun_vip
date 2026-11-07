"""Extracción de videos de YouTube mediante la API InnerTube (sin yt-dlp)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any
from urllib.parse import parse_qs

from .errors import ExtractionError, NetworkError, UnsupportedError
from .http import DEFAULT_USER_AGENT, HttpClient
from .utils import deep_get, safe_float, safe_int, text_of


INNERTUBE_API = "https://www.youtube.com/youtubei/v1/player"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

_VISIONOS_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15"
)

_VISITOR_DATA_RE = re.compile(r'"VISITOR_DATA"\s*:\s*"([^"]+)"')

_MIME_EXT = {
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
}

_AUDIO_CODEC_PREFIXES = (
    "mp4a",
    "opus",
    "vorbis",
    "ac-3",
    "ec-3",
    "flac",
    "pcm",
    "mp3",
)


@dataclass(frozen=True)
class ClientConfig:
    name: str
    client: dict[str, Any]
    user_agent: str
    # Valor de X-Youtube-Client-Name que usa InnerTube para este cliente.
    client_id: int | None = None


CLIENTS: tuple[ClientConfig, ...] = (
    # visionOS es el cliente que YouTube sigue sirviendo con URLs directas
    # descargables. Desde mediados de 2026 los clientes móviles clásicos
    # (android/ios) entregan enlaces que solo permiten el primer MiB y luego
    # responden HTTP 403, así que visionOS va primero.
    ClientConfig(
        name="visionos",
        client={
            "clientName": "VISIONOS",
            "clientVersion": "1.02",
            "deviceMake": "Apple",
            "deviceModel": "RealityDevice17,1",
            "userAgent": _VISIONOS_USER_AGENT,
            "osName": "visionOS",
            "osVersion": "26.5.23O471",
            "hl": "en",
            "timeZone": "UTC",
            "utcOffsetMinutes": 0,
        },
        user_agent=_VISIONOS_USER_AGENT,
        client_id=101,
    ),
    ClientConfig(
        name="android",
        client={
            "clientName": "ANDROID",
            "clientVersion": "20.10.38",
            "androidSdkVersion": 30,
            "osName": "Android",
            "osVersion": "11",
            "hl": "en",
        },
        user_agent=(
            "com.google.android.youtube/20.10.38 "
            "(Linux; U; Android 11) gzip"
        ),
        client_id=3,
    ),
    ClientConfig(
        name="ios",
        client={
            "clientName": "IOS",
            "clientVersion": "20.10.4",
            "deviceModel": "iPhone16,2",
            "osName": "iPhone",
            "osVersion": "18.3.2.22D82",
            "hl": "en",
        },
        user_agent=(
            "com.google.ios.youtube/20.10.4 "
            "(iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"
        ),
        client_id=5,
    ),
    ClientConfig(
        name="android_vr",
        client={
            "clientName": "ANDROID_VR",
            "clientVersion": "1.62.27",
            "deviceMake": "Oculus",
            "deviceModel": "Quest 3",
            "androidSdkVersion": 32,
            "osName": "Android",
            "osVersion": "12",
            "hl": "en",
        },
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.62.27 "
            "(Linux; U; Android 12; GB) gzip"
        ),
        client_id=28,
    ),
)


@dataclass
class Format:
    itag: int
    url: str
    mime_type: str
    ext: str
    vcodec: str | None
    acodec: str | None
    width: int | None
    height: int | None
    fps: int | None
    bitrate: float | None
    audio_bitrate: float | None
    quality_label: str | None
    audio_quality: str | None
    filesize: int | None
    duration: float | None
    has_video: bool
    has_audio: bool
    is_progressive: bool
    source_client: str
    language: str | None = None
    note: str | None = None

    @property
    def resolution(self) -> str:
        if self.has_video and self.height:
            suffix = str(self.fps) if self.fps and self.fps >= 50 else ""
            return f"{self.height}p{suffix}"
        if self.has_video:
            return self.quality_label or "video"
        return "audio"

    @property
    def size_estimate(self) -> int | None:
        if self.filesize:
            return self.filesize
        if self.bitrate and self.duration:
            return int(self.bitrate * self.duration / 8)
        return None

    @property
    def codec_summary(self) -> str:
        video = self.vcodec or "-"
        audio = self.acodec or "-"
        if not self.has_video:
            return audio
        if not self.has_audio:
            return video
        return f"{video} / {audio}"

    @property
    def kind(self) -> str:
        if self.has_video and self.has_audio:
            return "video+audio"
        if self.has_video:
            return "video"
        return "audio"


@dataclass
class CaptionTrack:
    language_code: str
    name: str
    base_url: str
    kind: str | None = None
    is_auto: bool = False


@dataclass
class VideoInfo:
    id: str
    title: str
    author: str
    channel_id: str
    length_seconds: int
    view_count: int
    description: str
    keywords: list[str]
    thumbnails: list[dict[str, Any]]
    upload_date: str
    is_live: bool
    default_audio_language: str | None
    formats: list[Format] = field(default_factory=list)
    subtitles: list[CaptionTrack] = field(default_factory=list)
    source_client: str = ""
    webpage_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["webpage_url"] = self.webpage_url or f"https://www.youtube.com/watch?v={self.id}"
        return data


class InnertubeClient:
    def __init__(self, http: HttpClient, *, verbose: bool = False) -> None:
        self.http = http
        self.verbose = verbose
        self._visitor_data: str | None = None
        self._visitor_loaded = False

    def _ensure_visitor_data(self) -> str | None:
        """Obtiene el visitorData de la sesión (necesario para visionOS).

        YouTube liga el cliente visionOS a la cookie VISITOR_INFO1_LIVE. Un
        primer GET a la portada crea esa cookie y deja el identificador en
        ytcfg. Sin él, el cliente responde ``LOGIN_REQUIRED``.
        """
        if self._visitor_loaded:
            return self._visitor_data
        self._visitor_loaded = True
        try:
            page = self.http.get_text(
                "https://www.youtube.com/",
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
        except NetworkError:
            return None
        match = _VISITOR_DATA_RE.search(page)
        if match:
            self._visitor_data = match.group(1)
        return self._visitor_data

    def get_video(self, video_id: str) -> VideoInfo:
        errors: list[str] = []
        for client in CLIENTS:
            try:
                payload = self._player(video_id, client)
            except NetworkError as exc:
                errors.append(f"{client.name}: {exc}")
                continue

            status = deep_get(payload, "playabilityStatus.status")
            if status != "OK":
                reason = deep_get(payload, "playabilityStatus.reason") or status or "desconocido"
                errors.append(f"{client.name}: {status} ({reason})")
                continue

            try:
                info = self._parse_player(payload, video_id, client.name)
            except UnsupportedError:
                raise
            except ExtractionError as exc:
                errors.append(f"{client.name}: {exc}")
                continue

            if info.formats:
                return info
            errors.append(f"{client.name}: no devolvió formatos descargables")

        detail = "; ".join(errors) if errors else "respuesta vacía"
        hint = ""
        joined = detail.lower()
        if "login_required" in joined or "bot" in joined or "sign in" in joined:
            hint = (
                " YouTube pidió iniciar sesión (o detectó un bot). "
                "Prueba a pasar cookies con --cookies cookies.txt."
            )
        raise ExtractionError(
            f"No se pudo extraer el video {video_id}: {detail}.{hint}"
        )

    def _player(self, video_id: str, client: ClientConfig) -> dict[str, Any]:
        body = {
            "context": {"client": dict(client.client)},
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": client.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Origin": "https://www.youtube.com",
            "Referer": f"https://www.youtube.com/watch?v={video_id}",
        }
        if client.client_id is not None:
            headers["X-Youtube-Client-Name"] = str(client.client_id)
            headers["X-Youtube-Client-Version"] = str(
                client.client.get("clientVersion", "")
            )
        visitor_data = self._ensure_visitor_data()
        if visitor_data:
            headers["X-Goog-Visitor-Id"] = visitor_data
        return self.http.post_json(
            f"{INNERTUBE_API}?key={INNERTUBE_KEY}&prettyPrint=false",
            body,
            headers=headers,
        )

    def _parse_player(
        self,
        payload: dict[str, Any],
        video_id: str,
        client_name: str,
    ) -> VideoInfo:
        details = payload.get("videoDetails") or {}
        if not details:
            raise ExtractionError("la respuesta no incluye videoDetails")

        if details.get("isLive"):
            raise UnsupportedError(
                "No se pueden descargar directos en vivo. Espera a que termine el directo."
            )

        length = safe_int(details.get("lengthSeconds"))
        raw_formats = list(deep_get(payload, "streamingData.formats") or [])
        raw_formats += list(deep_get(payload, "streamingData.adaptiveFormats") or [])

        formats: list[Format] = []
        seen_itags: set[int] = set()
        for raw in raw_formats:
            if not isinstance(raw, dict):
                continue
            fmt = _parse_format(raw, client_name, length)
            if fmt is None or fmt.itag in seen_itags:
                continue
            seen_itags.add(fmt.itag)
            formats.append(fmt)

        if not formats:
            raise ExtractionError(
                "no hay URLs directas utilizables (puede que YouTube esté "
                "forzando streaming SABR para este video)"
            )

        microformat = deep_get(payload, "microformat.playerMicroformatRenderer") or {}
        published = (
            microformat.get("publishDate")
            or microformat.get("uploadDate")
            or ""
        )
        upload_date = published[:10].replace("-", "") if published else ""

        thumbnails = deep_get(details, "thumbnail.thumbnails") or []
        if not isinstance(thumbnails, list):
            thumbnails = []

        subtitles: list[CaptionTrack] = []
        for track in deep_get(
            payload,
            "captions.playerCaptionsTracklistRenderer.captionTracks",
        ) or []:
            if not isinstance(track, dict):
                continue
            base_url = track.get("baseUrl") or track.get("base_url")
            language = track.get("languageCode") or track.get("lang")
            if not base_url or not language:
                continue
            kind = track.get("kind")
            subtitles.append(
                CaptionTrack(
                    language_code=str(language),
                    name=text_of(track.get("name")) or str(language),
                    base_url=str(base_url),
                    kind=kind,
                    is_auto=kind == "asr",
                )
            )

        info = VideoInfo(
            id=video_id,
            title=text_of(details.get("title")) or video_id,
            author=text_of(details.get("author")) or "",
            channel_id=text_of(details.get("channelId")) or "",
            length_seconds=length,
            view_count=safe_int(details.get("viewCount")),
            description=text_of(details.get("shortDescription")) or "",
            keywords=list(details.get("keywords") or []),
            thumbnails=thumbnails,
            upload_date=upload_date,
            is_live=bool(details.get("isLive")),
            default_audio_language=details.get("defaultAudioLanguage"),
            formats=formats,
            subtitles=subtitles,
            source_client=client_name,
            webpage_url=f"https://www.youtube.com/watch?v={video_id}",
        )
        return info


def _extract_url(raw: dict[str, Any]) -> str | None:
    direct = raw.get("url")
    if direct:
        return str(direct)

    cipher = raw.get("signatureCipher") or raw.get("cipher")
    if not cipher:
        return None
    params = parse_qs(str(cipher))
    urls = params.get("url")
    if not urls:
        return None
    # Si la firma viene aparte (parámetro s) haría falta descifrarla con el
    # player JS. Los clientes ANDROID/IOS devuelven la URL completa, así que
    # aquí solo aceptamos cifrados que ya la incluyen.
    if params.get("s") and params.get("s", [""])[0]:
        return None
    return urls[0]


def _parse_format(
    raw: dict[str, Any],
    client_name: str,
    duration: int,
) -> Format | None:
    url = _extract_url(raw)
    if not url:
        return None

    mime_full = str(raw.get("mimeType") or "")
    mime_type = mime_full.split(";", 1)[0].strip().lower()
    codecs_match = re.search(r'codecs="([^"]+)"', mime_full)
    codecs = codecs_match.group(1) if codecs_match else ""
    parts = [part.strip() for part in codecs.split(",") if part.strip()]

    vcodec: str | None = None
    acodec: str | None = None
    if mime_type.startswith("audio/"):
        acodec = parts[0] if parts else "unknown"
    elif parts:
        if len(parts) >= 2:
            vcodec, acodec = parts[0], parts[1]
        else:
            token = parts[0].lower()
            if token.startswith(_AUDIO_CODEC_PREFIXES):
                acodec = parts[0]
            else:
                vcodec = parts[0]

    quality_label = raw.get("qualityLabel")
    audio_quality = raw.get("audioQuality")
    if isinstance(audio_quality, str) and audio_quality.startswith("AUDIO_QUALITY_"):
        audio_quality = audio_quality[len("AUDIO_QUALITY_") :].lower()

    has_video = bool(
        mime_type.startswith("video/")
        or quality_label
        or raw.get("width")
        or raw.get("height")
    )
    has_audio = bool(
        mime_type.startswith("audio/")
        or audio_quality
        or raw.get("audioBitrate")
        or acodec
    )
    if not has_video and not has_audio:
        return None
    is_progressive = has_video and has_audio

    height = safe_int(raw.get("height"))
    if not height and quality_label:
        match = re.search(r"(\d{2,5})p", str(quality_label))
        if match:
            height = int(match.group(1))
    fps = safe_int(raw.get("fps"))
    if not fps and quality_label:
        match = re.search(r"p(\d{2,3})", str(quality_label))
        if match:
            fps = int(match.group(1))

    bitrate = safe_float(raw.get("bitrate")) or None
    audio_bitrate = safe_float(raw.get("audioBitrate")) or (
        bitrate if has_audio and not has_video else None
    )
    filesize = safe_int(raw.get("contentLength")) or None
    ext = _MIME_EXT.get(mime_type)
    if not ext:
        ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"

    return Format(
        itag=safe_int(raw.get("itag")),
        url=url,
        mime_type=mime_type,
        ext=ext,
        vcodec=vcodec,
        acodec=acodec,
        width=safe_int(raw.get("width")) or None,
        height=height or None,
        fps=fps or None,
        bitrate=bitrate,
        audio_bitrate=audio_bitrate,
        quality_label=str(quality_label) if quality_label else None,
        audio_quality=str(audio_quality) if audio_quality else None,
        filesize=filesize,
        duration=float(duration) if duration else None,
        has_video=has_video,
        has_audio=has_audio,
        is_progressive=is_progressive,
        source_client=client_name,
        language=raw.get("language"),
        note=str(raw.get("quality") or "") or None,
    )

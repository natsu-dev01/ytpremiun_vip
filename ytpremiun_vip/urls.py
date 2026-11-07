"""Interpretación de URLs e identificadores de YouTube."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ALLOWED_HOSTS = {
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "youtube.googleapis.com",
}


@dataclass(frozen=True)
class ParsedInput:
    raw: str
    video_id: str | None = None
    playlist_id: str | None = None

    @property
    def is_video(self) -> bool:
        return bool(self.video_id)

    @property
    def is_playlist(self) -> bool:
        return bool(self.playlist_id)


def is_video_id(value: str | None) -> bool:
    return bool(value and _VIDEO_ID_RE.match(value))


def _clean_host(host: str) -> str:
    host = host.lower().strip(".")
    for prefix in ("www.", "m.", "music."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def parse_input(text: str) -> ParsedInput:
    """Acepta IDs, youtu.be, /watch, /shorts, /embed, /live y playlists."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("La URL está vacía")

    if _VIDEO_ID_RE.match(raw):
        return ParsedInput(raw=raw, video_id=raw)

    candidate = raw if "://" in raw else "https://" + raw
    parsed = urlparse(candidate)
    host = _clean_host(parsed.hostname or "")
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"No es una URL de YouTube: {raw}")

    query = parse_qs(parsed.query)
    playlist_id = (query.get("list") or [None])[0]
    video_id: str | None = None

    if host == "youtu.be":
        first = parsed.path.strip("/").split("/")[0]
        if is_video_id(first):
            video_id = first
    else:
        video_id = (query.get("v") or [None])[0]
        if not is_video_id(video_id):
            video_id = None
        if video_id is None:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"}:
                if is_video_id(parts[1]):
                    video_id = parts[1]

    if playlist_id is not None and not playlist_id.strip():
        playlist_id = None
    if playlist_id is not None:
        playlist_id = playlist_id.strip()

    if video_id is None and playlist_id is None:
        raise ValueError(f"No se encontró un video ni una playlist en: {raw}")

    return ParsedInput(raw=raw, video_id=video_id, playlist_id=playlist_id)


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"

"""Lectura de listas de reproducción de YouTube."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote
from typing import Any, Iterator

from .errors import ExtractionError, NetworkError
from .http import DEFAULT_USER_AGENT, HttpClient
from .urls import is_video_id, playlist_url
from .utils import deep_get, extract_json_after, text_of


BROWSE_API = "https://www.youtube.com/youtubei/v1/browse"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

_WEB_CLIENT = {
    "clientName": "WEB",
    "clientVersion": "2.20250101.00.00",
    "hl": "en",
    "gl": "US",
}


@dataclass
class PlaylistEntry:
    video_id: str
    title: str
    index: int
    url: str


@dataclass
class PlaylistInfo:
    id: str
    title: str
    entries: list[PlaylistEntry] = field(default_factory=list)
    warning: str | None = None


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _lockup_title(lockup: dict[str, Any]) -> str:
    for path in (
        "metadata.lockupMetadataViewModel.title.content",
        "metadata.lockupMetadataViewModel.title.simpleText",
        "metadata.lockupMetadataViewModel.title.runs",
    ):
        value = deep_get(lockup, path)
        text = text_of(value)
        if text:
            return text
    return ""


def _playlist_title(data: dict[str, Any]) -> str:
    candidates = (
        "metadata.playlistMetadataRenderer.title",
        "header.playlistHeaderRenderer.title",
        "header.pageHeaderViewModel.title.content",
        "sidebar.playlistSidebarRenderer.items.0.playlistSidebarPrimaryInfoRenderer.title",
    )
    for path in candidates:
        text = text_of(deep_get(data, path))
        if text:
            return text
    return ""


def _collect_entries(data: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for node in _walk(data):
        lockup = node.get("lockupViewModel")
        if isinstance(lockup, dict):
            video_id = lockup.get("contentId")
            if is_video_id(video_id):
                found.append((video_id, _lockup_title(lockup)))
            continue
        renderer = node.get("playlistVideoRenderer")
        if isinstance(renderer, dict):
            video_id = renderer.get("videoId")
            if is_video_id(video_id):
                found.append((video_id, text_of(renderer.get("title"))))
    return found


def _find_continuation(data: Any) -> str | None:
    for node in _walk(data):
        item = node.get("continuationItemRenderer")
        if isinstance(item, dict):
            token = deep_get(
                item,
                "continuationEndpoint.continuationCommand.token",
            )
            if token:
                return str(token)

    tokens: list[str] = []
    for node in _walk(data):
        command = node.get("continuationCommand")
        if isinstance(command, dict) and command.get("token"):
            tokens.append(str(command["token"]))
    return tokens[-1] if tokens else None


class PlaylistClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch(self, playlist_id: str, *, max_items: int | None = None) -> PlaylistInfo:
        url = f"{playlist_url(playlist_id)}&hl=en&gl=US"
        try:
            html = self.http.get_text(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except NetworkError as exc:
            raise ExtractionError(
                f"No se pudo abrir la playlist {playlist_id}: {exc}"
            ) from exc

        data = extract_json_after(html, "ytInitialData")
        if not isinstance(data, dict):
            raise ExtractionError(
                f"No se pudo leer la playlist {playlist_id}. "
                "Puede ser privada, inexistente o requerir inicio de sesión."
            )

        title = _playlist_title(data) or playlist_id
        entries: list[PlaylistEntry] = []
        seen: set[str] = set()
        warning: str | None = None

        def append(found: list[tuple[str, str]]) -> None:
            for video_id, entry_title in found:
                if video_id in seen:
                    continue
                seen.add(video_id)
                entries.append(
                    PlaylistEntry(
                        video_id=video_id,
                        title=entry_title or video_id,
                        index=len(entries) + 1,
                        url=f"https://www.youtube.com/watch?v={video_id}",
                    )
                )

        append(_collect_entries(data))
        token = _find_continuation(data)
        pages = 0
        while token and (max_items is None or len(entries) < max_items) and pages < 100:
            try:
                continuation_data = self._browse(token)
            except NetworkError as exc:
                warning = f"No se pudo continuar la playlist: {exc}"
                break
            append(_collect_entries(continuation_data))
            token = _find_continuation(continuation_data)
            pages += 1

        if max_items is not None:
            entries = entries[:max_items]

        if not entries:
            raise ExtractionError(
                f"La playlist {playlist_id} está vacía o no es accesible."
            )

        return PlaylistInfo(
            id=playlist_id,
            title=title,
            entries=entries,
            warning=warning,
        )

    def _browse(self, token: str) -> dict[str, Any]:
        body = {
            "context": {"client": dict(_WEB_CLIENT)},
            "continuation": token,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
            "Origin": "https://www.youtube.com",
            "Referer": "https://www.youtube.com/",
        }
        return self.http.post_json(
            f"{BROWSE_API}?key={INNERTUBE_KEY}&prettyPrint=false",
            body,
            headers=headers,
        )

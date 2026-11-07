"""Descarga y conversión de subtítulos de YouTube."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http import HttpClient
from .innertube import CaptionTrack
from .utils import safe_float


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_json3(payload: dict[str, Any]) -> list[Cue]:
    cues: list[Cue] = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        start = safe_float(event.get("tStartMs")) / 1000.0
        duration = safe_float(event.get("dDurationMs")) / 1000.0
        text = "".join(
            str(segment.get("utf8", ""))
            for segment in (event.get("segs") or [])
            if isinstance(segment, dict)
        )
        text = _clean_text(text)
        if not text:
            continue
        cues.append(Cue(start=start, end=start + duration, text=text))
    return cues


def _parse_srt_like(payload: str) -> list[Cue]:
    cues: list[Cue] = []
    time_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
    )
    blocks = re.split(r"\r?\n\r?\n", payload.strip())
    for block in blocks:
        lines = block.splitlines()
        match = None
        time_index = -1
        for index, line in enumerate(lines):
            match = time_re.search(line)
            if match:
                time_index = index
                break
        if not match:
            continue
        start = (
            int(match.group(1)) * 3600
            + int(match.group(2)) * 60
            + int(match.group(3))
            + int(match.group(4).ljust(3, "0")) / 1000.0
        )
        end = (
            int(match.group(5)) * 3600
            + int(match.group(6)) * 60
            + int(match.group(7))
            + int(match.group(8).ljust(3, "0")) / 1000.0
        )
        text = _clean_text("\n".join(lines[time_index + 1 :]))
        if text:
            cues.append(Cue(start=start, end=end, text=text))
    return cues


def parse_timedtext(payload: str) -> list[Cue]:
    """Convierte XML timedtext, JSON3 o VTT/SRT a una lista de cues."""
    if not payload or not payload.strip():
        return []

    stripped = payload.lstrip()
    if stripped.startswith("{"):
        try:
            return _parse_json3(json.loads(payload))
        except (ValueError, TypeError):
            return []

    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return _parse_srt_like(payload)

    cues: list[Cue] = []
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if tag == "p" and element.get("t") is not None:
            start = safe_float(element.get("t")) / 1000.0
            duration = safe_float(element.get("d")) / 1000.0
            text = _clean_text("".join(element.itertext()))
            if text:
                cues.append(Cue(start=start, end=start + duration, text=text))
        elif tag == "text" and element.get("start") is not None:
            start = safe_float(element.get("start"))
            duration = safe_float(element.get("dur"))
            text = _clean_text("".join(element.itertext()))
            if text:
                cues.append(Cue(start=start, end=start + duration, text=text))
    return cues


def _srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _vtt_time(seconds: float) -> str:
    return _srt_time(seconds).replace(",", ".")


def cues_to_srt(cues: list[Cue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def cues_to_vtt(cues: list[Cue]) -> str:
    blocks = ["WEBVTT", ""]
    for cue in cues:
        blocks.append(
            f"{_vtt_time(cue.start)} --> {_vtt_time(cue.end)}\n{cue.text}\n"
        )
    return "\n".join(blocks)


def _language_matches(code: str, wanted: str) -> bool:
    code = (code or "").lower()
    wanted = (wanted or "").lower()
    if not code or not wanted:
        return False
    if code == wanted:
        return True
    code_base = code.split("-")[0]
    wanted_base = wanted.split("-")[0]
    return (
        code_base == wanted_base
        or code.startswith(wanted + "-")
        or wanted.startswith(code + "-")
    )


def select_tracks(
    tracks: list[CaptionTrack],
    langs: str | None,
    include_auto: bool,
    default_language: str | None,
) -> list[CaptionTrack]:
    if not tracks:
        return []

    if langs and langs.strip():
        if langs.strip().lower() == "all":
            wanted: list[str] | None = None
        else:
            wanted = [part.strip() for part in langs.split(",") if part.strip()]
    else:
        fallback = default_language or tracks[0].language_code
        wanted = [fallback]

    selected: list[CaptionTrack] = []
    seen: set[tuple[str, bool]] = set()
    for track in tracks:
        if track.is_auto and not include_auto:
            continue
        if wanted is not None and not any(
            _language_matches(track.language_code, language) for language in wanted
        ):
            continue
        key = (track.language_code, track.is_auto)
        if key in seen:
            continue
        seen.add(key)
        selected.append(track)

    # Si no hay pista manual para el idioma pedido, usa la automática.
    if not selected and include_auto:
        for track in tracks:
            if wanted is not None and not any(
                _language_matches(track.language_code, language) for language in wanted
            ):
                continue
            selected.append(track)
            break
    return selected


def subtitle_path(base: Path, track: CaptionTrack, fmt: str) -> Path:
    suffix = f".{track.language_code}"
    if track.is_auto:
        suffix += ".auto"
    return base.with_name(base.name + suffix + "." + fmt)


def download_subtitle(
    track: CaptionTrack,
    http: HttpClient,
    base: Path,
    fmt: str,
    *,
    force: bool = False,
) -> Path | None:
    destination = subtitle_path(base, track, fmt)
    if destination.exists() and not force:
        return destination

    payload = http.get_bytes(
        track.base_url,
        headers={
            "Referer": "https://www.youtube.com/",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    text = payload.decode("utf-8", errors="replace")

    if fmt == "xml":
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    cues = parse_timedtext(text)
    if not cues:
        return None

    content = cues_to_srt(cues) if fmt == "srt" else cues_to_vtt(cues)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination

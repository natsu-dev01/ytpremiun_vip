"""Utilidades generales: nombres de archivo, plantillas, índices y formato."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TEMPLATE_RE = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)(?:(\d+)([dsif])|([dsif]))?")
_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kmgt]?)i?b?\s*$", re.I)


def human_bytes(num: float | int | None) -> str:
    """Convierte bytes a una cadena legible (KiB, MiB...)."""
    if num is None:
        return "?"
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(value) or value < 0:
        return "?"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f} {units[index]}"


def human_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "?"
    return f"{human_bytes(bytes_per_second)}/s"


def human_duration(seconds: float | int | None) -> str:
    """Formatea segundos como HH:MM:SS o MM:SS."""
    if seconds is None:
        return "?"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "?"
    if total < 0:
        return "?"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def human_eta(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0 or seconds > 86400 * 10:
        return "--:--"
    return human_duration(seconds)


def parse_size(text: str) -> int | None:
    """Convierte '1.5M', '20 MiB' o '1024' a bytes."""
    match = _SIZE_RE.match(text or "")
    if not match:
        return None
    value = float(match.group(1))
    multiplier = {
        "": 1,
        "k": 1024,
        "m": 1024 ** 2,
        "g": 1024 ** 3,
        "t": 1024 ** 4,
    }[match.group(2).lower()]
    return int(value * multiplier)


def sanitize_filename(
    name: str,
    *,
    restrict: bool = False,
    max_length: int = 180,
) -> str:
    """Limpia un nombre para que sea válido en Windows, macOS y Linux."""
    if name is None:
        return "download"
    text = str(name)
    if restrict:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
    text = _ILLEGAL_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .")
    if not text:
        text = "download"

    stem = text.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        text = "_" + text

    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    return text or "download"


def format_template(template: str, fields: Mapping[str, Any]) -> str:
    """Expande plantillas tipo yt-dlp: %(title)s, %(playlist_index)03d..."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = fields.get(key)
        if value is None:
            return ""
        width = match.group(2)
        conv = match.group(3) or match.group(4)

        if conv in ("d", "i"):
            try:
                number = int(value)
            except (TypeError, ValueError):
                return str(value)
            if width:
                return f"{number:0{int(width)}d}"
            return str(number)
        if conv == "f":
            try:
                precision = int(width) if width else 2
                return f"{float(value):.{precision}f}"
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    return _TEMPLATE_RE.sub(replace, template)


def build_output_path(
    template: str,
    fields: Mapping[str, Any],
    base_dir: str | Path,
    *,
    restrict: bool = False,
    max_filename: int = 180,
) -> Path:
    """Construye una ruta segura a partir de la plantilla y los metadatos."""
    safe_fields: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str):
            safe_fields[key] = sanitize_filename(
                value, restrict=restrict, max_length=max_filename
            )
        else:
            safe_fields[key] = value

    rendered = format_template(template, safe_fields).replace("\\", "/")
    parts: list[str] = []
    for part in rendered.split("/"):
        part = part.strip()
        if not part or part == ".":
            continue
        if part == "..":
            part = "_"
        parts.append(
            sanitize_filename(part, restrict=restrict, max_length=max_filename)
        )
    if not parts:
        parts = ["download"]
    return Path(base_dir, *parts)


def parse_index_spec(spec: str | None) -> Callable[[int], bool] | None:
    """Devuelve un predicado para '--playlist-items' (1-3,7,10-)."""
    if not spec or not spec.strip():
        return None

    ranges: list[tuple[int, int | None]] = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text) if start_text.strip() else 1
            end = int(end_text) if end_text.strip() else None
            if start <= 0:
                start = 1
            if end is not None and end < start:
                start, end = end, start
            ranges.append((start, end))
        else:
            number = int(part)
            if number > 0:
                ranges.append((number, number))

    if not ranges:
        return None

    def contains(index: int) -> bool:
        return any(
            start <= index and (end is None or index <= end)
            for start, end in ranges
        )

    return contains


def read_batch_file(path: str | Path) -> list[str]:
    """Lee un archivo de URLs (una por línea, # como comentario)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def extract_json_after(text: str, marker: str) -> Any | None:
    """Extrae el primer objeto JSON que aparece después de un marcador."""
    index = text.find(marker)
    if index < 0:
        return None
    start = text.find("{", index)
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value
    except json.JSONDecodeError:
        return None


def deep_get(obj: Any, path: str, default: Any = None) -> Any:
    """Accede a un valor anidado con una ruta 'a.b.0.c'."""
    current = obj
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
        if current is None:
            return default
    return current


def text_of(value: Any) -> str:
    """Extrae texto de las estructuras típicas de YouTube."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        simple = value.get("simpleText")
        if isinstance(simple, str):
            return simple
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict))
        content = value.get("content")
        if isinstance(content, str):
            return content
    return ""


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def truncate(text: str, length: int, suffix: str = "...") -> str:
    if len(text) <= length:
        return text
    if length <= len(suffix):
        return text[:length]
    return text[: length - len(suffix)] + suffix

"""Selección de formatos de video/audio y tabla para --list-formats."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ExtractionError
from .innertube import Format
from .utils import human_bytes, parse_size


class _NoMatch(Exception):
    pass


@dataclass
class Selection:
    video: Format | None = None
    audio: Format | None = None
    progressive: Format | None = None

    @property
    def requires_merge(self) -> bool:
        return self.progressive is None and self.video is not None and self.audio is not None

    @property
    def has_video(self) -> bool:
        return self.progressive is not None or self.video is not None

    @property
    def has_audio(self) -> bool:
        return (
            self.progressive is not None
            or self.audio is not None
            or (self.video is not None and self.video.has_audio)
        )

    @property
    def primary(self) -> Format | None:
        return self.progressive or self.video or self.audio


_FILTER_RE = re.compile(
    r"\[([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|!=|\^=|\$=|\*|=|<|>)\s*([^\]]*)\]"
)
_TOKEN_RE = re.compile(r"^([A-Za-z0-9_*!]+)((?:\[[^\]]*\])*)$")

_AUDIO_BASES = {
    "bestaudio", "ba", "bestaudio*", "ba*", "worstaudio", "wa", "worstaudio*", "wa*",
}
_STRICT_AUDIO_BASES = {"bestaudio", "ba", "worstaudio", "wa"}
_VIDEO_BASES = {
    "bestvideo", "bv", "bestvideo*", "bv*", "worstvideo", "wv", "worstvideo*", "wv*",
}
_STRICT_VIDEO_BASES = {"bestvideo", "bv", "worstvideo", "wv"}


def _alternatives(spec: str) -> list[str]:
    return [part.strip() for part in spec.split("/") if part.strip()]


def _parse_token(token: str) -> tuple[str, list[tuple[str, str, str]]]:
    match = _TOKEN_RE.match(token.strip())
    if not match:
        raise _NoMatch(f"formato no válido: {token}")
    base = match.group(1).lower()
    filters = [
        (field.lower(), op, value.strip().strip("'\""))
        for field, op, value in _FILTER_RE.findall(match.group(2))
    ]
    return base, filters


def _actual_value(fmt: Format, field: str):
    if field in ("itag", "format_id", "id"):
        return fmt.itag
    if field == "height":
        return fmt.height
    if field == "width":
        return fmt.width
    if field == "fps":
        return fmt.fps
    if field in ("tbr", "bitrate"):
        return (fmt.bitrate / 1000.0) if fmt.bitrate else None
    if field in ("abr", "audio_bitrate"):
        return (fmt.audio_bitrate / 1000.0) if fmt.audio_bitrate else None
    if field in ("filesize", "filesize_approx", "size"):
        return fmt.size_estimate
    if field == "ext":
        return fmt.ext
    if field == "vcodec":
        return fmt.vcodec or "none"
    if field == "acodec":
        return fmt.acodec or "none"
    if field == "protocol":
        return "https"
    if field == "resolution":
        return fmt.resolution
    if field == "audio_channels":
        return None
    return None


def _filter_matches(fmt: Format, field: str, op: str, value: str) -> bool:
    actual = _actual_value(fmt, field)
    if actual is None:
        return False

    numeric = field in {
        "itag", "format_id", "id", "height", "width", "fps",
        "tbr", "bitrate", "abr", "audio_bitrate",
        "filesize", "filesize_approx", "size",
    }

    if numeric:
        if field in ("filesize", "filesize_approx", "size"):
            wanted = parse_size(value)
            if wanted is None:
                try:
                    wanted = float(value)
                except ValueError:
                    return False
        else:
            try:
                wanted = float(value)
            except ValueError:
                return False
        actual_number = float(actual)
        if op == "<":
            return actual_number < wanted
        if op == "<=":
            return actual_number <= wanted
        if op == ">":
            return actual_number > wanted
        if op == ">=":
            return actual_number >= wanted
        if op == "=":
            return actual_number == wanted
        if op == "!=":
            return actual_number != wanted
        return False

    actual_text = str(actual).lower()
    wanted_text = value.lower()
    if op == "=":
        return actual_text == wanted_text
    if op == "!=":
        return actual_text != wanted_text
    if op == "^=":
        return actual_text.startswith(wanted_text)
    if op == "$=":
        return actual_text.endswith(wanted_text)
    if op == "*=":
        return wanted_text in actual_text
    if op == "<":
        return actual_text < wanted_text
    if op == "<=":
        return actual_text <= wanted_text
    if op == ">":
        return actual_text > wanted_text
    if op == ">=":
        return actual_text >= wanted_text
    return False


def _apply_filters(formats: list[Format], filters: list[tuple[str, str, str]]) -> list[Format]:
    for field, op, value in filters:
        formats = [fmt for fmt in formats if _filter_matches(fmt, field, op, value)]
    return formats


def _video_key(fmt: Format, merge_ext: str):
    ext_pref = 1 if fmt.ext == merge_ext else 0
    avc_pref = 2 if (fmt.vcodec or "").lower().startswith("avc") else 0
    return (
        fmt.height or 0,
        fmt.fps or 0,
        ext_pref,
        avc_pref,
        fmt.bitrate or 0,
        1 if fmt.has_audio else 0,
    )


def _audio_key(fmt: Format, audio_ext_pref: str | None):
    ext_pref = 1 if audio_ext_pref and fmt.ext == audio_ext_pref else 0
    return (
        ext_pref,
        fmt.audio_bitrate or fmt.bitrate or 0,
        fmt.filesize or 0,
    )


def _select_token(
    formats: list[Format],
    token: str,
    *,
    merge_ext: str,
    audio_ext_pref: str | None,
    role: str,
) -> Format | None:
    base, filters = _parse_token(token)

    if base in ("best", "b"):
        pool = [fmt for fmt in formats if fmt.has_video]
        progressive = [fmt for fmt in pool if fmt.has_audio]
        if progressive:
            pool = progressive
        key = lambda fmt: _video_key(fmt, merge_ext)
        reverse = True
    elif base in ("worst", "w"):
        pool = [fmt for fmt in formats if fmt.has_video]
        key = lambda fmt: _video_key(fmt, merge_ext)
        reverse = False
    elif base in _AUDIO_BASES:
        pool = [fmt for fmt in formats if fmt.has_audio]
        if base in _STRICT_AUDIO_BASES:
            pool = [fmt for fmt in pool if not fmt.has_video]
        key = lambda fmt: _audio_key(fmt, audio_ext_pref)
        reverse = not base.startswith("worst")
    elif base in _VIDEO_BASES:
        pool = [fmt for fmt in formats if fmt.has_video]
        if base in _STRICT_VIDEO_BASES:
            pool = [fmt for fmt in pool if not fmt.has_audio]
        key = lambda fmt: _video_key(fmt, merge_ext)
        reverse = not base.startswith("worst")
    elif base.isdigit():
        pool = [fmt for fmt in formats if fmt.itag == int(base)]
        key = lambda fmt: fmt.itag
        reverse = False
    elif base in ("all", "*"):
        pool = list(formats)
        key = lambda fmt: _video_key(fmt, merge_ext)
        reverse = True
    else:
        raise _NoMatch(f"formato desconocido: {token}")

    pool = _apply_filters(pool, filters)
    if role == "video":
        pool = [fmt for fmt in pool if fmt.has_video]
    elif role == "audio":
        pool = [fmt for fmt in pool if fmt.has_audio]
    if not pool:
        return None
    return sorted(pool, key=key, reverse=reverse)[0]


def _select_audio(
    formats: list[Format],
    spec: str,
    audio_ext_pref: str | None,
) -> Format:
    errors: list[str] = []
    for alternative in _alternatives(spec):
        token = alternative.split("+", 1)[0].strip()
        try:
            fmt = _select_token(
                formats,
                token,
                merge_ext="mp4",
                audio_ext_pref=audio_ext_pref,
                role="audio",
            )
        except _NoMatch as exc:
            errors.append(str(exc))
            continue
        if fmt is not None:
            return fmt
        errors.append(f"sin coincidencias para {token}")

    # Último recurso: el mejor audio disponible.
    audio_formats = [fmt for fmt in formats if fmt.has_audio]
    if audio_formats:
        return sorted(
            audio_formats,
            key=lambda fmt: _audio_key(fmt, audio_ext_pref),
            reverse=True,
        )[0]
    raise ExtractionError(
        "No hay ningún formato de audio disponible. " + "; ".join(errors)
    )


def _select_alternative(
    formats: list[Format],
    alternative: str,
    *,
    merge_ext: str,
    audio_ext_pref: str | None,
) -> Selection:
    tokens = [token.strip() for token in alternative.split("+") if token.strip()]
    if not tokens:
        raise _NoMatch("alternativa vacía")
    if len(tokens) > 2:
        raise _NoMatch(f"demasiados '+' en {alternative}")

    if len(tokens) == 2:
        video = _select_token(
            formats, tokens[0], merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="video",
        )
        audio = _select_token(
            formats, tokens[1], merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="audio",
        )
        if video is None or audio is None:
            raise _NoMatch(f"sin coincidencias para {alternative}")
        if video.has_audio:
            return Selection(progressive=video)
        return Selection(video=video, audio=audio)

    token = tokens[0]
    base, _ = _parse_token(token)

    if base in _AUDIO_BASES:
        fmt = _select_token(
            formats, token, merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="audio",
        )
        if fmt is None:
            raise _NoMatch(f"sin coincidencias para {token}")
        return Selection(audio=fmt)

    if base in _VIDEO_BASES or base in ("worst", "w"):
        fmt = _select_token(
            formats, token, merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="video",
        )
        if fmt is None:
            raise _NoMatch(f"sin coincidencias para {token}")
        if fmt.has_video and fmt.has_audio:
            return Selection(progressive=fmt)
        if fmt.has_video:
            return Selection(video=fmt)
        return Selection(audio=fmt)

    if base in ("best", "b"):
        fmt = _select_token(
            formats, token, merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="video",
        )
        if fmt is None:
            raise _NoMatch(f"sin coincidencias para {token}")
        if fmt.has_audio:
            return Selection(progressive=fmt)
        audio = _select_token(
            formats, "bestaudio", merge_ext=merge_ext,
            audio_ext_pref=audio_ext_pref, role="audio",
        )
        return Selection(video=fmt, audio=audio)

    # Itag numérico o "all": decide según el formato encontrado.
    fmt = _select_token(
        formats, token, merge_ext=merge_ext,
        audio_ext_pref=audio_ext_pref, role="any",
    )
    if fmt is None:
        raise _NoMatch(f"sin coincidencias para {token}")
    if fmt.has_video and fmt.has_audio:
        return Selection(progressive=fmt)
    if fmt.has_video:
        return Selection(video=fmt)
    return Selection(audio=fmt)


def select_format(
    formats: list[Format],
    spec: str | None = None,
    *,
    audio_only: bool = False,
    merge_ext: str = "mp4",
    audio_ext_pref: str | None = None,
) -> Selection:
    """Selecciona formatos. Lanza ExtractionError si nada coincide."""
    usable = [fmt for fmt in formats if fmt.url]
    if not usable:
        raise ExtractionError("El video no tiene formatos descargables.")

    if audio_only:
        selected = _select_audio(
            usable,
            spec or "bestaudio/best",
            audio_ext_pref,
        )
        return Selection(audio=selected)

    spec = spec or "bv*+ba/b"
    errors: list[str] = []
    for alternative in _alternatives(spec):
        try:
            selection = _select_alternative(
                usable,
                alternative,
                merge_ext=merge_ext,
                audio_ext_pref=audio_ext_pref,
            )
        except _NoMatch as exc:
            errors.append(str(exc))
            continue
        if selection.primary is not None:
            return selection

    detail = "; ".join(errors) if errors else "ninguna alternativa válida"
    raise ExtractionError(
        f"No se encontró un formato que coincida con '{spec}'. {detail}"
    )


def format_table(formats: list[Format]) -> str:
    video = sorted(
        [fmt for fmt in formats if fmt.has_video],
        key=lambda fmt: (fmt.height or 0, fmt.fps or 0),
    )
    audio = sorted(
        [fmt for fmt in formats if not fmt.has_video and fmt.has_audio],
        key=lambda fmt: fmt.audio_bitrate or fmt.bitrate or 0,
        reverse=True,
    )
    rows = video + audio

    header = (
        f"{'ID':>4}  {'TIPO':<11}  {'EXT':<4}  {'RES':<9}  {'FPS':>3}  "
        f"{'VCODEC':<18}  {'ACODEC':<14}  {'TAMAÑO':>9}  NOTA"
    )
    lines = [header, "-" * len(header)]
    for fmt in rows:
        size = fmt.size_estimate
        lines.append(
            f"{fmt.itag:>4}  {fmt.kind:<11}  {fmt.ext:<4}  {fmt.resolution:<9}  "
            f"{(fmt.fps or 0):>3}  {(fmt.vcodec or '-'):<18}  "
            f"{(fmt.acodec or '-'):<14}  {(human_bytes(size) if size else '?'):>9}  "
            f"{fmt.quality_label or fmt.audio_quality or ''}"
        )
    return "\n".join(lines)

"""Integración con ffmpeg: merge de video+audio, remux y extracción de audio."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import FFmpegNotFoundError, MediaError


def find_ffmpeg() -> str:
    candidates: list[str | None] = [os.environ.get("FFMPEG"), shutil.which("ffmpeg")]
    if os.name == "nt":
        candidates += [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise FFmpegNotFoundError(
        "ffmpeg no está instalado o no está en el PATH. "
        "Instálalo desde https://ffmpeg.org/ y vuelve a intentarlo. "
        "Sin ffmpeg no se pueden unir video+audio ni convertir a MP3."
    )


def ffmpeg_available() -> bool:
    try:
        find_ffmpeg()
        return True
    except FFmpegNotFoundError:
        return False


def _run(command: list[str]) -> None:
    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise MediaError(f"No se pudo ejecutar ffmpeg: {exc}") from exc

    if process.returncode != 0:
        output = (process.stderr or process.stdout or "").strip()
        tail = "\n".join(output.splitlines()[-10:])
        raise MediaError(f"ffmpeg falló:\n{tail}")


def _metadata_args(metadata: dict[str, Any] | None) -> list[str]:
    args: list[str] = []
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        text = str(value).replace("\x00", "").replace("\r", " ").replace("\n", " ")
        text = text.strip()
        if text:
            args += ["-metadata", f"{key}={text}"]
    return args


def _base_command() -> list[str]:
    return [
        find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
    ]


def merge(
    video: str | Path,
    audio: str | Path,
    output: str | Path,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Une una pista de video y otra de audio sin recodificar."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _base_command() + [
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
    ]
    if output_path.suffix.lower() == ".mp4":
        command += ["-movflags", "+faststart"]
    command += _metadata_args(metadata)
    command.append(str(output_path))
    _run(command)


def remux(
    source: str | Path,
    output: str | Path,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Cambia el contenedor sin recodificar."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _base_command() + ["-i", str(source), "-c", "copy"]
    if output_path.suffix.lower() == ".mp4":
        command += ["-movflags", "+faststart"]
    command += _metadata_args(metadata)
    command.append(str(output_path))
    _run(command)


def normalize_quality(quality: str | None, default: str = "192k") -> str:
    if not quality:
        return default
    text = str(quality).strip().lower()
    if text in ("best", "0", "none"):
        return default
    if text.isdigit():
        return f"{text}k"
    if text.endswith("k") or text.endswith("m"):
        return text
    return default


def extract_audio(
    source: str | Path,
    output: str | Path,
    fmt: str,
    quality: str = "192K",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Extrae y convierte el audio al formato indicado."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target = (fmt or output_path.suffix.lstrip(".")).lower()

    codec_map = {
        "mp3": "libmp3lame",
        "m4a": "aac",
        "aac": "aac",
        "opus": "libopus",
        "ogg": "libopus",
        "wav": "pcm_s16le",
        "flac": "flac",
    }
    codec = codec_map.get(target)
    if codec is None:
        raise MediaError(f"Formato de audio no soportado: {target}")

    source_ext = Path(source).suffix.lstrip(".").lower()
    copy_stream = (
        source_ext == target
        or (source_ext, target) in {("webm", "opus"), ("mp4", "m4a")}
    ) and target in {"mp3", "m4a", "opus", "flac"}

    command = _base_command() + [
        "-i", str(source),
        "-vn",
        "-map", "0:a:0",
        "-c:a", "copy" if copy_stream else codec,
    ]
    if not copy_stream and target in {"mp3", "m4a", "aac", "opus", "ogg"}:
        command += ["-b:a", normalize_quality(quality)]
    if output_path.suffix.lower() in {".m4a", ".mp4"}:
        command += ["-movflags", "+faststart"]
    command += _metadata_args(metadata)
    command.append(str(output_path))
    _run(command)

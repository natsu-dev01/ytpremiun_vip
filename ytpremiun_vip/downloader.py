"""Orquestador: descubre videos, selecciona formatos y descarga."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ExtractionError, YtPremiunVipError
from .formats import Selection, format_table, select_format
from .http import DEFAULT_CONNECTIONS, DEFAULT_USER_AGENT, HttpClient
from .innertube import Format, InnertubeClient, VideoInfo
from .media import extract_audio, find_ffmpeg, merge, remux
from .playlist import PlaylistClient
from .progress import ProgressPrinter
from .subtitles import download_subtitle, select_tracks
from .urls import parse_input, video_url
from .utils import (
    build_output_path,
    human_bytes,
    human_duration,
    parse_index_spec,
)


@dataclass
class Options:
    output_template: str = "%(title)s [%(id)s].%(ext)s"
    paths: Path = field(default_factory=lambda: Path("downloads"))
    format_spec: str | None = None
    audio_only: bool = False
    audio_format: str = "mp3"
    audio_quality: str = "192K"
    merge_output_format: str = "mp4"
    write_subs: bool = False
    sub_langs: str | None = None
    sub_format: str = "srt"
    write_auto_subs: bool = False
    playlist: bool = True
    playlist_items: str | None = None
    max_downloads: int | None = None
    archive: Path | None = None
    restrict_filenames: bool = False
    force_overwrites: bool = False
    keep_files: bool = False
    quiet: bool = False
    no_progress: bool = False
    verbose: bool = False
    retries: int = 5
    timeout: float = 20.0
    connections: int = DEFAULT_CONNECTIONS
    jobs: int = 1
    proxy: str | None = None
    cookies: Path | None = None
    list_formats: bool = False
    print_json: bool = False
    flat_playlist: bool = False
    simulate: bool = False


@dataclass
class Job:
    video_id: str
    url: str
    playlist_id: str | None = None
    playlist_title: str | None = None
    playlist_index: int | None = None
    entry_title: str | None = None


@dataclass
class Result:
    job: Job
    status: str
    paths: list[Path] = field(default_factory=list)
    error: str | None = None
    info: VideoInfo | None = None


class Downloader:
    def __init__(self, options: Options) -> None:
        self.options = options
        self.http = HttpClient(
            timeout=options.timeout,
            retries=options.retries,
            proxy=options.proxy,
            cookies=options.cookies,
        )
        self.innertube = InnertubeClient(self.http, verbose=options.verbose)
        self.playlists = PlaylistClient(self.http)
        self._archive = self._load_archive()
        self._archive_lock = threading.Lock()
        self._print_lock = threading.Lock()

    # ------------------------------------------------------------------ cola
    def discover(
        self, inputs: list[str]
    ) -> tuple[list[Job], list[tuple[str, Exception]]]:
        jobs: list[Job] = []
        errors: list[tuple[str, Exception]] = []

        for raw in inputs:
            try:
                parsed = parse_input(raw)
                use_playlist = bool(
                    parsed.playlist_id
                    and self.options.playlist
                    and not (
                        parsed.video_id
                        and str(parsed.playlist_id).startswith("RD")
                    )
                )

                if use_playlist:
                    assert parsed.playlist_id is not None
                    self._log(f"Leyendo playlist {parsed.playlist_id}...")
                    playlist = self.playlists.fetch(parsed.playlist_id)
                    if playlist.warning:
                        self._warn(playlist.warning)
                    contains = parse_index_spec(self.options.playlist_items)
                    added = 0
                    for entry in playlist.entries:
                        if contains and not contains(entry.index):
                            continue
                        jobs.append(
                            Job(
                                video_id=entry.video_id,
                                url=entry.url,
                                playlist_id=playlist.id,
                                playlist_title=playlist.title,
                                playlist_index=entry.index,
                                entry_title=entry.title,
                            )
                        )
                        added += 1
                    self._log(
                        f"Playlist: {playlist.title} ({added} videos seleccionados)"
                    )
                    if added == 0:
                        raise ExtractionError(
                            "Ningún elemento de la playlist coincide con --playlist-items."
                        )
                elif parsed.video_id:
                    jobs.append(
                        Job(
                            video_id=parsed.video_id,
                            url=video_url(parsed.video_id),
                        )
                    )
                else:
                    raise ExtractionError(
                        "La URL solo contiene una playlist. "
                        "Usa --no-playlist únicamente con URLs de video."
                    )
            except Exception as exc:  # se informa y se sigue con las demás URLs
                errors.append((raw, exc))

        seen: set[str] = set()
        unique: list[Job] = []
        for job in jobs:
            if job.video_id in seen:
                continue
            seen.add(job.video_id)
            unique.append(job)

        return unique, errors

    def run(self, jobs: list[Job]) -> list[Result]:
        if self.options.max_downloads is not None:
            jobs = jobs[: max(0, self.options.max_downloads)]

        total = len(jobs)
        if total == 0:
            return []

        workers = max(1, min(int(self.options.jobs or 1), total))
        if workers == 1:
            return [
                self._process_safe(job, position, total)
                for position, job in enumerate(jobs, 1)
            ]

        # Varios videos a la vez: útil para playlists o listas de URLs. El
        # orden de los resultados se conserva aunque terminen desordenados.
        results: list[Result | None] = [None] * total
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="ytpremiun-job",
        ) as pool:
            futures = [
                pool.submit(self._process_safe, job, position, total)
                for position, job in enumerate(jobs, 1)
            ]
            for index, future in enumerate(futures):
                results[index] = future.result()
        return [result for result in results if result is not None]

    def _process_safe(self, job: Job, position: int, total: int) -> Result:
        """Procesa un trabajo sin dejar que un fallo detenga la cola."""
        try:
            return self.process(job, position, total)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if self.options.verbose:
                traceback.print_exc()
            self._warn(f"✗ {job.video_id}: {exc}")
            return Result(job=job, status="failed", error=str(exc))

    # -------------------------------------------------------------- descarga
    def process(self, job: Job, position: int, total: int) -> Result:
        if job.video_id in self._archive:
            self._log(
                f"↷ [{position}/{total}] {job.video_id}: ya está en el archivo; se omite."
            )
            return Result(job=job, status="skipped")

        info = self.innertube.get_video(job.video_id)
        if job.entry_title and (not info.title or info.title == info.id):
            info.title = job.entry_title

        if not self.options.quiet:
            print(f"\n[{position}/{total}] {info.title}")
            details = [info.author]
            if info.length_seconds:
                details.append(human_duration(info.length_seconds))
            details.append(f"cliente {info.source_client}")
            print("  " + " · ".join(part for part in details if part))

        if self.options.print_json:
            print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))

        if self.options.list_formats:
            print(format_table(info.formats))
            return Result(job=job, status="ok", info=info)

        selection = self._select(info)
        ext = self._target_ext(selection)
        final_path = self._build_path(info, job, selection, ext)
        final_path.parent.mkdir(parents=True, exist_ok=True)

        if final_path.exists() and not self.options.force_overwrites:
            self._log(f"  ↷ Ya existe: {final_path}")
            return Result(
                job=job, status="skipped", paths=[final_path], info=info
            )

        if self.options.simulate:
            self._log(f"  (simulación) {final_path}")
            for fmt in (selection.progressive, selection.video, selection.audio):
                if fmt:
                    detail = fmt.resolution if fmt.has_video else fmt.ext
                    self._log(f"    itag {fmt.itag}: {fmt.kind} {detail}")
            return Result(job=job, status="ok", paths=[final_path], info=info)

        temp_dir = final_path.parent / ".ytpremiun-vip-tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        metadata = self._metadata(info, job)
        actual_final = final_path

        if self.options.audio_only:
            source = selection.audio or selection.progressive
            if source is None:
                raise ExtractionError("No se seleccionó ninguna pista de audio.")
            source_path = temp_dir / f"{info.id}.f{source.itag}.{source.ext}"
            self._download_source(
                source,
                source_path,
                f"audio {source.ext}",
            )
            created.append(source_path)
            if source.ext == ext:
                self._move(source_path, final_path)
            else:
                find_ffmpeg()
                mixed = temp_dir / f"{info.id}.audio.{ext}"
                created.append(mixed)
                extract_audio(
                    source_path,
                    mixed,
                    ext,
                    self.options.audio_quality,
                    metadata,
                )
                self._move(mixed, final_path)

        elif selection.progressive is not None:
            source = selection.progressive
            source_path = temp_dir / f"{info.id}.f{source.itag}.{source.ext}"
            self._download_source(
                source,
                source_path,
                f"video+audio {source.resolution}",
            )
            created.append(source_path)
            if source.ext == final_path.suffix.lstrip(".").lower():
                self._move(source_path, final_path)
            else:
                try:
                    mixed = temp_dir / f"{info.id}.merged.{ext}"
                    created.append(mixed)
                    remux(source_path, mixed, metadata)
                    self._move(mixed, final_path)
                except YtPremiunVipError as exc:
                    fallback = final_path.with_suffix("." + source.ext)
                    self._warn(
                        f"  ! No se pudo cambiar el contenedor ({exc}). "
                        f"Se guarda como {fallback.name}"
                    )
                    self._move(source_path, fallback)
                    actual_final = fallback

        elif selection.video is not None and selection.audio is not None:
            video_path = (
                temp_dir
                / f"{info.id}.f{selection.video.itag}.{selection.video.ext}"
            )
            audio_path = (
                temp_dir
                / f"{info.id}.f{selection.audio.itag}.{selection.audio.ext}"
            )
            # Descargar ambos flujos a la vez casi duplica la velocidad en los
            # formatos separados de YouTube (1080p y superiores).
            self._download_sources(
                [
                    (
                        selection.video,
                        video_path,
                        f"video {selection.video.resolution}",
                    ),
                    (
                        selection.audio,
                        audio_path,
                        f"audio {selection.audio.ext}",
                    ),
                ]
            )
            created += [video_path, audio_path]

            try:
                mixed = temp_dir / f"{info.id}.merged.{ext}"
                created.append(mixed)
                merge(video_path, audio_path, mixed, metadata)
                self._move(mixed, final_path)
            except YtPremiunVipError as exc:
                if ext != "mp4":
                    raise
                fallback = final_path.with_suffix(".mkv")
                mixed_mkv = temp_dir / f"{info.id}.merged.mkv"
                created.append(mixed_mkv)
                self._warn(
                    f"  ! Falló el merge en MP4 ({exc}). "
                    "Reintentando en MKV..."
                )
                merge(video_path, audio_path, mixed_mkv, metadata)
                self._move(mixed_mkv, fallback)
                actual_final = fallback

        elif selection.video is not None:
            source = selection.video
            source_path = temp_dir / f"{info.id}.f{source.itag}.{source.ext}"
            self._download_source(
                source,
                source_path,
                f"video {source.resolution}",
            )
            created.append(source_path)
            self._move(source_path, final_path)

        elif selection.audio is not None:
            source = selection.audio
            source_path = temp_dir / f"{info.id}.f{source.itag}.{source.ext}"
            self._download_source(source, source_path, f"audio {source.ext}")
            created.append(source_path)
            self._move(source_path, final_path)

        else:
            raise ExtractionError("La selección de formato quedó vacía.")

        paths = [actual_final]
        if self.options.write_subs:
            paths.extend(self._download_subtitles(info, actual_final))

        if not self.options.keep_files:
            for path in created:
                self._safe_unlink(path)
            try:
                temp_dir.rmdir()
            except OSError:
                pass

        self._archive_add(info.id)

        size = actual_final.stat().st_size if actual_final.exists() else 0
        self._log(f"  ✓ {actual_final.name} ({human_bytes(size)})")
        return Result(
            job=job,
            status="ok",
            paths=paths,
            info=info,
        )

    # -------------------------------------------------------------- helpers
    def _select(self, info: VideoInfo) -> Selection:
        if self.options.audio_only:
            audio_pref = {
                "m4a": "m4a",
                "mp3": "m4a",
                "opus": "webm",
            }.get(self.options.audio_format)
        else:
            audio_pref = "m4a" if self.options.merge_output_format == "mp4" else None

        return select_format(
            info.formats,
            self.options.format_spec,
            audio_only=self.options.audio_only,
            merge_ext=self.options.merge_output_format,
            audio_ext_pref=audio_pref,
        )

    def _target_ext(self, selection: Selection) -> str:
        if self.options.audio_only:
            source = selection.audio or selection.progressive
            if source is None:
                raise ExtractionError("No hay audio disponible.")
            if self.options.audio_format == "best":
                return source.ext
            if self.options.audio_format == "m4a" and source.ext == "m4a":
                return "m4a"
            if self.options.audio_format == "opus" and source.ext == "webm":
                return "opus"
            return self.options.audio_format

        if selection.progressive is not None:
            if (
                selection.progressive.ext == "webm"
                and self.options.merge_output_format == "mp4"
            ):
                return "mp4"
            return selection.progressive.ext
        if selection.video is not None and selection.audio is not None:
            return self.options.merge_output_format
        if selection.video is not None:
            return selection.video.ext
        if selection.audio is not None:
            return selection.audio.ext
        raise ExtractionError("No se pudo determinar la extensión de salida.")

    def _build_path(
        self,
        info: VideoInfo,
        job: Job,
        selection: Selection,
        ext: str,
    ) -> Path:
        primary: Format | None = (
            selection.progressive or selection.video or selection.audio
        )
        fields: dict[str, object] = {
            "id": info.id,
            "title": info.title,
            "uploader": info.author,
            "channel": info.author,
            "channel_id": info.channel_id,
            "duration": info.length_seconds,
            "duration_string": human_duration(info.length_seconds),
            "upload_date": info.upload_date,
            "view_count": info.view_count,
            "playlist_id": job.playlist_id or "",
            "playlist_title": job.playlist_title or "",
            "playlist_index": job.playlist_index or "",
            "epoch": int(time.time()),
            "ext": ext,
            "resolution": primary.resolution if primary else "",
            "height": (primary.height or "") if primary else "",
            "width": (primary.width or "") if primary else "",
            "fps": (primary.fps or "") if primary else "",
            "format_id": primary.itag if primary else "",
        }
        return build_output_path(
            self.options.output_template,
            fields,
            self.options.paths,
            restrict=self.options.restrict_filenames,
        )

    def _download_sources(
        self, sources: list[tuple[Format, Path, str]]
    ) -> None:
        """Descarga varias pistas en paralelo y espera a que terminen todas."""
        if len(sources) == 1:
            self._download_source(*sources[0])
            return

        errors: list[BaseException] = []
        with ThreadPoolExecutor(
            max_workers=len(sources),
            thread_name_prefix="ytpremiun-stream",
        ) as pool:
            futures = [
                pool.submit(self._download_source, *source) for source in sources
            ]
            for future in futures:
                try:
                    future.result()
                except KeyboardInterrupt:
                    raise
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]

    def _download_source(self, fmt: Format, destination: Path, label: str) -> None:
        printer = ProgressPrinter(
            label,
            quiet=self.options.quiet,
            enabled=not self.options.no_progress,
        )
        try:
            self.http.stream_download(
                fmt.url,
                destination,
                expected_size=fmt.filesize,
                progress=printer,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": "https://www.youtube.com/",
                },
                connections=self.options.connections,
            )
        finally:
            printer.finish()

    def _download_subtitles(self, info: VideoInfo, final_path: Path) -> list[Path]:
        tracks = select_tracks(
            info.subtitles,
            self.options.sub_langs,
            self.options.write_auto_subs,
            info.default_audio_language,
        )
        if not tracks:
            self._warn(
                "  ! No hay subtítulos que coincidan con el idioma pedido."
            )
            return []

        base = final_path.with_suffix("")
        downloaded: list[Path] = []
        for track in tracks:
            try:
                path = download_subtitle(
                    track,
                    self.http,
                    base,
                    self.options.sub_format,
                    force=self.options.force_overwrites,
                )
            except YtPremiunVipError as exc:
                self._warn(
                    f"  ! No se pudo descargar el subtítulo "
                    f"{track.language_code}: {exc}"
                )
                continue
            if path is None:
                self._warn(
                    f"  ! El subtítulo {track.language_code} llegó vacío; se omite."
                )
                continue
            downloaded.append(path)
            self._log(f"  ✓ subtítulos {track.language_code}: {path.name}")
        return downloaded

    def _metadata(self, info: VideoInfo, job: Job) -> dict[str, str]:
        metadata = {
            "title": info.title,
            "artist": info.author,
            "date": info.upload_date,
            "comment": info.webpage_url,
        }
        if job.playlist_title:
            metadata["album"] = job.playlist_title
        return metadata

    def _move(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass

    def _load_archive(self) -> set[str]:
        if not self.options.archive:
            return set()
        path = Path(self.options.archive)
        if not path.exists():
            return set()
        identifiers: set[str] = set()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            identifiers.add(line.split()[0])
        return identifiers

    def _archive_add(self, video_id: str) -> None:
        if not self.options.archive:
            return
        with self._archive_lock:
            path = Path(self.options.archive)
            path.parent.mkdir(parents=True, exist_ok=True)
            if video_id in self._archive:
                return
            with path.open("a", encoding="utf-8") as handle:
                handle.write(video_id + "\n")
            self._archive.add(video_id)

    def _log(self, message: str) -> None:
        if not self.options.quiet:
            with self._print_lock:
                print(message, flush=True)

    def _warn(self, message: str) -> None:
        with self._print_lock:
            print(message, file=sys.stderr, flush=True)

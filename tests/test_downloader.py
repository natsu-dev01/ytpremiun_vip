"""Tests del orquestador: descubrimiento, cola, archivo y flujo de descarga."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytpremiun_vip.downloader import Downloader, Job, Options
from ytpremiun_vip.errors import ExtractionError, MediaError
from ytpremiun_vip.formats import Selection
from ytpremiun_vip.innertube import Format, VideoInfo
from ytpremiun_vip.playlist import PlaylistEntry, PlaylistInfo

VIDEO = "jNQXAC9IVRw"


def make_format(
    itag: int,
    *,
    ext: str = "mp4",
    vcodec: str | None = None,
    acodec: str | None = None,
    height: int | None = None,
    audio_bitrate: float | None = None,
) -> Format:
    has_video = vcodec is not None
    has_audio = acodec is not None
    return Format(
        itag=itag,
        url="https://example.com/v",
        mime_type="video/mp4" if has_video else "audio/mp4",
        ext=ext,
        vcodec=vcodec,
        acodec=acodec,
        width=None,
        height=height,
        fps=30 if has_video else None,
        bitrate=500_000,
        audio_bitrate=audio_bitrate,
        quality_label=f"{height}p" if height else None,
        audio_quality=None,
        filesize=None,
        duration=19.0,
        has_video=has_video,
        has_audio=has_audio,
        is_progressive=has_video and has_audio,
        source_client="android",
    )


def make_info(formats: list[Format]) -> VideoInfo:
    return VideoInfo(
        id=VIDEO,
        title="Demo",
        author="Canal",
        channel_id="UC1",
        length_seconds=19,
        view_count=10,
        description="desc",
        keywords=[],
        thumbnails=[],
        upload_date="20050424",
        is_live=False,
        default_audio_language="es",
        formats=formats,
        subtitles=[],
        source_client="android",
        webpage_url=f"https://www.youtube.com/watch?v={VIDEO}",
    )


class FakeInnertube:
    def __init__(self, info: VideoInfo):
        self.info = info
        self.calls = 0

    def get_video(self, video_id: str) -> VideoInfo:
        self.calls += 1
        return self.info


class FakeHttp:
    def __init__(self, payload: bytes = b"contenido"):
        self.payload = payload
        self.downloads: list[Path] = []

    def stream_download(
        self,
        url,
        destination,
        *,
        expected_size=None,
        progress=None,
        headers=None,
        connections=None,
    ):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.payload)
        self.downloads.append(path)
        if progress:
            progress(len(self.payload), len(self.payload))
        return len(self.payload)


class FakePlaylists:
    def __init__(self, entries=None, *, fail=False):
        self.entries = entries or []
        self.fail = fail
        self.calls = 0

    def fetch(self, playlist_id):
        self.calls += 1
        if self.fail:
            raise AssertionError("no se esperaba leer la playlist")
        return PlaylistInfo(id=playlist_id, title="Lista", entries=self.entries)


def make_downloader(tmp: str, info: VideoInfo, **option_kwargs) -> Downloader:
    options = Options(
        paths=Path(tmp),
        quiet=True,
        no_progress=True,
        **option_kwargs,
    )
    downloader = Downloader(options)
    downloader.innertube = FakeInnertube(info)
    downloader.http = FakeHttp()
    return downloader


class ArchiveTests(unittest.TestCase):
    def test_load_and_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archivo.txt"
            archive.write_text("# comentario\nabc 2024\ndef\n\n", encoding="utf-8")
            options = Options(paths=Path(tmp), archive=archive, quiet=True)
            downloader = Downloader(options)
            self.assertEqual(downloader._archive, {"abc", "def"})
            downloader._archive_add("abc")
            downloader._archive_add("nuevo")
            lines = archive.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines.count("abc 2024"), 1)
            self.assertIn("nuevo", lines)

    def test_archived_video_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archivo.txt"
            archive.write_text(VIDEO + "\n", encoding="utf-8")
            info = make_info([make_format(18, vcodec="avc1", acodec="mp4a")])
            downloader = make_downloader(tmp, info, archive=archive)
            downloader.http = FakeHttp()
            result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            self.assertEqual(result.status, "skipped")
            assert isinstance(downloader.innertube, FakeInnertube)
            self.assertEqual(downloader.innertube.calls, 0)


class DiscoverTests(unittest.TestCase):
    def test_playlist_uses_selected_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(Options(paths=Path(tmp), quiet=True))
            downloader.playlists = FakePlaylists(
                [
                    PlaylistEntry("aaaaaaaaaaa", "A", 1, "https://a"),
                    PlaylistEntry("bbbbbbbbbbb", "B", 2, "https://b"),
                    PlaylistEntry("ccccccccccc", "C", 3, "https://c"),
                ]
            )
            downloader.options.playlist_items = "2"
            jobs, errors = downloader.discover(
                ["https://www.youtube.com/playlist?list=PL123"]
            )
            self.assertEqual(errors, [])
            self.assertEqual([job.video_id for job in jobs], ["bbbbbbbbbbb"])
            self.assertEqual(jobs[0].playlist_index, 2)
            self.assertEqual(jobs[0].playlist_title, "Lista")

    def test_playlist_items_no_match_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(Options(paths=Path(tmp), quiet=True))
            downloader.playlists = FakePlaylists(
                [PlaylistEntry("aaaaaaaaaaa", "A", 1, "https://a")]
            )
            downloader.options.playlist_items = "5-10"
            jobs, errors = downloader.discover(
                ["https://www.youtube.com/playlist?list=PL123"]
            )
            self.assertEqual(jobs, [])
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0][1], ExtractionError)

    def test_no_playlist_forces_video_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(
                Options(paths=Path(tmp), quiet=True, playlist=False)
            )
            downloader.playlists = FakePlaylists(fail=True)
            jobs, errors = downloader.discover(
                [f"https://www.youtube.com/watch?v={VIDEO}&list=PL123"]
            )
            self.assertEqual(errors, [])
            self.assertEqual([job.video_id for job in jobs], [VIDEO])
            self.assertIsNone(jobs[0].playlist_id)

    def test_deduplicates_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(Options(paths=Path(tmp), quiet=True))
            jobs, errors = downloader.discover(
                [f"https://youtu.be/{VIDEO}", f"https://www.youtube.com/watch?v={VIDEO}"]
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(jobs), 1)

    def test_invalid_url_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(Options(paths=Path(tmp), quiet=True))
            jobs, errors = downloader.discover(["https://vimeo.com/1"])
            self.assertEqual(jobs, [])
            self.assertEqual(len(errors), 1)


class TargetExtTests(unittest.TestCase):
    def _downloader(self):
        return Downloader(Options(quiet=True))

    def test_progressive_webm_to_mp4(self):
        selection = Selection(progressive=make_format(43, ext="webm", vcodec="vp8", acodec="vorbis"))
        self.assertEqual(self._downloader()._target_ext(selection), "mp4")

    def test_merge_container(self):
        selection = Selection(
            video=make_format(137, vcodec="avc1", height=1080),
            audio=make_format(140, ext="m4a", acodec="mp4a"),
        )
        downloader = Downloader(Options(quiet=True, merge_output_format="mkv"))
        self.assertEqual(downloader._target_ext(selection), "mkv")

    def test_audio_best_keeps_source_ext(self):
        selection = Selection(audio=make_format(251, ext="webm", acodec="opus"))
        downloader = Downloader(Options(quiet=True, audio_only=True, audio_format="best"))
        self.assertEqual(downloader._target_ext(selection), "webm")

    def test_audio_opus_from_webm(self):
        selection = Selection(audio=make_format(251, ext="webm", acodec="opus"))
        downloader = Downloader(Options(quiet=True, audio_only=True, audio_format="opus"))
        self.assertEqual(downloader._target_ext(selection), "opus")

    def test_empty_selection_raises(self):
        with self.assertRaises(ExtractionError):
            self._downloader()._target_ext(Selection())


class BuildPathTests(unittest.TestCase):
    def test_template_and_playlist_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            downloader = Downloader(
                Options(
                    paths=Path(tmp),
                    quiet=True,
                    output_template="%(playlist_index)03d - %(title)s.%(ext)s",
                )
            )
            info = make_info([make_format(18, vcodec="avc1", acodec="mp4a")])
            job = Job(VIDEO, "https://x", playlist_index=2, playlist_title="Lista")
            path = downloader._build_path(
                info, job, Selection(progressive=info.formats[0]), "mp4"
            )
            self.assertEqual(path, Path(tmp) / "002 - Demo.mp4")

    def test_metadata(self):
        downloader = Downloader(Options(quiet=True))
        info = make_info([])
        job = Job(VIDEO, "https://x", playlist_title="Lista")
        metadata = downloader._metadata(info, job)
        self.assertEqual(metadata["title"], "Demo")
        self.assertEqual(metadata["artist"], "Canal")
        self.assertEqual(metadata["album"], "Lista")


class ProcessTests(unittest.TestCase):
    def test_progressive_download(self):
        info = make_info([make_format(18, vcodec="avc1", acodec="mp4a", height=360)])
        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info)
            result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mp4"
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.paths, [final])
            self.assertTrue(final.exists())
            self.assertEqual(final.read_bytes(), b"contenido")
            self.assertFalse((Path(tmp) / ".ytpremiun-vip-tmp").exists())

    def test_existing_file_is_skipped(self):
        info = make_info([make_format(18, vcodec="avc1", acodec="mp4a", height=360)])
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mp4"
            final.write_bytes(b"previo")
            downloader = make_downloader(tmp, info)
            result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            self.assertEqual(result.status, "skipped")
            self.assertEqual(final.read_bytes(), b"previo")
            assert isinstance(downloader.http, FakeHttp)
            self.assertEqual(downloader.http.downloads, [])

    def test_simulate_does_not_download(self):
        info = make_info([make_format(18, vcodec="avc1", acodec="mp4a", height=360)])
        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info, simulate=True)
            result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            self.assertEqual(result.status, "ok")
            self.assertFalse(result.paths[0].exists())
            assert isinstance(downloader.http, FakeHttp)
            self.assertEqual(downloader.http.downloads, [])

    def test_audio_only_mp3(self):
        info = make_info([make_format(140, ext="m4a", acodec="mp4a", audio_bitrate=128_000)])

        def fake_extract(source, output, fmt, quality="192K", metadata=None):
            Path(output).write_bytes(b"mp3")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(
                tmp, info, audio_only=True, audio_format="mp3"
            )
            with patch("ytpremiun_vip.downloader.find_ffmpeg", return_value="ffmpeg"):
                with patch(
                    "ytpremiun_vip.downloader.extract_audio", side_effect=fake_extract
                ) as extract:
                    result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mp3"
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.paths, [final])
            self.assertEqual(final.read_bytes(), b"mp3")
            self.assertEqual(extract.call_args.args[2], "mp3")

    def test_split_video_audio_merge(self):
        info = make_info(
            [
                make_format(137, vcodec="avc1", height=1080),
                make_format(140, ext="m4a", acodec="mp4a", audio_bitrate=128_000),
            ]
        )

        def fake_merge(video, audio, output, metadata=None):
            Path(output).write_bytes(b"merged")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info)
            with patch("ytpremiun_vip.downloader.merge", side_effect=fake_merge) as merge:
                result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mp4"
            self.assertEqual(result.status, "ok")
            self.assertEqual(final.read_bytes(), b"merged")
            self.assertEqual(merge.call_count, 1)

    def test_merge_falls_back_to_mkv(self):
        info = make_info(
            [
                make_format(137, vcodec="avc1", height=1080),
                make_format(140, ext="m4a", acodec="mp4a", audio_bitrate=128_000),
            ]
        )
        calls = []

        def fake_merge(video, audio, output, metadata=None):
            calls.append(Path(output))
            if len(calls) == 1:
                raise MediaError("contenedor incompatible")
            Path(output).write_bytes(b"mkv")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info)
            with patch("ytpremiun_vip.downloader.merge", side_effect=fake_merge):
                with contextlib.redirect_stderr(io.StringIO()):
                    result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mkv"
            self.assertEqual(result.paths, [final])
            self.assertTrue(final.exists())
            self.assertEqual(len(calls), 2)

    def test_progressive_remux_to_mp4(self):
        info = make_info([make_format(43, ext="webm", vcodec="vp8", acodec="vorbis")])

        def fake_remux(source, output, metadata=None):
            Path(output).write_bytes(b"remux")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info)
            with patch("ytpremiun_vip.downloader.remux", side_effect=fake_remux) as remux:
                result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            final = Path(tmp) / "Demo [jNQXAC9IVRw].mp4"
            self.assertEqual(result.paths, [final])
            self.assertEqual(final.read_bytes(), b"remux")
            self.assertEqual(remux.call_count, 1)

    def test_keep_files_leaves_temp_dir(self):
        info = make_info([make_format(43, ext="webm", vcodec="vp8", acodec="vorbis")])

        def fake_remux(source, output, metadata=None):
            Path(output).write_bytes(b"remux")

        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(
                tmp, info, keep_files=True, output_template="video.%(ext)s"
            )
            with patch("ytpremiun_vip.downloader.remux", side_effect=fake_remux):
                result = downloader.process(Job(VIDEO, "https://x"), 1, 1)
            self.assertEqual(result.status, "ok")
            temp_dir = Path(tmp) / ".ytpremiun-vip-tmp"
            self.assertTrue(temp_dir.exists())
            self.assertTrue(any(temp_dir.iterdir()))

    def test_result_failure_is_captured_in_run(self):
        info = make_info([make_format(18, vcodec="avc1", acodec="mp4a", height=360)])
        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info)
            with patch.object(downloader, "process", side_effect=RuntimeError("boom")):
                with contextlib.redirect_stderr(io.StringIO()):
                    results = downloader.run([Job(VIDEO, "https://x")])
            self.assertEqual(results[0].status, "failed")
            self.assertIn("boom", results[0].error or "")

    def test_max_downloads(self):
        info = make_info([make_format(18, vcodec="avc1", acodec="mp4a", height=360)])
        with tempfile.TemporaryDirectory() as tmp:
            downloader = make_downloader(tmp, info, max_downloads=0)
            results = downloader.run([Job(VIDEO, "https://x")])
            self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()

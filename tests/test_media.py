"""Tests de la integración con ffmpeg (comandos y ejecución real opcional)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytpremiun_vip.errors import FFmpegNotFoundError, MediaError
from ytpremiun_vip.media import (
    _metadata_args,
    extract_audio,
    ffmpeg_available,
    find_ffmpeg,
    merge,
    normalize_quality,
    remux,
)


class NormalizeQualityTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(normalize_quality(None), "192k")
        self.assertEqual(normalize_quality(""), "192k")
        self.assertEqual(normalize_quality("best"), "192k")
        self.assertEqual(normalize_quality("320"), "320k")
        self.assertEqual(normalize_quality("128K"), "128k")
        self.assertEqual(normalize_quality("2M"), "2m")
        self.assertEqual(normalize_quality("raro"), "192k")


class MetadataTests(unittest.TestCase):
    def test_metadata_args(self):
        args = _metadata_args(
            {"title": "Hola\nmundo", "artist": "Canal", "vacio": "", "nada": None}
        )
        self.assertEqual(
            args,
            ["-metadata", "title=Hola mundo", "-metadata", "artist=Canal"],
        )

    def test_metadata_none(self):
        self.assertEqual(_metadata_args(None), [])


class CommandTests(unittest.TestCase):
    def _capture(self, func, *args, **kwargs):
        with patch("ytpremiun_vip.media._run") as run:
            func(*args, **kwargs)
        self.assertTrue(run.called)
        return run.call_args.args[0]

    def test_mp3_reencodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                extract_audio,
                Path(tmp) / "v.webm",
                Path(tmp) / "out.mp3",
                "mp3",
                "320K",
            )
        self.assertIn("libmp3lame", command)
        self.assertIn("-b:a", command)
        self.assertIn("320k", command)
        self.assertNotIn("copy", command)

    def test_opus_copies_webm(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                extract_audio,
                Path(tmp) / "v.webm",
                Path(tmp) / "out.opus",
                "opus",
            )
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertNotIn("-b:a", command)

    def test_m4a_copies_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                extract_audio,
                Path(tmp) / "v.mp4",
                Path(tmp) / "out.m4a",
                "m4a",
            )
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertIn("-movflags", command)

    def test_flac_reencodes_webm(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                extract_audio,
                Path(tmp) / "v.webm",
                Path(tmp) / "out.flac",
                "flac",
            )
        self.assertEqual(command[command.index("-c:a") + 1], "flac")

    def test_unsupported_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MediaError):
                with patch("ytpremiun_vip.media._run"):
                    extract_audio(
                        Path(tmp) / "v.webm", Path(tmp) / "out.xyz", "xyz"
                    )

    def test_merge_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                merge,
                Path(tmp) / "v.mp4",
                Path(tmp) / "a.m4a",
                Path(tmp) / "out.mp4",
                {"title": "Demo"},
            )
        self.assertIn("0:v:0", command)
        self.assertIn("1:a:0", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertIn("+faststart", command)
        self.assertIn("title=Demo", command)

    def test_merge_mkv_has_no_faststart(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                merge,
                Path(tmp) / "v.webm",
                Path(tmp) / "a.webm",
                Path(tmp) / "out.mkv",
            )
        self.assertNotIn("+faststart", command)

    def test_remux(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = self._capture(
                remux, Path(tmp) / "v.webm", Path(tmp) / "out.mp4"
            )
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertIn("+faststart", command)


class FindFFmpegTests(unittest.TestCase):
    def test_not_found_raises(self):
        with patch.dict(os.environ, {"FFMPEG": ""}):
            with patch("ytpremiun_vip.media.shutil.which", return_value=None):
                with patch("ytpremiun_vip.media.Path.exists", return_value=False):
                    with self.assertRaises(FFmpegNotFoundError):
                        find_ffmpeg()

    def test_available_flag(self):
        with patch("ytpremiun_vip.media.find_ffmpeg", return_value="ffmpeg"):
            self.assertTrue(ffmpeg_available())
        with patch("ytpremiun_vip.media.find_ffmpeg", side_effect=FFmpegNotFoundError()):
            self.assertFalse(ffmpeg_available())


@unittest.skipUnless(ffmpeg_available(), "ffmpeg no está disponible")
class RealFFmpegTests(unittest.TestCase):
    def test_extract_mp3_from_generated_wav(self):
        ffmpeg = find_ffmpeg()
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "tono.wav"
            mp3 = Path(tmp) / "tono.mp3"
            subprocess.run(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                    str(wav),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            extract_audio(wav, mp3, "mp3", "128K")
            self.assertTrue(mp3.exists())
            self.assertGreater(mp3.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()

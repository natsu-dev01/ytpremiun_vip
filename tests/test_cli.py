"""Tests de la interfaz de línea de comandos."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ytpremiun_vip.cli import build_parser, main
from ytpremiun_vip.downloader import Job, Result
from ytpremiun_vip.errors import YtPremiunVipError

VIDEO = "jNQXAC9IVRw"


class ParserTests(unittest.TestCase):
    def test_defaults(self):
        args = build_parser().parse_args([VIDEO])
        self.assertEqual(args.urls, [VIDEO])
        self.assertEqual(args.paths, "downloads")
        self.assertEqual(args.audio_format, "mp3")
        self.assertEqual(args.audio_quality, "192K")
        self.assertTrue(args.playlist)
        self.assertFalse(args.audio_only)
        self.assertFalse(args.write_subs)
        self.assertFalse(args.json_result)
        self.assertEqual(args.jobs, 1)

    def test_flags(self):
        args = build_parser().parse_args(
            [
                "-x",
                "--audio-format", "m4a",
                "--no-playlist",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", "es,en",
                "--playlist-items", "1-2",
                "--merge-output-format", "mkv",
                "--max-downloads", "3",
                "--jobs", "3",
                VIDEO,
            ]
        )
        self.assertTrue(args.audio_only)
        self.assertEqual(args.audio_format, "m4a")
        self.assertFalse(args.playlist)
        self.assertTrue(args.write_subs)
        self.assertTrue(args.write_auto_subs)
        self.assertEqual(args.sub_langs, "es,en")
        self.assertEqual(args.playlist_items, "1-2")
        self.assertEqual(args.merge_output_format, "mkv")
        self.assertEqual(args.max_downloads, 3)
        self.assertEqual(args.jobs, 3)

    def test_invalid_choice(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["--audio-format", "ogg", VIDEO])


class MainTests(unittest.TestCase):
    def _run(self, argv, **fake_config):
        job = Job(VIDEO, f"https://www.youtube.com/watch?v={VIDEO}")
        fake = fake_config.pop("fake")
        fake.discover.return_value = fake_config.pop("discover", ([job], []))
        if "run" in fake_config:
            fake.run.return_value = fake_config.pop("run")
        with patch("ytpremiun_vip.cli.Downloader", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_requires_input(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        self.assertEqual(ctx.exception.code, 2)

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_missing_batch_file(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["-a", "no-existe-jamas.txt"])
        self.assertEqual(code, 2)

    def test_success_summary(self):
        from unittest.mock import Mock

        job = Job(VIDEO, f"https://www.youtube.com/watch?v={VIDEO}")
        fake = Mock()
        fake.run.return_value = [Result(job=job, status="ok", paths=[Path("x.mp4")])]
        code, out, _ = self._run([VIDEO], fake=fake)
        self.assertEqual(code, 0)
        self.assertIn("Resumen: 1 correctos, 0 omitidos, 0 fallidos", out)

    def test_discovery_errors_return_one(self):
        from unittest.mock import Mock

        fake = Mock()
        code, out, err = self._run(
            ["https://vimeo.com/1"],
            fake=fake,
            discover=([], [("https://vimeo.com/1", ValueError("no es YouTube"))]),
        )
        self.assertEqual(code, 1)
        self.assertIn("No hay nada que descargar.", err)

    def test_failed_result_returns_one(self):
        from unittest.mock import Mock

        job = Job(VIDEO, f"https://www.youtube.com/watch?v={VIDEO}")
        fake = Mock()
        fake.run.return_value = [
            Result(job=job, status="failed", error="falló la red")
        ]
        code, out, err = self._run([VIDEO], fake=fake)
        self.assertEqual(code, 1)
        self.assertIn("1 fallidos", out)
        self.assertIn("falló la red", err)

    def test_flat_playlist_prints_urls(self):
        from unittest.mock import Mock

        job = Job(VIDEO, f"https://www.youtube.com/watch?v={VIDEO}")
        fake = Mock()
        code, out, _ = self._run([VIDEO, "--flat-playlist"], fake=fake)
        self.assertEqual(code, 0)
        self.assertIn(f"https://www.youtube.com/watch?v={VIDEO}", out)
        fake.run.assert_not_called()

    def test_json_resultado(self):
        from unittest.mock import Mock

        job = Job(VIDEO, f"https://www.youtube.com/watch?v={VIDEO}")
        fake = Mock()
        fake.run.return_value = [
            Result(job=job, status="ok", paths=[Path("x.mp4")])
        ]
        code, out, err = self._run([VIDEO, "--json"], fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["ok"])
        self.assertEqual(data[0]["estado"], "ok")
        self.assertEqual(data[0]["archivo"], "x.mp4")
        self.assertEqual(data[0]["url"], job.url)

    def test_json_incluye_errores_de_descubrimiento(self):
        from unittest.mock import Mock

        fake = Mock()
        code, out, err = self._run(
            ["https://vimeo.com/1", "--json"],
            fake=fake,
            discover=([], [("https://vimeo.com/1", ValueError("no es YouTube"))]),
        )
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["ok"])
        self.assertEqual(data[0]["estado"], "fallido")
        self.assertIn("no es YouTube", data[0]["error"])

    def test_keyboard_interrupt(self):
        from unittest.mock import Mock

        fake = Mock()
        fake.run.side_effect = KeyboardInterrupt
        code, _, err = self._run([VIDEO], fake=fake)
        self.assertEqual(code, 130)
        self.assertIn("Cancelado", err)

    def test_custom_error_returns_one(self):
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with patch(
                    "ytpremiun_vip.cli.Downloader", side_effect=YtPremiunVipError("x")
                ):
                    code = main([VIDEO])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

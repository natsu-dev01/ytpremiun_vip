"""Tests de las utilidades generales."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ytpremiun_vip.utils import (
    build_output_path,
    dedupe,
    deep_get,
    extract_json_after,
    format_template,
    human_bytes,
    human_duration,
    human_eta,
    human_speed,
    parse_index_spec,
    parse_size,
    read_batch_file,
    safe_float,
    safe_int,
    sanitize_filename,
    text_of,
    truncate,
)


class HumanFormatTests(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(1023), "1023 B")
        self.assertEqual(human_bytes(1024), "1.0 KiB")
        self.assertEqual(human_bytes(1536), "1.5 KiB")
        self.assertEqual(human_bytes(1024 ** 3), "1.0 GiB")
        self.assertEqual(human_bytes(None), "?")
        self.assertEqual(human_bytes(-5), "?")

    def test_human_duration(self):
        self.assertEqual(human_duration(0), "00:00")
        self.assertEqual(human_duration(59), "00:59")
        self.assertEqual(human_duration(60), "01:00")
        self.assertEqual(human_duration(3661), "01:01:01")
        self.assertEqual(human_duration(None), "?")
        self.assertEqual(human_duration(-1), "?")

    def test_human_speed_and_eta(self):
        self.assertEqual(human_speed(0), "?")
        self.assertEqual(human_speed(1024), "1.0 KiB/s")
        self.assertEqual(human_eta(None), "--:--")
        self.assertEqual(human_eta(90), "01:30")


class ParsingTests(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(parse_size("1024"), 1024)
        self.assertEqual(parse_size("1.5K"), 1536)
        self.assertEqual(parse_size("1.5M"), int(1.5 * 1024 ** 2))
        self.assertEqual(parse_size("20 MiB"), 20 * 1024 ** 2)
        self.assertEqual(parse_size("2g"), 2 * 1024 ** 3)
        self.assertIsNone(parse_size("grande"))
        self.assertIsNone(parse_size(""))

    def test_safe_numbers(self):
        self.assertEqual(safe_int("42"), 42)
        self.assertEqual(safe_int(None, 7), 7)
        self.assertEqual(safe_int("x", 3), 3)
        self.assertEqual(safe_float("1.5"), 1.5)
        self.assertEqual(safe_float("x", 2.5), 2.5)

    def test_truncate(self):
        self.assertEqual(truncate("abcdef", 5), "ab...")
        self.assertEqual(truncate("abc", 5), "abc")
        self.assertEqual(truncate("abcdef", 2), "ab")


class FilenameTests(unittest.TestCase):
    def test_illegal_characters(self):
        result = sanitize_filename('a/b:c*?"<>|')
        self.assertTrue(result.startswith("a_b_c"))
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, result)

    def test_reserved_names(self):
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("con.txt"), "_con.txt")
        self.assertEqual(sanitize_filename("LPT1"), "_LPT1")

    def test_trimming_and_empty(self):
        self.assertEqual(sanitize_filename("  nombre.  "), "nombre")
        self.assertEqual(sanitize_filename(""), "download")
        self.assertEqual(sanitize_filename(None), "download")

    def test_restrict_ascii(self):
        self.assertEqual(sanitize_filename("canción.mp4", restrict=True), "cancion.mp4")

    def test_max_length(self):
        result = sanitize_filename("x" * 300, max_length=50)
        self.assertEqual(len(result), 50)


class TemplateTests(unittest.TestCase):
    def test_format_template_basic(self):
        fields = {"title": "Hola", "id": "abc", "ext": "mp4"}
        self.assertEqual(
            format_template("%(title)s [%(id)s].%(ext)s", fields),
            "Hola [abc].mp4",
        )

    def test_format_template_number_and_float(self):
        fields = {"playlist_index": 5, "duration": 12.345}
        self.assertEqual(format_template("%(playlist_index)03d", fields), "005")
        self.assertEqual(format_template("%(duration)f", fields), "12.35")

    def test_format_template_missing(self):
        self.assertEqual(format_template("[%(nada)s]", {}), "[]")

    def test_build_output_path(self):
        fields = {"title": "Mi video", "id": "abcdefghijk", "ext": "mp4"}
        with tempfile.TemporaryDirectory() as tmp:
            path = build_output_path(
                "%(title)s [%(id)s].%(ext)s", fields, tmp
            )
            self.assertEqual(path, Path(tmp) / "Mi video [abcdefghijk].mp4")

    def test_build_output_path_nested_and_traversal(self):
        fields = {"title": "Tema", "ext": "mp3"}
        with tempfile.TemporaryDirectory() as tmp:
            nested = build_output_path("sub/%(title)s.%(ext)s", fields, tmp)
            self.assertEqual(nested, Path(tmp) / "sub" / "Tema.mp3")

            traversal = build_output_path("../escape.%(ext)s", fields, tmp)
            self.assertIn(Path(tmp), traversal.parents)
            self.assertEqual(traversal.name, "escape.mp3")
            self.assertEqual(traversal.parent, Path(tmp) / "_")


class IndexSpecTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(parse_index_spec(None))
        self.assertIsNone(parse_index_spec("  "))

    def test_ranges(self):
        contains = parse_index_spec("1-3,7,10-")
        self.assertIsNotNone(contains)
        assert contains is not None
        for index in (1, 2, 3, 7, 10, 999):
            self.assertTrue(contains(index), index)
        for index in (0, 4, 5, 6, 8, 9):
            self.assertFalse(contains(index), index)

    def test_reversed_range(self):
        contains = parse_index_spec("5-2")
        assert contains is not None
        self.assertTrue(contains(2))
        self.assertTrue(contains(5))
        self.assertFalse(contains(1))


class MiscTests(unittest.TestCase):
    def test_read_batch_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "urls.txt"
            path.write_text(
                "\ufeff# comentario\n\nhttps://a\n  https://b  \n",
                encoding="utf-8",
            )
            self.assertEqual(read_batch_file(path), ["https://a", "https://b"])

    def test_dedupe(self):
        self.assertEqual(dedupe(["a", "b", "a", "c", "b"]), ["a", "b", "c"])

    def test_extract_json_after(self):
        text = 'var ytInitialData = {"a": {"b": 1}}; otra cosa'
        self.assertEqual(
            extract_json_after(text, "ytInitialData"), {"a": {"b": 1}}
        )
        self.assertIsNone(extract_json_after(text, "no-existe"))
        self.assertIsNone(extract_json_after("sin llaves", "x"))

    def test_deep_get(self):
        data = {"a": {"b": [{"c": 5}]}}
        self.assertEqual(deep_get(data, "a.b.0.c"), 5)
        self.assertEqual(deep_get(data, "a.b.0.d", "x"), "x")
        self.assertEqual(deep_get(data, "a.b.9.c", "def"), "def")
        self.assertEqual(deep_get(data, "a.b.zz", "def"), "def")

    def test_text_of(self):
        self.assertEqual(text_of("hola"), "hola")
        self.assertEqual(text_of({"simpleText": "simple"}), "simple")
        self.assertEqual(text_of({"runs": [{"text": "a"}, {"text": "b"}]}), "ab")
        self.assertEqual(text_of({"content": "contenido"}), "contenido")
        self.assertEqual(text_of(None), "")


if __name__ == "__main__":
    unittest.main()

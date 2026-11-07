"""Tests del selector de formatos."""

from __future__ import annotations

import unittest

from ytpremiun_vip.errors import ExtractionError
from ytpremiun_vip.formats import (
    _filter_matches,
    format_table,
    select_format,
)
from ytpremiun_vip.innertube import Format


def make_format(
    itag: int,
    *,
    ext: str = "mp4",
    vcodec: str | None = None,
    acodec: str | None = None,
    height: int | None = None,
    fps: int | None = None,
    bitrate: float | None = None,
    audio_bitrate: float | None = None,
    filesize: int | None = None,
    url: str | None = "https://example.com/v",
    quality_label: str | None = None,
) -> Format:
    has_video = vcodec is not None
    has_audio = acodec is not None
    if quality_label is None and has_video and height:
        quality_label = f"{height}p"
    return Format(
        itag=itag,
        url=url or "",
        mime_type="video/mp4" if has_video else "audio/mp4",
        ext=ext,
        vcodec=vcodec,
        acodec=acodec,
        width=None,
        height=height,
        fps=fps,
        bitrate=bitrate,
        audio_bitrate=audio_bitrate,
        quality_label=quality_label,
        audio_quality=None,
        filesize=filesize,
        duration=60.0,
        has_video=has_video,
        has_audio=has_audio,
        is_progressive=has_video and has_audio,
        source_client="android",
    )


def sample_formats() -> list[Format]:
    return [
        make_format(
            18, ext="mp4", vcodec="avc1.42001E", acodec="mp4a.40.2",
            height=360, fps=30, bitrate=500_000, filesize=3_000_000,
        ),
        make_format(
            22, ext="mp4", vcodec="avc1.64001F", acodec="mp4a.40.2",
            height=720, fps=30, bitrate=2_000_000,
        ),
        make_format(
            137, ext="mp4", vcodec="avc1.640028", height=1080, fps=30,
            bitrate=4_000_000,
        ),
        make_format(
            248, ext="webm", vcodec="vp9", height=1080, fps=30,
            bitrate=3_500_000,
        ),
        make_format(
            140, ext="m4a", acodec="mp4a.40.2", audio_bitrate=128_000,
            bitrate=128_000,
        ),
        make_format(
            251, ext="webm", acodec="opus", audio_bitrate=160_000,
            bitrate=160_000,
        ),
    ]


class SelectionTests(unittest.TestCase):
    def test_default_prefers_avc_and_m4a(self):
        selection = select_format(sample_formats(), audio_ext_pref="m4a")
        self.assertIsNone(selection.progressive)
        self.assertIsNotNone(selection.video)
        self.assertIsNotNone(selection.audio)
        assert selection.video is not None and selection.audio is not None
        self.assertEqual(selection.video.itag, 137)
        self.assertEqual(selection.audio.itag, 140)
        self.assertTrue(selection.requires_merge)

    def test_default_without_audio_preference_picks_best_bitrate(self):
        selection = select_format(sample_formats())
        assert selection.audio is not None
        self.assertEqual(selection.audio.itag, 251)

    def test_best_prefers_progressive_and_highest(self):
        # Regresión: antes el orden invertido elegía la peor calidad.
        selection = select_format(sample_formats(), "best")
        self.assertIsNotNone(selection.progressive)
        assert selection.progressive is not None
        self.assertEqual(selection.progressive.itag, 22)

    def test_worst_picks_lowest(self):
        selection = select_format(sample_formats(), "worst")
        self.assertIsNotNone(selection.primary)
        assert selection.primary is not None
        self.assertEqual(selection.primary.itag, 18)

    def test_height_filter(self):
        selection = select_format(sample_formats(), "bv*[height<=720]+ba")
        assert selection.progressive is not None
        self.assertEqual(selection.progressive.itag, 22)

    def test_itag_combination(self):
        selection = select_format(sample_formats(), "137+140")
        assert selection.video is not None and selection.audio is not None
        self.assertEqual(selection.video.itag, 137)
        self.assertEqual(selection.audio.itag, 140)

    def test_single_itag_audio(self):
        selection = select_format(sample_formats(), "251")
        assert selection.audio is not None
        self.assertEqual(selection.audio.itag, 251)
        self.assertIsNone(selection.video)

    def test_audio_only_bestaudio(self):
        selection = select_format(
            sample_formats(), audio_only=True, audio_ext_pref="m4a"
        )
        assert selection.audio is not None
        self.assertEqual(selection.audio.itag, 140)
        self.assertFalse(selection.video)

    def test_worstaudio(self):
        selection = select_format(sample_formats(), "worstaudio", audio_only=True)
        assert selection.audio is not None
        self.assertEqual(selection.audio.itag, 140)

    def test_alternative_falls_back(self):
        selection = select_format(
            sample_formats(), "999+bv*/bv*+ba", audio_ext_pref="m4a"
        )
        assert selection.video is not None
        self.assertEqual(selection.video.itag, 137)

    def test_no_match_raises(self):
        with self.assertRaises(ExtractionError):
            select_format(sample_formats(), "formato-inventado")

    def test_no_downloadable_formats_raises(self):
        formats = [make_format(18, vcodec="avc1", acodec="mp4a", url=None)]
        with self.assertRaises(ExtractionError):
            select_format(formats)

    def test_empty_list_raises(self):
        with self.assertRaises(ExtractionError):
            select_format([])


class FilterTests(unittest.TestCase):
    def test_numeric_and_text_filters(self):
        fmt = sample_formats()[2]  # 137, 1080p, avc1
        self.assertTrue(_filter_matches(fmt, "height", ">=", "1080"))
        self.assertFalse(_filter_matches(fmt, "height", "<", "1080"))
        self.assertTrue(_filter_matches(fmt, "ext", "=", "mp4"))
        self.assertTrue(_filter_matches(fmt, "vcodec", "^=", "avc"))
        self.assertTrue(_filter_matches(fmt, "filesize", ">", "1"))
        self.assertFalse(_filter_matches(fmt, "campo", "=", "x"))

    def test_missing_value_does_not_match(self):
        audio = sample_formats()[4]
        self.assertFalse(_filter_matches(audio, "height", ">", "0"))
        self.assertTrue(_filter_matches(audio, "acodec", "*=", "mp4a"))


class FormatTableTests(unittest.TestCase):
    def test_table_contains_rows(self):
        table = format_table(sample_formats())
        self.assertIn("ID", table)
        self.assertIn("TIPO", table)
        self.assertIn("137", table)
        self.assertIn("1080p", table)
        self.assertIn("audio", table)
        self.assertEqual(len(table.splitlines()), len(sample_formats()) + 2)


if __name__ == "__main__":
    unittest.main()

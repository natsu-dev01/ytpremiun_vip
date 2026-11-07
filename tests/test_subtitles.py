"""Tests de subtítulos: parseo, conversión y selección."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ytpremiun_vip.innertube import CaptionTrack
from ytpremiun_vip.subtitles import (
    Cue,
    _language_matches,
    cues_to_srt,
    cues_to_vtt,
    download_subtitle,
    parse_timedtext,
    select_tracks,
    subtitle_path,
)


class ParseTests(unittest.TestCase):
    def test_xml_transcript(self):
        payload = (
            '<transcript><text start="0" dur="1.5">Hola &amp; adiós</text>'
            '<text start="2" dur="1">Mundo</text></transcript>'
        )
        cues = parse_timedtext(payload)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0].start, 0.0)
        self.assertAlmostEqual(cues[0].end, 1.5)
        self.assertEqual(cues[0].text, "Hola & adiós")
        self.assertAlmostEqual(cues[1].start, 2.0)

    def test_xml_srv3_style(self):
        payload = '<timedtext><body><p t="1000" d="2000">Hola</p></body></timedtext>'
        cues = parse_timedtext(payload)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].start, 1.0)
        self.assertAlmostEqual(cues[0].end, 3.0)
        self.assertEqual(cues[0].text, "Hola")

    def test_json3(self):
        payload = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 500,
                        "dDurationMs": 1500,
                        "segs": [{"utf8": "Ho"}, {"utf8": "la"}],
                    },
                    {"tStartMs": 3000, "dDurationMs": 1000},
                ]
            }
        )
        cues = parse_timedtext(payload)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "Hola")
        self.assertAlmostEqual(cues[0].start, 0.5)
        self.assertAlmostEqual(cues[0].end, 2.0)

    def test_vtt_and_srt(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.500\nHola\n\n"
            "00:00:02.000 --> 00:00:03.000\nMundo\n"
        )
        cues = parse_timedtext(vtt)
        self.assertEqual([cue.text for cue in cues], ["Hola", "Mundo"])
        self.assertAlmostEqual(cues[0].end, 1.5)

        srt = "1\n00:00:01,000 --> 00:00:02,000\nTexto\n"
        cues = parse_timedtext(srt)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].text, "Texto")

    def test_empty_payload(self):
        self.assertEqual(parse_timedtext(""), [])
        self.assertEqual(parse_timedtext("   "), [])
        self.assertEqual(parse_timedtext("<transcript></transcript>"), [])

    def test_html_entities_and_zero_width(self):
        payload = '<transcript><text start="0" dur="1">\u200bA&amp;B</text></transcript>'
        cues = parse_timedtext(payload)
        self.assertEqual(cues[0].text, "A&B")


class ConversionTests(unittest.TestCase):
    def test_srt(self):
        cues = [Cue(0.0, 1.5, "Hola"), Cue(2.0, 3.25, "Mundo")]
        text = cues_to_srt(cues)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nHola", text)
        self.assertIn("2\n00:00:02,000 --> 00:00:03,250\nMundo", text)
        self.assertTrue(text.endswith("\n"))

    def test_vtt(self):
        text = cues_to_vtt([Cue(0.0, 1.5, "Hola")])
        self.assertTrue(text.startswith("WEBVTT\n"))
        self.assertIn("00:00:00.000 --> 00:00:01.500", text)

    def test_empty(self):
        self.assertEqual(cues_to_srt([]), "")
        self.assertTrue(cues_to_vtt([]).startswith("WEBVTT"))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            CaptionTrack("en", "English", "https://en", is_auto=False),
            CaptionTrack("es", "Español", "https://es", is_auto=False),
            CaptionTrack("es", "Español (auto)", "https://es-auto", kind="asr", is_auto=True),
            CaptionTrack("fr", "Français", "https://fr-auto", kind="asr", is_auto=True),
        ]

    def test_language_matching(self):
        self.assertTrue(_language_matches("es", "es"))
        self.assertTrue(_language_matches("es-MX", "es"))
        self.assertTrue(_language_matches("es", "es-ES"))
        self.assertFalse(_language_matches("en", "es"))
        self.assertFalse(_language_matches("", "es"))

    def test_manual_only_by_language(self):
        selected = select_tracks(self.tracks, "es", False, None)
        self.assertEqual(
            [(track.language_code, track.is_auto) for track in selected],
            [("es", False)],
        )

    def test_default_language(self):
        selected = select_tracks(self.tracks, None, False, "en")
        self.assertEqual(selected[0].language_code, "en")

    def test_default_falls_back_to_first_track(self):
        selected = select_tracks(self.tracks, None, False, None)
        self.assertEqual(selected[0].language_code, "en")

    def test_all_with_auto(self):
        selected = select_tracks(self.tracks, "all", True, None)
        self.assertEqual(len(selected), 4)
        self.assertEqual(len({(t.language_code, t.is_auto) for t in selected}), 4)

    def test_auto_only_when_requested(self):
        selected = select_tracks(self.tracks, "fr", False, None)
        self.assertEqual(selected, [])
        selected = select_tracks(self.tracks, "fr", True, None)
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0].is_auto)

    def test_manual_and_auto_both_selected(self):
        selected = select_tracks(self.tracks, "es", True, None)
        self.assertEqual(len(selected), 2)
        self.assertFalse(selected[0].is_auto)
        self.assertTrue(selected[1].is_auto)

    def test_no_tracks(self):
        self.assertEqual(select_tracks([], "all", True, None), [])

    def test_subtitle_path(self):
        base = Path("videos") / "Titulo [id]"
        manual = CaptionTrack("es", "Español", "https://es")
        auto = CaptionTrack("es", "Auto", "https://auto", is_auto=True)
        self.assertEqual(
            subtitle_path(base, manual, "srt"), Path("videos") / "Titulo [id].es.srt"
        )
        self.assertEqual(
            subtitle_path(base, auto, "vtt"),
            Path("videos") / "Titulo [id].es.auto.vtt",
        )


class FakeHttp:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def get_bytes(self, url, **kwargs):
        self.calls += 1
        return self.payload


class DownloadTests(unittest.TestCase):
    def test_download_json3_to_srt(self):
        payload = json.dumps(
            {
                "events": [
                    {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hola"}]}
                ]
            }
        ).encode("utf-8")
        http = FakeHttp(payload)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Titulo [id]"
            track = CaptionTrack("es", "Español", "https://es")
            path = download_subtitle(track, http, base, "srt")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertEqual(path.name, "Titulo [id].es.srt")
            self.assertIn("Hola", path.read_text(encoding="utf-8"))
            self.assertEqual(http.calls, 1)

            # No se vuelve a descargar si ya existe.
            again = download_subtitle(track, http, base, "srt")
            self.assertEqual(again, path)
            self.assertEqual(http.calls, 1)

    def test_download_vtt_and_xml(self):
        xml = '<transcript><text start="0" dur="1">Hola</text></transcript>'
        http = FakeHttp(xml.encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "v"
            track = CaptionTrack("en", "English", "https://en", is_auto=True)
            vtt = download_subtitle(track, http, base, "vtt")
            assert vtt is not None
            self.assertTrue(vtt.name.endswith(".en.auto.vtt"))
            self.assertTrue(vtt.read_text(encoding="utf-8").startswith("WEBVTT"))

            raw = download_subtitle(track, http, base, "xml", force=True)
            assert raw is not None
            self.assertEqual(raw.read_text(encoding="utf-8"), xml)
            self.assertEqual(http.calls, 2)

    def test_empty_subtitle_returns_none(self):
        http = FakeHttp(b"<transcript></transcript>")
        with tempfile.TemporaryDirectory() as tmp:
            track = CaptionTrack("es", "Español", "https://es")
            path = download_subtitle(track, http, Path(tmp) / "v", "srt")
            self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()

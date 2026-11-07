"""Tests del parseo de URLs de YouTube."""

from __future__ import annotations

import unittest

from ytpremiun_vip.urls import (
    is_video_id,
    parse_input,
    playlist_url,
    video_url,
)

VIDEO = "jNQXAC9IVRw"


class ParseInputTests(unittest.TestCase):
    def test_raw_video_id(self):
        parsed = parse_input(VIDEO)
        self.assertEqual(parsed.video_id, VIDEO)
        self.assertIsNone(parsed.playlist_id)
        self.assertTrue(parsed.is_video)

    def test_youtu_be(self):
        parsed = parse_input(f"https://youtu.be/{VIDEO}?t=10")
        self.assertEqual(parsed.video_id, VIDEO)

    def test_youtu_be_without_scheme(self):
        parsed = parse_input(f"youtu.be/{VIDEO}")
        self.assertEqual(parsed.video_id, VIDEO)

    def test_watch_with_playlist(self):
        parsed = parse_input(
            f"https://www.youtube.com/watch?v={VIDEO}&list=PLabc123&index=4"
        )
        self.assertEqual(parsed.video_id, VIDEO)
        self.assertEqual(parsed.playlist_id, "PLabc123")
        self.assertTrue(parsed.is_playlist)

    def test_playlist_only(self):
        parsed = parse_input("https://www.youtube.com/playlist?list=PLxyz")
        self.assertIsNone(parsed.video_id)
        self.assertEqual(parsed.playlist_id, "PLxyz")

    def test_empty_list_is_none(self):
        parsed = parse_input(f"https://www.youtube.com/watch?v={VIDEO}&list=")
        self.assertIsNone(parsed.playlist_id)

    def test_shorts_embed_live(self):
        for path in ("shorts", "embed", "live", "v"):
            parsed = parse_input(f"https://www.youtube.com/{path}/{VIDEO}")
            self.assertEqual(parsed.video_id, VIDEO, path)

    def test_mobile_and_music_hosts(self):
        for host in ("m.youtube.com", "music.youtube.com", "www.youtube.com"):
            parsed = parse_input(f"https://{host}/watch?v={VIDEO}")
            self.assertEqual(parsed.video_id, VIDEO, host)

    def test_nocookie_host(self):
        parsed = parse_input(f"https://www.youtube-nocookie.com/embed/{VIDEO}")
        self.assertEqual(parsed.video_id, VIDEO)

    def test_invalid_inputs(self):
        for raw in ("", "   ", "https://vimeo.com/123", "https://youtube.com/watch?v=corto"):
            with self.assertRaises(ValueError):
                parse_input(raw)

    def test_whitespace_is_stripped(self):
        parsed = parse_input(f"  {VIDEO}  ")
        self.assertEqual(parsed.video_id, VIDEO)


class HelperTests(unittest.TestCase):
    def test_is_video_id(self):
        self.assertTrue(is_video_id(VIDEO))
        self.assertFalse(is_video_id("corto"))
        self.assertFalse(is_video_id(None))
        self.assertFalse(is_video_id("con espacios"))

    def test_builders(self):
        self.assertEqual(
            video_url(VIDEO), f"https://www.youtube.com/watch?v={VIDEO}"
        )
        self.assertEqual(
            playlist_url("PL1"),
            "https://www.youtube.com/playlist?list=PL1",
        )


if __name__ == "__main__":
    unittest.main()

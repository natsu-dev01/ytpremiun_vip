"""Tests de la extracción con la API InnerTube."""

from __future__ import annotations

import unittest

from ytpremiun_vip.errors import ExtractionError, NetworkError, UnsupportedError
from ytpremiun_vip.innertube import (
    CLIENTS,
    InnertubeClient,
    _extract_url,
    _parse_format,
)

VIDEO = "jNQXAC9IVRw"


def raw_audio() -> dict:
    return {
        "itag": 140,
        "url": "https://example.com/audio",
        "mimeType": 'audio/mp4; codecs="mp4a.40.2"',
        "bitrate": 128000,
        "audioBitrate": 128000,
        "audioQuality": "AUDIO_QUALITY_MEDIUM",
        "contentLength": "1000",
    }


def raw_video() -> dict:
    return {
        "itag": 137,
        "url": "https://example.com/video",
        "mimeType": 'video/mp4; codecs="avc1.640028"',
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate": 4_000_000,
        "qualityLabel": "1080p",
        "contentLength": "5000000",
    }


def raw_progressive() -> dict:
    return {
        "itag": 18,
        "url": "https://example.com/prog",
        "mimeType": 'video/mp4; codecs="avc1.42001E, mp4a.40.2"',
        "width": 640,
        "height": 360,
        "fps": 30,
        "bitrate": 500_000,
        "qualityLabel": "360p",
        "contentLength": "100000",
    }


def make_payload(*, formats=None, live=False, status="OK", with_details=True):
    payload = {
        "playabilityStatus": {"status": status, "reason": "motivo"},
        "streamingData": {
            "formats": list(formats if formats is not None else [raw_progressive()]),
            "adaptiveFormats": [raw_video(), raw_audio()],
        },
        "microformat": {
            "playerMicroformatRenderer": {"publishDate": "2005-04-24T00:00:00-07:00"}
        },
        "captions": {
            "playerCaptionsTracklistRenderer": {
                "captionTracks": [
                    {
                        "baseUrl": "https://example.com/subs-es",
                        "languageCode": "es",
                        "name": {"simpleText": "Español"},
                    },
                    {
                        "baseUrl": "https://example.com/subs-auto",
                        "languageCode": "es",
                        "kind": "asr",
                        "name": {"runs": [{"text": "Español (auto)"}]},
                    },
                ]
            }
        },
    }
    if with_details:
        payload["videoDetails"] = {
            "videoId": VIDEO,
            "title": "Me at the zoo",
            "author": "jawed",
            "channelId": "UC1",
            "lengthSeconds": "19",
            "viewCount": "12345",
            "shortDescription": "descripción",
            "keywords": ["zoo", "video"],
            "thumbnail": {"thumbnails": [{"url": "https://img", "width": 120}]},
            "isLive": live,
            "defaultAudioLanguage": "en",
        }
    return payload


class FormatTests(unittest.TestCase):
    def test_audio_format(self):
        fmt = _parse_format(raw_audio(), "android", 60)
        self.assertIsNotNone(fmt)
        assert fmt is not None
        self.assertEqual(fmt.itag, 140)
        self.assertEqual(fmt.ext, "m4a")
        self.assertTrue(fmt.has_audio)
        self.assertFalse(fmt.has_video)
        self.assertEqual(fmt.acodec, "mp4a.40.2")
        self.assertEqual(fmt.audio_quality, "medium")
        self.assertEqual(fmt.resolution, "audio")
        self.assertEqual(fmt.kind, "audio")
        self.assertEqual(fmt.filesize, 1000)
        self.assertEqual(fmt.audio_bitrate, 128000)

    def test_video_only_format(self):
        fmt = _parse_format(raw_video(), "ios", 60)
        assert fmt is not None
        self.assertEqual(fmt.ext, "mp4")
        self.assertTrue(fmt.has_video)
        self.assertFalse(fmt.has_audio)
        self.assertEqual(fmt.vcodec, "avc1.640028")
        self.assertIsNone(fmt.acodec)
        self.assertEqual(fmt.resolution, "1080p")
        self.assertEqual(fmt.kind, "video")
        self.assertEqual(fmt.source_client, "ios")

    def test_progressive_format(self):
        fmt = _parse_format(raw_progressive(), "android", 60)
        assert fmt is not None
        self.assertTrue(fmt.has_video)
        self.assertTrue(fmt.has_audio)
        self.assertTrue(fmt.is_progressive)
        self.assertEqual(fmt.vcodec, "avc1.42001E")
        self.assertEqual(fmt.acodec, "mp4a.40.2")
        self.assertEqual(fmt.kind, "video+audio")

    def test_fps_from_quality_label(self):
        raw = raw_video()
        raw.pop("fps")
        raw["qualityLabel"] = "720p60"
        fmt = _parse_format(raw, "android", 60)
        assert fmt is not None
        self.assertEqual(fmt.fps, 60)
        self.assertEqual(fmt.height, 1080)  # height explícito tiene prioridad

    def test_height_from_quality_label(self):
        raw = raw_video()
        raw.pop("height")
        raw.pop("width")
        fmt = _parse_format(raw, "android", 60)
        assert fmt is not None
        self.assertEqual(fmt.height, 1080)

    def test_unknown_mime_without_video_hints(self):
        raw = {"itag": 1, "url": "https://x", "mimeType": "application/octet-stream"}
        self.assertIsNone(_parse_format(raw, "android", 60))

    def test_missing_url_returns_none(self):
        raw = raw_audio()
        raw.pop("url")
        self.assertIsNone(_parse_format(raw, "android", 60))


class CipherTests(unittest.TestCase):
    def test_direct_url(self):
        self.assertEqual(_extract_url({"url": "https://x"}), "https://x")

    def test_cipher_with_signature_is_rejected(self):
        cipher = "s=ABC&url=https%3A%2F%2Fexample.com%2Fv"
        self.assertIsNone(_extract_url({"signatureCipher": cipher}))

    def test_cipher_without_signature(self):
        cipher = "url=https%3A%2F%2Fexample.com%2Fv"
        self.assertEqual(
            _extract_url({"signatureCipher": cipher}), "https://example.com/v"
        )

    def test_cipher_url_param_key(self):
        cipher = "url=https%3A%2F%2Fexample.com%2Fa%3Fb%3D1"
        self.assertEqual(
            _extract_url({"cipher": cipher}), "https://example.com/a?b=1"
        )

    def test_no_url(self):
        self.assertIsNone(_extract_url({}))


def parse_player_payload(payload, video_id=VIDEO, client="android"):
    # _parse_player es un método; el cliente no necesita HTTP para parsear.
    return InnertubeClient(None)._parse_player(payload, video_id, client)


class ParsePlayerTests(unittest.TestCase):
    def test_full_payload(self):
        info = parse_player_payload(make_payload(), VIDEO, "android")
        self.assertEqual(info.id, VIDEO)
        self.assertEqual(info.title, "Me at the zoo")
        self.assertEqual(info.author, "jawed")
        self.assertEqual(info.channel_id, "UC1")
        self.assertEqual(info.length_seconds, 19)
        self.assertEqual(info.view_count, 12345)
        self.assertEqual(info.upload_date, "20050424")
        self.assertEqual(info.default_audio_language, "en")
        self.assertEqual(info.source_client, "android")
        self.assertEqual(info.webpage_url, f"https://www.youtube.com/watch?v={VIDEO}")
        self.assertEqual(len(info.formats), 3)
        self.assertEqual(len(info.subtitles), 2)
        self.assertFalse(info.subtitles[0].is_auto)
        self.assertTrue(info.subtitles[1].is_auto)
        self.assertEqual(info.subtitles[1].name, "Español (auto)")

    def test_live_raises(self):
        with self.assertRaises(UnsupportedError):
            parse_player_payload(make_payload(live=True), VIDEO, "android")

    def test_missing_details(self):
        with self.assertRaises(ExtractionError):
            parse_player_payload(make_payload(with_details=False), VIDEO, "android")

    def test_no_formats(self):
        payload = make_payload()
        payload["streamingData"] = {"formats": [], "adaptiveFormats": []}
        with self.assertRaises(ExtractionError):
            parse_player_payload(payload, VIDEO, "android")

    def test_to_dict(self):
        info = parse_player_payload(make_payload(), VIDEO, "android")
        data = info.to_dict()
        self.assertEqual(data["id"], VIDEO)
        self.assertIn("formats", data)
        self.assertEqual(data["webpage_url"], f"https://www.youtube.com/watch?v={VIDEO}")


class FakeHttp:
    def __init__(self, responses, page=""):
        self.responses = list(responses)
        self.calls = 0
        self.page = page
        self.get_calls = 0
        self.last_headers = None

    def get_text(self, url, **kwargs):
        self.get_calls += 1
        return self.page

    def post_json(self, url, payload, **kwargs):
        self.calls += 1
        self.last_headers = kwargs.get("headers") or {}
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class GetVideoTests(unittest.TestCase):
    def test_falls_back_to_next_client(self):
        http = FakeHttp([NetworkError("caída"), make_payload()])
        info = InnertubeClient(http).get_video(VIDEO)
        self.assertEqual(info.source_client, "android")
        self.assertEqual(http.calls, 2)

    def test_all_clients_fail(self):
        error = {"playabilityStatus": {"status": "ERROR", "reason": "x"}}
        http = FakeHttp([error] * len(CLIENTS))
        with self.assertRaises(ExtractionError) as ctx:
            InnertubeClient(http).get_video(VIDEO)
        self.assertIn("No se pudo extraer", str(ctx.exception))
        self.assertEqual(http.calls, len(CLIENTS))

    def test_login_hint(self):
        blocked = {
            "playabilityStatus": {
                "status": "LOGIN_REQUIRED",
                "reason": "Sign in to confirm you are not a bot",
            }
        }
        http = FakeHttp([blocked] * len(CLIENTS))
        with self.assertRaises(ExtractionError) as ctx:
            InnertubeClient(http).get_video(VIDEO)
        self.assertIn("--cookies", str(ctx.exception))

    def test_sends_visitor_data_and_client_headers(self):
        page = '<script>var ytcfg = {"VISITOR_DATA":"abc123"};</script>'
        http = FakeHttp([make_payload()], page=page)
        InnertubeClient(http)._player(VIDEO, CLIENTS[0])
        self.assertEqual(http.get_calls, 1)
        self.assertEqual(http.last_headers["X-Goog-Visitor-Id"], "abc123")
        self.assertEqual(http.last_headers["X-Youtube-Client-Name"], "101")
        self.assertEqual(http.last_headers["X-Youtube-Client-Version"], "1.02")

    def test_visitor_data_is_fetched_once(self):
        http = FakeHttp([], page='{"VISITOR_DATA":"abc123"}')
        client = InnertubeClient(http)
        self.assertEqual(client._ensure_visitor_data(), "abc123")
        self.assertEqual(client._ensure_visitor_data(), "abc123")
        self.assertEqual(http.get_calls, 1)

    def test_no_visitor_header_without_visitor_data(self):
        http = FakeHttp([make_payload()], page="<html></html>")
        InnertubeClient(http)._player(VIDEO, CLIENTS[0])
        self.assertNotIn("X-Goog-Visitor-Id", http.last_headers)

    def test_unsupported_is_not_retried(self):
        http = FakeHttp([make_payload(live=True)])
        with self.assertRaises(UnsupportedError):
            InnertubeClient(http).get_video(VIDEO)
        self.assertEqual(http.calls, 1)


if __name__ == "__main__":
    unittest.main()

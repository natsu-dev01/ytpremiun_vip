"""Tests de lectura de playlists."""

from __future__ import annotations

import json
import unittest

from ytpremiun_vip.errors import ExtractionError, NetworkError
from ytpremiun_vip.playlist import (
    PlaylistClient,
    _collect_entries,
    _find_continuation,
    _playlist_title,
)


def page(*video_ids: str, title: str | None = None, token: str | None = None):
    items = []
    for index, video_id in enumerate(video_ids):
        items.append(
            {
                "lockupViewModel": {
                    "contentId": video_id,
                    "metadata": {
                        "lockupMetadataViewModel": {
                            "title": {"content": f"Video {video_id}"}
                        }
                    },
                }
            }
        )
    data = {
        "contents": {
            "items": items,
        }
    }
    if title is not None:
        data["metadata"] = {
            "playlistMetadataRenderer": {"title": title}
        }
    if token is not None:
        data["contents"]["continuation"] = {
            "continuationItemRenderer": {
                "continuationEndpoint": {
                    "continuationCommand": {"token": token}
                }
            }
        }
    return data


def html_with(data: dict) -> str:
    return (
        "<html><script>var ytInitialData = "
        + json.dumps(data)
        + ";</script></html>"
    )


class StructureTests(unittest.TestCase):
    def test_collect_entries_lockup_and_renderer(self):
        data = {
            "a": {
                "lockupViewModel": {
                    "contentId": "jNQXAC9IVRw",
                    "metadata": {
                        "lockupMetadataViewModel": {
                            "title": {"content": "Me at the zoo"}
                        }
                    },
                }
            },
            "b": {
                "playlistVideoRenderer": {
                    "videoId": "dQw4w9WgXcQ",
                    "title": {"runs": [{"text": "Never Gonna"}]},
                }
            },
            "c": {"lockupViewModel": {"contentId": "invalido"}},
        }
        self.assertEqual(
            _collect_entries(data),
            [
                ("jNQXAC9IVRw", "Me at the zoo"),
                ("dQw4w9WgXcQ", "Never Gonna"),
            ],
        )

    def test_playlist_title(self):
        data = page(title="Mi lista")
        self.assertEqual(_playlist_title(data), "Mi lista")
        self.assertEqual(_playlist_title({}), "")

    def test_find_continuation(self):
        data = page("jNQXAC9IVRw", token="TOKEN123")
        self.assertEqual(_find_continuation(data), "TOKEN123")
        self.assertIsNone(_find_continuation(page("jNQXAC9IVRw")))


class FakeHttp:
    def __init__(self, text: str, pages=None, get_error=None, post_errors=None):
        self.text = text
        self.pages = list(pages or [])
        self.get_error = get_error
        self.post_errors = list(post_errors or [])
        self.requests = 0

    def get_text(self, url, **kwargs):
        self.requests += 1
        if self.get_error:
            raise self.get_error
        return self.text

    def post_json(self, url, payload, **kwargs):
        self.requests += 1
        if self.post_errors:
            raise self.post_errors.pop(0)
        return self.pages.pop(0)


class FetchTests(unittest.TestCase):
    def test_fetch_follows_continuation_and_dedupes(self):
        first = page("jNQXAC9IVRw", title="Lista", token="T1")
        second = page("dQw4w9WgXcQ", "jNQXAC9IVRw")
        client = PlaylistClient(FakeHttp(html_with(first), pages=[second]))

        info = client.fetch("PL123")

        self.assertEqual(info.id, "PL123")
        self.assertEqual(info.title, "Lista")
        self.assertEqual(
            [entry.video_id for entry in info.entries],
            ["jNQXAC9IVRw", "dQw4w9WgXcQ"],
        )
        self.assertEqual([entry.index for entry in info.entries], [1, 2])
        self.assertEqual(info.entries[0].url, "https://www.youtube.com/watch?v=jNQXAC9IVRw")
        self.assertIsNone(info.warning)

    def test_fetch_limits_items(self):
        first = page("jNQXAC9IVRw", "dQw4w9WgXcQ", title="Lista", token="T1")
        http = FakeHttp(html_with(first), pages=[page("aaaaaaaaaaa")])
        info = PlaylistClient(http).fetch("PL123", max_items=1)
        self.assertEqual(len(info.entries), 1)
        self.assertEqual(http.requests, 1)

    def test_fetch_empty_raises(self):
        client = PlaylistClient(FakeHttp(html_with(page(title="Vacía"))))
        with self.assertRaises(ExtractionError):
            client.fetch("PL123")

    def test_fetch_network_error_raises(self):
        client = PlaylistClient(FakeHttp("", get_error=NetworkError("caída")))
        with self.assertRaises(ExtractionError):
            client.fetch("PL123")

    def test_bad_html_raises(self):
        client = PlaylistClient(FakeHttp("<html>sin datos</html>"))
        with self.assertRaises(ExtractionError):
            client.fetch("PL123")

    def test_continuation_failure_keeps_first_page(self):
        first = page("jNQXAC9IVRw", title="Lista", token="T1")
        client = PlaylistClient(
            FakeHttp(html_with(first), post_errors=[NetworkError("timeout")])
        )
        info = client.fetch("PL123")
        self.assertEqual(len(info.entries), 1)
        self.assertIsNotNone(info.warning)


if __name__ == "__main__":
    unittest.main()

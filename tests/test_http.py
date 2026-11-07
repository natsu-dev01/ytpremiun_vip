"""Tests del cliente HTTP: cookies, respuestas y descargas reanudables."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from ytpremiun_vip.errors import DownloadError, NetworkError
from ytpremiun_vip.http import HttpClient, _content_range_total, load_netscape_cookies


class ContentRangeTests(unittest.TestCase):
    def test_total(self):
        self.assertEqual(
            _content_range_total("bytes 0-1023/7118685"), 7118685
        )
        self.assertIsNone(_content_range_total("bytes 0-1023/*"))
        self.assertIsNone(_content_range_total(None))
        self.assertIsNone(_content_range_total("basura"))


class CookieTests(unittest.TestCase):
    def test_load_netscape_cookies(self):
        content = (
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tSID\tvalor123\n"
            "linea-incompleta\n"
            "\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text(content, encoding="utf-8")
            session = requests.Session()
            self.assertEqual(load_netscape_cookies(session, path), 1)
            self.assertEqual(session.cookies.get("SID"), "valor123")

    def test_missing_cookie_file(self):
        with self.assertRaises(FileNotFoundError):
            load_netscape_cookies(requests.Session(), "no-existe.txt")

    def test_client_loads_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text(
                ".youtube.com\tTRUE\t/\tTRUE\t9999999999\tPSID\tx1\n",
                encoding="utf-8",
            )
            client = HttpClient(cookies=path)
            self.assertEqual(client.session.cookies.get("PSID"), "x1")


def make_response(*, status=200, content=b"", json_data=None, headers=None):
    response = Mock()
    response.status_code = status
    response.content = content
    response.headers = headers or {}
    response.raise_for_status = Mock()
    if json_data is not None:
        response.json.return_value = json_data
    return response


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient(retries=0, timeout=20)
        self.client.session.request = Mock()

    def test_get_text_and_bytes(self):
        self.client.session.request.return_value = make_response(
            content="hola".encode("utf-8")
        )
        self.assertEqual(self.client.get_text("https://x"), "hola")
        self.assertEqual(self.client.get_bytes("https://x"), b"hola")

    def test_post_json(self):
        self.client.session.request.return_value = make_response(
            json_data={"ok": True}
        )
        self.assertEqual(
            self.client.post_json("https://x", {"a": 1}), {"ok": True}
        )

    def test_http_error_becomes_network_error(self):
        response = make_response()
        response.raise_for_status.side_effect = requests.HTTPError("403")
        self.client.session.request.return_value = response
        with self.assertRaises(NetworkError):
            self.client.get_text("https://x")

    def test_invalid_json(self):
        response = make_response()
        response.json.side_effect = ValueError("no json")
        self.client.session.request.return_value = response
        with self.assertRaises(NetworkError):
            self.client.post_json("https://x", {})

    def test_connection_error(self):
        self.client.session.request.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(NetworkError):
            self.client.get_text("https://x")

    def test_timeout_tuple(self):
        self.assertEqual(self.client._timeout(), (20, 30))


class FakeStreamResponse:
    def __init__(self, *, status=200, chunks=(), headers=None):
        self.status_code = status
        self._chunks = list(chunks)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=0):
        yield from self._chunks


class StreamDownloadTests(unittest.TestCase):
    def setUp(self):
        self.client = HttpClient(retries=0, timeout=20)

    def test_download_writes_file_and_reports_progress(self):
        self.client.session.get = Mock(
            return_value=FakeStreamResponse(
                chunks=(b"abc", b"def"), headers={"Content-Length": "6"}
            )
        )
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            size = self.client.stream_download(
                "https://x", dest, progress=lambda d, t: calls.append((d, t))
            )
            self.assertEqual(size, 6)
            self.assertEqual(dest.read_bytes(), b"abcdef")
            self.assertFalse(dest.with_name(dest.name + ".part").exists())
            self.assertEqual(calls[-1], (6, 6))
            headers = self.client.session.get.call_args.kwargs["headers"]
            # Siempre se pide un rango acotado, nunca "bytes=0-".
            self.assertRegex(headers["Range"], r"^bytes=0-\d+$")

    def test_chunked_bounded_ranges(self):
        responses = [
            FakeStreamResponse(
                status=206,
                chunks=(b"abcd",),
                headers={"Content-Range": "bytes 0-3/10"},
            ),
            FakeStreamResponse(
                status=206,
                chunks=(b"efgh",),
                headers={"Content-Range": "bytes 4-7/10"},
            ),
            FakeStreamResponse(
                status=206,
                chunks=(b"ij",),
                headers={"Content-Range": "bytes 8-9/10"},
            ),
        ]
        self.client.session.get = Mock(side_effect=responses)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            size = self.client.stream_download(
                "https://x", dest, expected_size=10, range_size=4
            )
            self.assertEqual(size, 10)
            self.assertEqual(dest.read_bytes(), b"abcdefghij")
            ranges = [
                call.kwargs["headers"]["Range"]
                for call in self.client.session.get.call_args_list
            ]
            self.assertEqual(ranges, ["bytes=0-3", "bytes=4-7", "bytes=8-9"])

    def test_unknown_total_ends_with_short_chunk(self):
        responses = [
            FakeStreamResponse(
                status=206,
                chunks=(b"abcd",),
                headers={"Content-Range": "bytes 0-3/*"},
            ),
            FakeStreamResponse(
                status=206,
                chunks=(b"ef",),
                headers={"Content-Range": "bytes 4-5/*"},
            ),
        ]
        self.client.session.get = Mock(side_effect=responses)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            size = self.client.stream_download(
                "https://x", dest, range_size=4
            )
            self.assertEqual(size, 6)
            self.assertEqual(dest.read_bytes(), b"abcdef")
            self.assertEqual(self.client.session.get.call_count, 2)

    def test_resume_with_range(self):
        self.client.session.get = Mock(
            return_value=FakeStreamResponse(
                status=206, chunks=(b"def",), headers={"Content-Length": "3"}
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(b"abc")
            size = self.client.stream_download("https://x", dest)
            self.assertEqual(size, 6)
            self.assertEqual(dest.read_bytes(), b"abcdef")
            headers = self.client.session.get.call_args.kwargs["headers"]
            self.assertTrue(headers["Range"].startswith("bytes=3-"))

    def test_range_not_satisfiable(self):
        self.client.session.get = Mock(return_value=FakeStreamResponse(status=416))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(b"12345")
            size = self.client.stream_download("https://x", dest)
            self.assertEqual(size, 5)
            self.assertEqual(dest.read_bytes(), b"12345")

    def test_expected_size_already_complete(self):
        self.client.session.get = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "archivo.bin"
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(b"12345")
            size = self.client.stream_download("https://x", dest, expected_size=5)
            self.assertEqual(size, 5)
            self.assertEqual(dest.read_bytes(), b"12345")
            self.client.session.get.assert_not_called()

    def test_forbidden_is_not_retried(self):
        self.client.session.get = Mock(return_value=FakeStreamResponse(status=403))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadError):
                self.client.stream_download("https://x", Path(tmp) / "a.bin")
            self.assertEqual(self.client.session.get.call_count, 1)

    def test_incomplete_download_fails(self):
        self.client.session.get = Mock(
            return_value=FakeStreamResponse(
                chunks=(b"ab",), headers={"Content-Length": "2"}
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DownloadError):
                self.client.stream_download(
                    "https://x", Path(tmp) / "a.bin", expected_size=10
                )


if __name__ == "__main__":
    unittest.main()

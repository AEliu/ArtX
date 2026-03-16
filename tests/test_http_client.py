from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from googleart_download.download.http_client import HttpClient
from googleart_download.errors import DownloadError
from googleart_download.models import RetryConfig


class HttpClientTests(unittest.TestCase):
    def test_fetch_bytes_retries_retryable_http_status(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(503, request=request)
            return httpx.Response(200, request=request, content=b"ok")

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with (
            patch("googleart_download.download.http_client.time.sleep"),
            HttpClient(
                retry_config=RetryConfig(attempts=2, backoff_base_seconds=0),
                client=client,
            ) as http_client,
        ):
            payload = http_client.fetch_bytes("https://example.com/image", description="tile")

        self.assertEqual(payload, b"ok")
        self.assertEqual(attempts["count"], 2)

    def test_fetch_bytes_raises_on_non_retryable_http_status(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with HttpClient(retry_config=RetryConfig(attempts=3, backoff_base_seconds=0), client=client) as http_client:
            with self.assertRaisesRegex(DownloadError, r"tile failed: https://example\.com/image -> HTTP 404"):
                http_client.fetch_bytes("https://example.com/image", description="tile")

    def test_fetch_bytes_retries_request_error(self) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise httpx.ConnectError("connection reset", request=request)
            return httpx.Response(200, request=request, content=b"tile")

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with (
            patch("googleart_download.download.http_client.time.sleep"),
            HttpClient(
                retry_config=RetryConfig(attempts=2, backoff_base_seconds=0),
                client=client,
            ) as http_client,
        ):
            payload = http_client.fetch_bytes("https://example.com/tile", description="tile x=0 y=0")

        self.assertEqual(payload, b"tile")
        self.assertEqual(attempts["count"], 2)

    def test_fetch_text_decodes_response_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request, content="hello".encode("utf-8"))

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with HttpClient(retry_config=RetryConfig(attempts=1, backoff_base_seconds=0), client=client) as http_client:
            payload = http_client.fetch_text("https://example.com/page", description="page")

        self.assertEqual(payload, "hello")

    def test_fetch_text_with_url_returns_final_response_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, request=request, content="hello".encode("utf-8"))

        client = httpx.Client(transport=httpx.MockTransport(handler))

        with HttpClient(retry_config=RetryConfig(attempts=1, backoff_base_seconds=0), client=client) as http_client:
            payload, final_url = http_client.fetch_text_with_url("https://g.co/arts/example", description="page")

        self.assertEqual(payload, "hello")
        self.assertEqual(final_url, "https://g.co/arts/example")


if __name__ == "__main__":
    unittest.main()

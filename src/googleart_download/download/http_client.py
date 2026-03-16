from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from ..errors import DownloadError
from ..logging_utils import get_logger
from ..models import RetryConfig
from .constants import REQUEST_TIMEOUT
from .transport import TransportConfig, retry_delay_seconds, should_retry_http

ResponseValue = TypeVar("ResponseValue")


class HttpClient:
    def __init__(
        self,
        retry_config: RetryConfig,
        timeout: int = REQUEST_TIMEOUT,
        proxy_url: str | None = None,
        client: httpx.Client | None = None,
        on_retry: Callable[[str, str, int, str], None] | None = None,
    ) -> None:
        self.transport_config = TransportConfig(retry_config=retry_config, timeout=timeout, proxy_url=proxy_url)
        self.retry_config = retry_config
        self.timeout = timeout
        self.proxy_url = proxy_url
        self.logger = get_logger()
        self.on_retry = on_retry
        self._owns_client = client is None
        self.client = client or httpx.Client(**self.transport_config.sync_client_kwargs())

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def fetch_bytes(self, url: str, *, description: str) -> bytes:
        return self.fetch_bytes_with_url(url, description=description)[0]

    def fetch_bytes_with_url(self, url: str, *, description: str) -> tuple[bytes, str]:
        return self._request_with_retries(
            url,
            description=description,
            action=lambda request_url: self._extract_content_and_url(self.client.get(request_url)),
        )

    def fetch_text(self, url: str, *, description: str) -> str:
        return self.fetch_text_with_url(url, description=description)[0]

    def fetch_text_with_url(self, url: str, *, description: str) -> tuple[str, str]:
        content, final_url = self.fetch_bytes_with_url(url, description=description)
        return content.decode("utf-8", errors="ignore"), final_url

    def resolve_url(self, url: str, *, description: str) -> str:
        return self._request_with_retries(
            url,
            description=description,
            action=self._stream_final_url,
        )

    def _request_with_retries(
        self,
        url: str,
        *,
        description: str,
        action: Callable[[str], ResponseValue],
    ) -> ResponseValue:
        last_error: Exception | None = None

        for attempt in range(1, self.retry_config.attempts + 1):
            try:
                return action(url)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if not should_retry_http(self.retry_config, status_code=status_code, attempt=attempt):
                    raise DownloadError(f"{description} failed: {url} -> HTTP {status_code}") from exc
                self._sleep_before_retry(description, url, attempt, f"HTTP {status_code}")
            except httpx.RequestError as exc:
                last_error = exc
                reason = str(exc) or exc.__class__.__name__
                if attempt >= self.retry_config.attempts:
                    raise DownloadError(f"{description} failed: {url} -> {reason}") from exc
                self._sleep_before_retry(description, url, attempt, reason)

        raise DownloadError(f"{description} failed after retries: {url} -> {last_error}")

    def _extract_content_and_url(self, response: httpx.Response) -> tuple[bytes, str]:
        response.raise_for_status()
        return response.content, str(response.url)

    def _stream_final_url(self, url: str) -> str:
        with self.client.stream("GET", url) as response:
            response.raise_for_status()
            return str(response.url)

    def _sleep_before_retry(self, description: str, url: str, attempt: int, reason: str) -> None:
        delay = retry_delay_seconds(self.retry_config, attempt=attempt)
        if self.on_retry is not None:
            self.on_retry(description, url, attempt + 1, reason)
        self.logger.warning(
            "Retrying %s (attempt %s/%s) after %ss due to %s: %s",
            description,
            attempt + 1,
            self.retry_config.attempts,
            f"{delay:.2f}",
            reason,
            url,
        )
        time.sleep(delay)


class AsyncHttpClient:
    def __init__(
        self,
        retry_config: RetryConfig,
        timeout: int = REQUEST_TIMEOUT,
        proxy_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        on_retry: Callable[[str, str, int, str], None] | None = None,
    ) -> None:
        self.transport_config = TransportConfig(retry_config=retry_config, timeout=timeout, proxy_url=proxy_url)
        self.retry_config = retry_config
        self.timeout = timeout
        self.proxy_url = proxy_url
        self.logger = get_logger()
        self.on_retry = on_retry
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(**self.transport_config.async_client_kwargs())

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> AsyncHttpClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    async def fetch_bytes(self, url: str, *, description: str) -> bytes:
        content, _ = await self.fetch_bytes_with_url(url, description=description)
        return content

    async def fetch_bytes_with_url(self, url: str, *, description: str) -> tuple[bytes, str]:
        return await self._request_with_retries(
            url,
            description=description,
            action=lambda request_url: self._extract_content_and_url(self.client.get(request_url)),
        )

    async def _request_with_retries(
        self,
        url: str,
        *,
        description: str,
        action: Callable[[str], Awaitable[ResponseValue]],
    ) -> ResponseValue:
        last_error: Exception | None = None

        for attempt in range(1, self.retry_config.attempts + 1):
            try:
                return await action(url)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if not should_retry_http(self.retry_config, status_code=status_code, attempt=attempt):
                    raise DownloadError(f"{description} failed: {url} -> HTTP {status_code}") from exc
                await self._sleep_before_retry(description, url, attempt, f"HTTP {status_code}")
            except httpx.RequestError as exc:
                last_error = exc
                reason = str(exc) or exc.__class__.__name__
                if attempt >= self.retry_config.attempts:
                    raise DownloadError(f"{description} failed: {url} -> {reason}") from exc
                await self._sleep_before_retry(description, url, attempt, reason)

        raise DownloadError(f"{description} failed after retries: {url} -> {last_error}")

    async def _extract_content_and_url(self, awaitable: Awaitable[httpx.Response]) -> tuple[bytes, str]:
        response = await awaitable
        response.raise_for_status()
        return response.content, str(response.url)

    async def _sleep_before_retry(self, description: str, url: str, attempt: int, reason: str) -> None:
        delay = retry_delay_seconds(self.retry_config, attempt=attempt)
        if self.on_retry is not None:
            self.on_retry(description, url, attempt + 1, reason)
        self.logger.warning(
            "Retrying %s (attempt %s/%s) after %ss due to %s: %s",
            description,
            attempt + 1,
            self.retry_config.attempts,
            f"{delay:.2f}",
            reason,
            url,
        )
        await asyncio.sleep(delay)

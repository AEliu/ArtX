from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from ..errors import DownloadError
from ..logging_utils import get_logger
from ..models import RetryConfig
from .constants import REQUEST_TIMEOUT, USER_AGENT


class HttpClient:
    def __init__(
        self,
        retry_config: RetryConfig,
        timeout: int = REQUEST_TIMEOUT,
        client: httpx.Client | None = None,
        on_retry: Callable[[str, str, int, str], None] | None = None,
    ) -> None:
        self.retry_config = retry_config
        self.timeout = timeout
        self.logger = get_logger()
        self.on_retry = on_retry
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )

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
        last_error: Exception | None = None

        for attempt in range(1, self.retry_config.attempts + 1):
            try:
                response = self.client.get(url)
                response.raise_for_status()
                return response.content, str(response.url)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if not self._should_retry_http(status_code, attempt):
                    raise DownloadError(f"{description} failed: {url} -> HTTP {status_code}") from exc
                self._sleep_before_retry(description, url, attempt, f"HTTP {status_code}")
            except httpx.RequestError as exc:
                last_error = exc
                reason = str(exc) or exc.__class__.__name__
                if attempt >= self.retry_config.attempts:
                    raise DownloadError(f"{description} failed: {url} -> {reason}") from exc
                self._sleep_before_retry(description, url, attempt, reason)

        raise DownloadError(f"{description} failed after retries: {url} -> {last_error}")

    def fetch_text(self, url: str, *, description: str) -> str:
        return self.fetch_text_with_url(url, description=description)[0]

    def fetch_text_with_url(self, url: str, *, description: str) -> tuple[str, str]:
        content, final_url = self.fetch_bytes_with_url(url, description=description)
        return content.decode("utf-8", errors="ignore"), final_url

    def resolve_url(self, url: str, *, description: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.retry_config.attempts + 1):
            try:
                with self.client.stream("GET", url) as response:
                    response.raise_for_status()
                    return str(response.url)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if not self._should_retry_http(status_code, attempt):
                    raise DownloadError(f"{description} failed: {url} -> HTTP {status_code}") from exc
                self._sleep_before_retry(description, url, attempt, f"HTTP {status_code}")
            except httpx.RequestError as exc:
                last_error = exc
                reason = str(exc) or exc.__class__.__name__
                if attempt >= self.retry_config.attempts:
                    raise DownloadError(f"{description} failed: {url} -> {reason}") from exc
                self._sleep_before_retry(description, url, attempt, reason)

        raise DownloadError(f"{description} failed after retries: {url} -> {last_error}")

    def _should_retry_http(self, status_code: int, attempt: int) -> bool:
        return attempt < self.retry_config.attempts and status_code in self.retry_config.retry_http_statuses

    def _sleep_before_retry(self, description: str, url: str, attempt: int, reason: str) -> None:
        delay = self.retry_config.backoff_base_seconds * (self.retry_config.backoff_multiplier ** (attempt - 1))
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

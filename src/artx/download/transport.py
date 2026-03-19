from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from ..models import RetryConfig
from .constants import REQUEST_TIMEOUT, USER_AGENT


class ClientKwargs(TypedDict):
    headers: dict[str, str]
    timeout: int
    follow_redirects: bool
    proxy: str | None
    trust_env: bool


@dataclass(frozen=True)
class TransportConfig:
    retry_config: RetryConfig
    timeout: int = REQUEST_TIMEOUT
    proxy_url: str | None = None
    user_agent: str = USER_AGENT

    @property
    def trust_env(self) -> bool:
        return self.proxy_url is None

    def sync_client_kwargs(self) -> ClientKwargs:
        return self._client_kwargs()

    def async_client_kwargs(self) -> ClientKwargs:
        return self._client_kwargs()

    def _client_kwargs(self) -> ClientKwargs:
        return {
            "headers": {"User-Agent": self.user_agent},
            "timeout": self.timeout,
            "follow_redirects": True,
            "proxy": self.proxy_url,
            "trust_env": self.trust_env,
        }


def should_retry_http(retry_config: RetryConfig, *, status_code: int, attempt: int) -> bool:
    return attempt < retry_config.attempts and status_code in retry_config.retry_http_statuses


def retry_delay_seconds(retry_config: RetryConfig, *, attempt: int) -> float:
    return retry_config.backoff_base_seconds * (retry_config.backoff_multiplier ** (attempt - 1))

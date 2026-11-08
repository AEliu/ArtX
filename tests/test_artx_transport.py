from __future__ import annotations

import unittest

from artx.download.constants import REQUEST_TIMEOUT, USER_AGENT
from artx.download.transport import TransportConfig, retry_delay_seconds, should_retry_http
from artx.models import RetryConfig


class TransportTests(unittest.TestCase):
    def test_transport_config_defaults_to_environment_proxy_lookup(self) -> None:
        config = TransportConfig(retry_config=RetryConfig())

        self.assertTrue(config.trust_env)
        self.assertEqual(
            config.sync_client_kwargs(),
            {
                "headers": {"User-Agent": USER_AGENT},
                "timeout": REQUEST_TIMEOUT,
                "follow_redirects": True,
                "proxy": None,
                "trust_env": True,
            },
        )

    def test_transport_config_disables_environment_proxy_lookup_when_proxy_is_explicit(self) -> None:
        config = TransportConfig(retry_config=RetryConfig(), proxy_url="http://127.0.0.1:7890", timeout=12)

        self.assertFalse(config.trust_env)
        self.assertEqual(config.sync_client_kwargs()["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(config.sync_client_kwargs()["timeout"], 12)
        self.assertFalse(config.sync_client_kwargs()["trust_env"])

    def test_should_retry_http_respects_status_list_and_attempt_limit(self) -> None:
        retry_config = RetryConfig(attempts=3, retry_http_statuses=(429, 503))

        self.assertTrue(should_retry_http(retry_config, status_code=503, attempt=1))
        self.assertFalse(should_retry_http(retry_config, status_code=404, attempt=1))
        self.assertFalse(should_retry_http(retry_config, status_code=503, attempt=3))

    def test_retry_delay_seconds_applies_exponential_backoff(self) -> None:
        retry_config = RetryConfig(attempts=3, backoff_base_seconds=0.5, backoff_multiplier=3.0)

        self.assertEqual(retry_delay_seconds(retry_config, attempt=1), 0.5)
        self.assertEqual(retry_delay_seconds(retry_config, attempt=2), 1.5)
        self.assertEqual(retry_delay_seconds(retry_config, attempt=3), 4.5)


if __name__ == "__main__":
    unittest.main()

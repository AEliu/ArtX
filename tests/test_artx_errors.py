from __future__ import annotations

import unittest

from artx.errors import build_error_guidance


class ErrorGuidanceTests(unittest.TestCase):
    def test_network_tile_failure_gets_actionable_guidance(self) -> None:
        message = (
            "tile x=56 y=31 failed: https://example.com/tile -> "
            "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
        )
        guidance = build_error_guidance(message)
        self.assertTrue(any("transient network failure" in line for line in guidance))
        self.assertTrue(any("reused" in line for line in guidance))
        self.assertTrue(any("--retries 5 --retry-backoff 1.0" in line for line in guidance))
        self.assertTrue(any("--workers 16" in line for line in guidance))

    def test_memory_guard_failure_gets_size_guidance(self) -> None:
        guidance = build_error_guidance(
            "image is too large for safe in-memory stitching: requires about 4.4 GiB raw canvas memory"
        )
        self.assertTrue(any("memory safety guard" in line for line in guidance))
        self.assertTrue(any("--size large" in line for line in guidance))
        self.assertTrue(any("bigtiff" in line for line in guidance))


if __name__ == "__main__":
    unittest.main()

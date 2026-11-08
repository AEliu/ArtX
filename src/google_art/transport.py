"""Shared wire protocol and retry policy; scheduling stays in the downloaders."""

from __future__ import annotations

import os

import httpx

from .constants import ACCEPT_IMAGE_HEADER, DEFAULT_USER_AGENT
from .tiles import decrypt_tile_if_needed

DEFAULT_HEADERS = {"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
MAX_ATTEMPTS = 3


def tile_headers(referer: str) -> dict[str, str]:
    return {"Referer": referer, "Accept": ACCEPT_IMAGE_HEADER}


def tile_content(response: httpx.Response) -> bytes:
    response.raise_for_status()
    if "image" not in response.headers.get("content-type", "").lower():
        message = "Received non-image data while downloading tiles (non-image-response)."
        if os.getenv("GOOGLE_ART_DEBUG"):
            message += f" Raw snippet: {response.content[:200]!r}"
        raise RuntimeError(message)
    return decrypt_tile_if_needed(response.content)


def should_retry(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


def retry_delay(attempt: int) -> float:
    return 0.2 * 2**attempt

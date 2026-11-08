"""Synchronous adapter over the shared download plan and image assembler."""

from __future__ import annotations

import time
import warnings
from pathlib import Path
from typing import Callable, Mapping

import httpx

from .assemblers import PillowImageAssembler
from .models import DownloadOptions
from .output import check_output, save_image
from .parser import parse_page, parse_tile_info
from .planning import DownloadPlan, normalize_asset, resolve_output_path
from .progress import DownloadProgress
from .tiles import compute_tile_url
from .transport import DEFAULT_HEADERS, MAX_ATTEMPTS, retry_delay, should_retry, tile_content, tile_headers


class GoogleArtDownloader:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        show_progress: bool = True,
        browser_factory: Callable[[str, Mapping[str, str]], object] | None = None,
    ) -> None:
        if browser_factory is not None:
            warnings.warn(
                "browser_factory is deprecated; browser fallback is no longer supported.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=30.0, headers=DEFAULT_HEADERS)
        self._progress = DownloadProgress(show_progress)

    def __enter__(self) -> GoogleArtDownloader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def download(self, options: DownloadOptions) -> Path:
        page = parse_page(self._fetch_text(normalize_asset(options.asset)))
        tiles = parse_tile_info(self._fetch_text(page.tile_info_url()))
        plan = DownloadPlan.build(options, page, tiles)
        check_output(plan.output_path, options.overwrite)
        assembler = PillowImageAssembler()
        try:
            assembler.begin(plan.canvas_size)
            with self._progress.track(page.name, plan.tile_count) as advance:
                for x, y in plan.coordinates():
                    content = self._fetch_tile(compute_tile_url(page, x, y, plan.level_index), plan.page_url)
                    assembler.paste_tile(x, y, tiles.tile_width, tiles.tile_height, content)
                    advance()
            return save_image(assembler, plan, options)
        finally:
            assembler.close()

    def _fetch_text(self, url: str) -> str:
        response = self._client.get(url)
        response.raise_for_status()
        return response.text

    def _fetch_tile(self, url: str, referer: str) -> bytes:
        for attempt in range(MAX_ATTEMPTS):
            try:
                return tile_content(self._client.get(url, headers=tile_headers(referer)))
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS - 1 or not should_retry(exc):
                    raise
                time.sleep(retry_delay(attempt))
        raise AssertionError("unreachable")

    # Preserve the old path helpers for callers migrating to planning.py.
    _normalize_asset = staticmethod(normalize_asset)
    _resolve_output_path = staticmethod(resolve_output_path)


__all__ = ["GoogleArtDownloader", "DownloadOptions"]

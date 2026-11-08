"""Bounded asynchronous tile scheduling with explicit resource ownership."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

import httpx

from .assemblers import ImageAssembler, pick_assembler
from .concurrency import run_blocking
from .models import AsyncOptions
from .output import check_output, staged_output
from .parser import parse_page, parse_tile_info
from .planning import DownloadPlan, normalize_asset, resolve_output_path
from .progress import DownloadProgress
from .tiles import compute_tile_url
from .transport import DEFAULT_HEADERS, MAX_ATTEMPTS, retry_delay, should_retry, tile_content, tile_headers


class AsyncGoogleArtDownloader:
    """Share one instance within one event loop to share a network budget.

    An injected client belongs to its caller. When net_concurrency is omitted,
    the first download configures the budget; later downloads must agree.
    A supplied reserved_outputs set retains claims for an entire batch.
    """

    def __init__(
        self,
        *,
        show_progress: bool = True,
        client: httpx.AsyncClient | None = None,
        net_concurrency: int | None = None,
        reserved_outputs: set[Path] | None = None,
    ) -> None:
        if net_concurrency is not None and net_concurrency <= 0:
            raise ValueError("net_concurrency must be positive")
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(timeout=30.0, headers=DEFAULT_HEADERS)
        self._net_concurrency = net_concurrency
        self._limiter: asyncio.Semaphore | None = None
        self._outputs = reserved_outputs if reserved_outputs is not None else set()
        self._retain_outputs = reserved_outputs is not None
        self._progress = DownloadProgress(show_progress)

    async def __aenter__(self) -> AsyncGoogleArtDownloader:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _configure(self, options: AsyncOptions) -> None:
        if self._net_concurrency is None:
            self._net_concurrency = options.net_concurrency
        if self._net_concurrency != options.net_concurrency:
            raise ValueError("All downloads on one downloader must use the same net_concurrency")
        if self._limiter is None:
            self._limiter = asyncio.Semaphore(self._net_concurrency)

    async def download(self, options: AsyncOptions) -> Path:
        self._configure(options)
        page = parse_page(await self._fetch_text(normalize_asset(options.asset)))
        tiles = parse_tile_info(await self._fetch_text(page.tile_info_url()))
        plan = DownloadPlan.build(options, page, tiles)
        output_key = plan.output_path.resolve()
        if output_key in self._outputs:
            raise FileExistsError(f"Multiple downloads target the same output: {plan.output_path}")
        check_output(plan.output_path, options.overwrite)
        self._outputs.add(output_key)
        assembler: ImageAssembler | None = None
        try:
            assembler = self._pick_assembler(options, plan)
            await run_blocking(assembler.begin, plan.canvas_size)
            await self._assemble_async(plan, assembler, options)
            with staged_output(plan.output_path, options.overwrite) as temporary:
                await run_blocking(
                    assembler.finalize_save, temporary, *plan.crop_size, *plan.target_size, options.normalized_format()
                )
            return plan.output_path
        finally:
            try:
                if assembler is not None:
                    await run_blocking(assembler.close)
            finally:
                if not self._retain_outputs:
                    self._outputs.remove(output_key)

    async def _get(self, url: str, **kwargs: object) -> httpx.Response:
        assert self._limiter is not None
        async with self._limiter:
            return await self._client.get(url, **kwargs)

    async def _fetch_text(self, url: str) -> str:
        response = await self._get(url)
        response.raise_for_status()
        return response.text

    async def _fetch_tile(self, url: str, referer: str) -> bytes:
        for attempt in range(MAX_ATTEMPTS):
            try:
                return tile_content(await self._get(url, headers=tile_headers(referer)))
            except httpx.HTTPError as exc:
                if attempt == MAX_ATTEMPTS - 1 or not should_retry(exc):
                    raise
                await asyncio.sleep(retry_delay(attempt))
        raise AssertionError("unreachable")

    async def _assemble_async(self, plan: DownloadPlan, assembler: ImageAssembler, options: AsyncOptions) -> None:
        queue: asyncio.Queue[tuple[int, int, bytes] | None] = asyncio.Queue(options.queue_size)
        coordinates = plan.coordinates()
        workers = min(options.per_asset_concurrency, options.net_concurrency, plan.tile_count)

        async def produce() -> None:
            # Advancing this shared iterator has no await, so each coordinate is claimed once.
            for x, y in coordinates:
                url = compute_tile_url(plan.page, x, y, plan.level_index)
                data = await self._fetch_tile(url, plan.page_url)
                await queue.put((x, y, data))
            # Only successful workers send a sentinel. TaskGroup cancels peers on failure.
            await queue.put(None)

        async def consume(advance: Callable[[], None]) -> None:
            finished = 0
            while finished < workers:
                item = await queue.get()
                if item is None:
                    finished += 1
                    continue
                x, y, data = item
                await run_blocking(assembler.paste_tile, x, y, plan.tiles.tile_width, plan.tiles.tile_height, data)
                advance()

        with self._progress.track(plan.page.name, plan.tile_count) as advance:
            async with asyncio.TaskGroup() as group:
                for _ in range(workers):
                    group.create_task(produce())
                group.create_task(consume(advance))

    def _pick_assembler(self, options: AsyncOptions, plan: DownloadPlan) -> ImageAssembler:
        return pick_assembler(options.assembler, plan.canvas_size, plan.tile_count)

    _normalize_asset = staticmethod(normalize_asset)
    _resolve_output_path = staticmethod(resolve_output_path)


__all__ = ["AsyncGoogleArtDownloader", "AsyncOptions"]

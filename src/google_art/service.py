"""Batch orchestration independent of Typer and console presentation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

from .async_downloader import AsyncGoogleArtDownloader
from .models import AsyncOptions
from .planning import is_directory_output


async def download_many(options: Iterable[AsyncOptions], *, jobs: int = 3, show_progress: bool = True) -> list[Path]:
    if jobs <= 0:
        raise ValueError("jobs must be positive")
    requests = list(options)
    if not requests:
        return []
    budgets = {request.net_concurrency for request in requests}
    if len(budgets) != 1:
        raise ValueError("All batch downloads must use the same net_concurrency")
    # Distinct explicit filenames are useful for library callers; reusing one is ambiguous.
    files = [
        Path(request.out_path).resolve()
        for request in requests
        if request.out_path and not is_directory_output(Path(request.out_path))
    ]
    if len(files) != len(set(files)):
        raise ValueError("Multiple assets cannot use the same output file; choose an output directory")
    results: list[Path | None] = [None] * len(requests)
    pending = iter(enumerate(requests))
    async with AsyncGoogleArtDownloader(
        show_progress=show_progress, net_concurrency=requests[0].net_concurrency, reserved_outputs=set()
    ) as downloader:

        async def worker() -> None:
            for index, request in pending:
                results[index] = await downloader.download(request)

        async with asyncio.TaskGroup() as group:
            for _ in range(min(jobs, len(requests))):
                group.create_task(worker())
    return [path for path in results if path is not None]

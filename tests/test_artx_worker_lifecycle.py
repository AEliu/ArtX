from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Callable

import pytest

from artx.download import tiles as tile_module
from artx.errors import DownloadError
from artx.models import TileJob
from artx.reporting import Reporter


def jobs(count: int) -> list[TileJob]:
    return [TileJob(z=0, x=index, y=0, url=f"https://example.test/{index}") for index in range(count)]


def test_async_workers_bound_network_and_task_count(tmp_path: Path) -> None:
    async def run() -> None:
        baseline = asyncio.all_tasks()
        active = peak_active = peak_tasks = 0

        class Client:
            async def fetch_bytes(self, url: str, *, description: str) -> bytes:
                nonlocal active, peak_active, peak_tasks
                active += 1
                peak_active = max(peak_active, active)
                peak_tasks = max(peak_tasks, len(asyncio.all_tasks() - baseline))
                try:
                    await asyncio.sleep(0.001)
                    return b"tile"
                finally:
                    active -= 1

        result = await tile_module.download_tiles_async(jobs(100), 3, Reporter(), Client(), tmp_path)
        assert len(result) == 100
        assert peak_active == 3
        assert peak_tasks <= 6  # At most one worker and one disk task per slot.
        assert active == 0
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(run())


def test_async_failure_cancels_requests_and_preserves_original_error(tmp_path: Path) -> None:
    async def run() -> None:
        baseline = asyncio.all_tasks()
        both_started = asyncio.Event()
        active = 0

        class Client:
            async def fetch_bytes(self, url: str, *, description: str) -> bytes:
                nonlocal active
                active += 1
                if active == 2:
                    both_started.set()
                try:
                    if url.endswith("/0"):
                        await both_started.wait()
                        raise DownloadError("tile unavailable")
                    await asyncio.Event().wait()
                    raise AssertionError("Blocked request should be cancelled")
                finally:
                    active -= 1

        with pytest.raises(DownloadError, match="tile unavailable"):
            await asyncio.wait_for(tile_module.download_tiles_async(jobs(100), 2, Reporter(), Client(), tmp_path), 3)
        assert active == 0
        assert not (asyncio.all_tasks() - baseline)
        assert not list(tmp_path.iterdir())

    asyncio.run(run())


def test_external_cancellation_stops_every_network_worker(tmp_path: Path) -> None:
    async def run() -> None:
        baseline = asyncio.all_tasks()
        started = asyncio.Event()
        active = 0

        class Client:
            async def fetch_bytes(self, url: str, *, description: str) -> bytes:
                nonlocal active
                active += 1
                started.set()
                try:
                    await asyncio.Event().wait()
                    raise AssertionError("Blocked request should be cancelled")
                finally:
                    active -= 1

        task = asyncio.create_task(tile_module.download_tiles_async(jobs(100), 3, Reporter(), Client(), tmp_path))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert active == 0
            assert not (asyncio.all_tasks() - baseline)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_cancellation_waits_for_cache_write_even_when_repeated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release, finished = Event(), Event(), Event()
    original_write = tile_module._write_tile_bytes
    fetched = 0

    def slow_write(path: Path, data: bytes) -> None:
        path.with_suffix(path.suffix + ".part").write_bytes(data)
        entered.set()
        assert release.wait(5)
        original_write(path, data)
        finished.set()

    monkeypatch.setattr(tile_module, "_write_tile_bytes", slow_write)

    class Client:
        async def fetch_bytes(self, url: str, *, description: str) -> bytes:
            nonlocal fetched
            fetched += 1
            return b"complete tile"

    async def run() -> None:
        baseline = asyncio.all_tasks()
        task = asyncio.create_task(tile_module.download_tiles_async(jobs(100), 1, Reporter(), Client(), tmp_path))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
            assert not finished.is_set()
            assert fetched == 1  # Disk backpressure also occupies the network worker slot.
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert finished.is_set()
            assert not list(tmp_path.glob("*.part"))
            assert len(list(tmp_path.glob("*.tile"))) == 1
            assert not (asyncio.all_tasks() - baseline)
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize("workers", [0, -1])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_invalid_worker_count_rejected_even_for_cached_or_empty_jobs(
    tmp_path: Path, workers: int, asynchronous: bool
) -> None:
    class SyncClient:
        def fetch_bytes(self, url: str, *, description: str) -> bytes:
            raise AssertionError("No requests should be made")

    class AsyncClient:
        async def fetch_bytes(self, url: str, *, description: str) -> bytes:
            raise AssertionError("No requests should be made")

    with pytest.raises(ValueError, match="workers must be positive"):
        if asynchronous:
            asyncio.run(tile_module.download_tiles_async([], workers, Reporter(), AsyncClient(), tmp_path))
        else:
            tile_module.download_tiles([], workers, Reporter(), SyncClient(), tmp_path)


def test_failed_cache_publication_removes_partial_and_keeps_previous_tile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "0-0-0.tile"
    path.write_bytes(b"previous tile")

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        tile_module._write_tile_bytes(path, b"new tile")
    assert path.read_bytes() == b"previous tile"
    assert list(tmp_path.iterdir()) == [path]


def test_sync_submission_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = Event(), Event()
    submissions = 0

    class RecordingExecutor(ThreadPoolExecutor):
        def submit(self, fn: Callable[..., bytes], /, *args: object, **kwargs: object) -> Future[bytes]:
            nonlocal submissions
            submissions += 1
            return super().submit(fn, *args, **kwargs)

    class Client:
        def fetch_bytes(self, url: str, *, description: str) -> bytes:
            started.set()
            assert release.wait(5)
            return b"tile"

    monkeypatch.setattr(tile_module, "ThreadPoolExecutor", RecordingExecutor)
    with ThreadPoolExecutor(max_workers=1) as caller:
        result = caller.submit(tile_module.download_tiles, jobs(100), 2, Reporter(), Client(), tmp_path)
        try:
            assert started.wait(3)
            assert submissions <= 2
        finally:
            release.set()
        assert len(result.result(timeout=5)) == 100

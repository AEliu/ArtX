from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Iterable, Protocol

from Crypto.Cipher import AES

from ..errors import DownloadError
from ..models import PageInfo, PyramidLevel, TileInfo, TileJob
from ..reporting import Reporter
from .cache import tile_cache_path
from .concurrency import run_blocking
from .constants import AES_IV, AES_KEY, ENCRYPTION_MARKER, SIGNING_KEY


class TileHttpClient(Protocol):
    def fetch_bytes(self, url: str, *, description: str) -> bytes: ...


class AsyncTileHttpClient(Protocol):
    async def fetch_bytes(self, url: str, *, description: str) -> bytes: ...


def build_tile_url(page: PageInfo, x: int, y: int, z: int) -> str:
    suffix = f"=x{x}-y{y}-z{z}-t"
    message = f"{page.path}{suffix}{page.token}".encode("utf-8")
    digest = hmac.new(SIGNING_KEY, message, hashlib.sha1).digest()
    signature = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=").replace("-", "_")
    return f"{page.base_url}{suffix}{signature}"


def decrypt_tile_if_needed(data: bytes) -> bytes:
    if not data.startswith(ENCRYPTION_MARKER):
        return data

    if len(data) < 12:
        raise DownloadError("encrypted tile is too short")

    header_size = int.from_bytes(data[-4:], "little")
    encrypted_size_offset = 4 + header_size
    encrypted_size = int.from_bytes(data[encrypted_size_offset : encrypted_size_offset + 4], "little")
    encrypted_start = encrypted_size_offset + 4
    encrypted_end = encrypted_start + encrypted_size
    footer_end = len(data) - 4

    header = data[4 : 4 + header_size]
    encrypted = data[encrypted_start:encrypted_end]
    footer = data[encrypted_end:footer_end]

    if len(encrypted) % AES.block_size != 0:
        raise DownloadError("encrypted tile size is not aligned to AES block size")

    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
    decrypted = cipher.decrypt(encrypted)
    return header + decrypted + footer


def build_jobs(page: PageInfo, tile_info: TileInfo, level: PyramidLevel) -> list[TileJob]:
    return [
        TileJob(z=level.z, x=x, y=y, url=build_tile_url(page, x, y, level.z))
        for y in range(level.num_tiles_y)
        for x in range(level.num_tiles_x)
    ]


def _write_tile_bytes(cache_path: Path, data: bytes) -> None:
    temp_path = cache_path.with_suffix(cache_path.suffix + ".part")
    try:
        temp_path.write_bytes(data)
        temp_path.replace(cache_path)
    finally:
        temp_path.unlink(missing_ok=True)


def download_tiles(
    jobs: Iterable[TileJob],
    workers: int,
    reporter: Reporter,
    http_client: TileHttpClient,
    tiles_dir: Path,
) -> dict[tuple[int, int], Path]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    tiles: dict[tuple[int, int], Path] = {}
    job_list = list(jobs)
    cached_jobs = [job for job in job_list if tile_cache_path(tiles_dir, job).exists()]
    missing_jobs = [job for job in job_list if not tile_cache_path(tiles_dir, job).exists()]
    total = len(job_list)
    completed = 0

    for job in cached_jobs:
        cache_path = tile_cache_path(tiles_dir, job)
        tiles[(job.x, job.y)] = cache_path
        completed += 1

    if cached_jobs:
        reporter.log(f"Reusing {len(cached_jobs)} cached tile(s)")
        reporter.tile_advanced(completed, total)

    if not missing_jobs:
        return tiles

    pending_jobs = iter(missing_jobs)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map: dict[Future[bytes], TileJob] = {}

        def submit_next() -> None:
            job = next(pending_jobs, None)
            if job is not None:
                future = executor.submit(http_client.fetch_bytes, job.url, description=f"tile x={job.x} y={job.y}")
                future_map[future] = job

        for _ in range(min(workers, len(missing_jobs))):
            submit_next()
        try:
            while future_map:
                ready, _ = wait(future_map, return_when=FIRST_COMPLETED)
                for future in ready:
                    job = future_map.pop(future)
                    tile_data = decrypt_tile_if_needed(future.result())
                    cache_path = tile_cache_path(tiles_dir, job)
                    _write_tile_bytes(cache_path, tile_data)
                    tiles[(job.x, job.y)] = cache_path
                    completed += 1
                    reporter.tile_advanced(completed, total)
                for _ in ready:
                    submit_next()
        finally:
            for future in future_map:
                future.cancel()

    return tiles


async def download_tiles_async(
    jobs: Iterable[TileJob],
    workers: int,
    reporter: Reporter,
    http_client: AsyncTileHttpClient,
    tiles_dir: Path,
) -> dict[tuple[int, int], Path]:
    if workers <= 0:
        raise ValueError("workers must be positive")
    tiles: dict[tuple[int, int], Path] = {}
    job_list = list(jobs)
    cached_jobs = [job for job in job_list if tile_cache_path(tiles_dir, job).exists()]
    missing_jobs = [job for job in job_list if not tile_cache_path(tiles_dir, job).exists()]
    total = len(job_list)
    completed = 0

    for job in cached_jobs:
        cache_path = tile_cache_path(tiles_dir, job)
        tiles[(job.x, job.y)] = cache_path
        completed += 1

    if cached_jobs:
        reporter.log(f"Reusing {len(cached_jobs)} cached tile(s)")
        reporter.tile_advanced(completed, total)

    if not missing_jobs:
        return tiles

    pending_jobs = iter(missing_jobs)

    async def worker() -> None:
        nonlocal completed
        # Iterator advancement does not await: each job belongs to one worker.
        # A worker keeps its slot until its tile has been written to disk, so
        # slow storage cannot accumulate an unbounded number of response bodies.
        for job in pending_jobs:
            payload = await http_client.fetch_bytes(job.url, description=f"tile x={job.x} y={job.y}")
            tile_data = decrypt_tile_if_needed(payload)
            cache_path = tile_cache_path(tiles_dir, job)
            await run_blocking(_write_tile_bytes, cache_path, tile_data)
            tiles[(job.x, job.y)] = cache_path
            completed += 1
            reporter.tile_advanced(completed, total)

    try:
        async with asyncio.TaskGroup() as group:
            for _ in range(min(workers, len(missing_jobs))):
                group.create_task(worker())
    except ExceptionGroup as exc:
        # Preserve the existing single-error API while retaining simultaneous
        # failures as a group instead of silently discarding sibling failures.
        if len(exc.exceptions) == 1:
            raise exc.exceptions[0] from exc
        raise

    return tiles

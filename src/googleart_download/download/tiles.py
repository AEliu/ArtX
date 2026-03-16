from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Protocol

from Crypto.Cipher import AES

from ..errors import DownloadError
from ..models import PageInfo, PyramidLevel, TileInfo, TileJob
from ..reporting import Reporter
from .cache import tile_cache_path
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
    temp_path.write_bytes(data)
    temp_path.replace(cache_path)


def download_tiles(
    jobs: Iterable[TileJob],
    workers: int,
    reporter: Reporter,
    http_client: TileHttpClient,
    tiles_dir: Path,
) -> dict[tuple[int, int], Path]:
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

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(http_client.fetch_bytes, job.url, description=f"tile x={job.x} y={job.y}"): job
            for job in missing_jobs
        }

        for future in as_completed(future_map):
            job = future_map[future]
            tile_data = decrypt_tile_if_needed(future.result())
            cache_path = tile_cache_path(tiles_dir, job)
            _write_tile_bytes(cache_path, tile_data)
            tiles[(job.x, job.y)] = cache_path
            completed += 1
            reporter.tile_advanced(completed, total)

    return tiles


async def download_tiles_async(
    jobs: Iterable[TileJob],
    workers: int,
    reporter: Reporter,
    http_client: AsyncTileHttpClient,
    tiles_dir: Path,
) -> dict[tuple[int, int], Path]:
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

    semaphore = asyncio.Semaphore(workers)
    tasks = [
        asyncio.create_task(
            _download_single_tile(job, semaphore=semaphore, http_client=http_client, tiles_dir=tiles_dir)
        )
        for job in missing_jobs
    ]

    try:
        for task in asyncio.as_completed(tasks):
            key, cache_path = await task
            tiles[key] = cache_path
            completed += 1
            reporter.tile_advanced(completed, total)
    except Exception:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    return tiles


async def _download_single_tile(
    job: TileJob,
    *,
    semaphore: asyncio.Semaphore,
    http_client: AsyncTileHttpClient,
    tiles_dir: Path,
) -> tuple[tuple[int, int], Path]:
    async with semaphore:
        payload = await http_client.fetch_bytes(job.url, description=f"tile x={job.x} y={job.y}")
    tile_data = decrypt_tile_if_needed(payload)
    cache_path = tile_cache_path(tiles_dir, job)
    await asyncio.to_thread(_write_tile_bytes, cache_path, tile_data)
    return (job.x, job.y), cache_path

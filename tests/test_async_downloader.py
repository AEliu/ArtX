from __future__ import annotations

import asyncio
import re
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from google_art.async_downloader import AsyncGoogleArtDownloader, AsyncOptions

ASSET_HTML = """
[123],"//lh3.googleusercontent.com/ci/TileBase","SecretToken"]
<script type="application/ld+json">{"name":"Test Artwork"}</script>
"""
TILE_PATTERN = re.compile(r"=x(?P<x>\d+)-y(?P<y>\d+)-z\d+-t")


def manifest(columns: int = 2, rows: int = 2) -> str:
    return (
        '<TileInfo tile_width="32" tile_height="32">'
        f'<pyramid_level num_tiles_x="{columns}" num_tiles_y="{rows}" '
        'empty_pels_x="0" empty_pels_y="0" /></TileInfo>'
    )


def metadata_response(request: httpx.Request, xml: str) -> httpx.Response | None:
    if request.url.host == "artsandculture.google.com":
        return httpx.Response(200, text=ASSET_HTML)
    if str(request.url).endswith("=g"):
        return httpx.Response(200, text=xml)
    return None


def png_bytes(color: tuple[int, int, int]) -> bytes:
    with Image.new("RGB", (32, 32), color) as image:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def exception_leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for child in exc.exceptions for leaf in exception_leaves(child)]
    return [exc]


def test_async_downloader_reconstructs_and_resizes_image(tmp_path: Path):
    colors = {(0, 0): (255, 0, 0), (1, 0): (0, 255, 0), (0, 1): (0, 0, 255), (1, 1): (255, 255, 0)}
    payloads = {coords: png_bytes(color) for coords, color in colors.items()}

    async def handler(request: httpx.Request) -> httpx.Response:
        if response := metadata_response(request, manifest()):
            return response
        match = TILE_PATTERN.search(str(request.url))
        assert match is not None
        assert request.headers["referer"].endswith("/sample-id")
        coords = int(match["x"]), int(match["y"])
        return httpx.Response(200, content=payloads[coords], headers={"Content-Type": "image/png"})

    async def run() -> Path:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            try:
                return await downloader.download(
                    AsyncOptions(
                        asset="sample-id",
                        out_path=str(tmp_path / "output.png"),
                        max_edge=32,
                        assembler="pillow",
                        queue_size=1,
                    )
                )
            finally:
                await downloader.aclose()

    result = asyncio.run(run())
    with Image.open(result) as image:
        assert image.size == (32, 32)
        assert image.getpixel((4, 4))[0] > 240
        assert image.getpixel((24, 4))[1] > 240
        assert image.getpixel((4, 24))[2] > 240


def test_network_concurrency_is_shared_between_assets(tmp_path: Path):
    active = peak = 0
    payload = png_bytes((12, 34, 56))

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            if response := metadata_response(request, manifest()):
                return response
            return httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})
        finally:
            active -= 1

    async def run() -> list[Path]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            try:
                return await asyncio.gather(
                    *(
                        downloader.download(
                            AsyncOptions(
                                asset=f"sample-{index}",
                                out_path=str(tmp_path / f"output-{index}.png"),
                                net_concurrency=2,
                                per_asset_concurrency=4,
                                queue_size=1,
                                assembler="pillow",
                            )
                        )
                        for index in range(3)
                    )
                )
            finally:
                await downloader.aclose()

    results = asyncio.run(run())
    assert all(path.exists() for path in results)
    assert peak == 2
    assert active == 0


def test_tile_task_count_is_bounded_by_workers(tmp_path: Path):
    payload = png_bytes((12, 34, 56))

    async def run() -> None:
        baseline = asyncio.all_tasks()
        peak_tasks = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal peak_tasks
            if response := metadata_response(request, manifest(8, 8)):
                return response
            peak_tasks = max(peak_tasks, len(asyncio.all_tasks() - baseline))
            await asyncio.sleep(0)
            return httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            try:
                await downloader.download(
                    AsyncOptions(
                        asset="sample-id",
                        out_path=str(tmp_path / "many-tiles.png"),
                        net_concurrency=3,
                        per_asset_concurrency=3,
                        queue_size=1,
                        assembler="pillow",
                    )
                )
                # Allow coordinator/consumer tasks while rejecting one task per tile.
                assert peak_tasks <= 10
                assert not (asyncio.all_tasks() - baseline)
            finally:
                await downloader.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["producer", "consumer"])
def test_failure_cancels_workers_without_leaking_tasks(tmp_path: Path, failure: str):
    async def run() -> None:
        active = 0
        waiting = asyncio.Event()
        forever = asyncio.Event()
        baseline = asyncio.all_tasks()

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active
            if response := metadata_response(request, manifest(8, 8)):
                return response
            active += 1
            if active >= 2:
                waiting.set()
            try:
                if "=x0-y0-" in str(request.url):
                    await waiting.wait()
                    if failure == "producer":
                        return httpx.Response(404, text="missing tile")
                    return httpx.Response(200, content=b"not an image", headers={"Content-Type": "image/png"})
                await forever.wait()
                raise AssertionError("Blocked request should have been cancelled")
            finally:
                active -= 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            try:
                with pytest.raises(Exception) as caught:
                    await asyncio.wait_for(
                        downloader.download(
                            AsyncOptions(
                                asset="sample-id",
                                out_path=str(tmp_path / "failed.png"),
                                net_concurrency=3,
                                per_asset_concurrency=3,
                                queue_size=1,
                                assembler="pillow",
                            )
                        ),
                        timeout=3,
                    )
                leaves = exception_leaves(caught.value)
                assert not any(isinstance(exc, TimeoutError) for exc in leaves)
                if failure == "producer":
                    assert any(isinstance(exc, httpx.HTTPStatusError) for exc in leaves)
                assert active == 0
                assert not (asyncio.all_tasks() - baseline)
                assert not (tmp_path / "failed.png").exists()
            finally:
                await downloader.aclose()

    asyncio.run(run())


def test_external_cancellation_stops_all_requests(tmp_path: Path):
    async def run() -> None:
        started = asyncio.Event()
        forever = asyncio.Event()
        active = 0
        baseline = asyncio.all_tasks()

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal active
            if response := metadata_response(request, manifest(8, 8)):
                return response
            active += 1
            started.set()
            try:
                await forever.wait()
                raise AssertionError("Blocked request should have been cancelled")
            finally:
                active -= 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            task = asyncio.create_task(
                downloader.download(
                    AsyncOptions(
                        asset="sample-id",
                        out_path=str(tmp_path / "cancelled.png"),
                        net_concurrency=2,
                        per_asset_concurrency=2,
                        queue_size=1,
                        assembler="pillow",
                    )
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=3)
                assert active == 0
                assert not (asyncio.all_tasks() - baseline)
                assert not (tmp_path / "cancelled.png").exists()
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await downloader.aclose()

    asyncio.run(run())


def test_closing_downloader_preserves_injected_client():
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text="still available"))
        ) as client:
            downloader = AsyncGoogleArtDownloader(client=client, show_progress=False)
            await downloader.aclose()
            assert not client.is_closed
            response = await client.get("https://example.test/")
            assert response.text == "still available"

    asyncio.run(run())


@pytest.mark.parametrize("field", ["net_concurrency", "per_asset_concurrency", "queue_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_async_options_reject_non_positive_limits(field: str, value: int):
    with pytest.raises(ValueError):
        AsyncOptions(asset="sample-id", **{field: value})

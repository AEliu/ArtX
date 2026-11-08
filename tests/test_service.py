from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from google_art import service
from google_art.async_downloader import AsyncGoogleArtDownloader
from google_art.models import AsyncOptions


def leaves(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for child in exc.exceptions for leaf in leaves(child)]
    return [exc]


def test_batch_limits_jobs_and_returns_input_order(monkeypatch):
    active = peak = 0
    finished: list[str] = []
    lifecycle: list[str] = []

    class FakeDownloader:
        def __init__(self, **kwargs):
            assert kwargs["net_concurrency"] == 4
            assert kwargs["show_progress"] is False
            assert kwargs["reserved_outputs"] == set()

        async def __aenter__(self):
            lifecycle.append("opened")
            return self

        async def __aexit__(self, *exc):
            assert active == 0
            lifecycle.append("closed")

        async def download(self, options):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                await asyncio.sleep(0.02 if options.asset == "first" else 0)
                finished.append(options.asset)
                return Path(f"{options.asset}.png")
            finally:
                active -= 1

    monkeypatch.setattr(service, "AsyncGoogleArtDownloader", FakeDownloader)
    requests = [AsyncOptions(asset=asset, net_concurrency=4) for asset in ("first", "second", "third")]
    result = asyncio.run(service.download_many(requests, jobs=2, show_progress=False))
    assert result == [Path("first.png"), Path("second.png"), Path("third.png")]
    assert finished[0] == "second"
    assert peak == 2
    assert lifecycle == ["opened", "closed"]


def test_batch_waits_for_cancelled_workers_before_closing(monkeypatch):
    async def run():
        started = asyncio.Event()
        forever = asyncio.Event()
        lifecycle: list[str] = []
        baseline = asyncio.all_tasks()

        class FakeDownloader:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                lifecycle.append("closed")

            async def download(self, options):
                if options.asset == "failing":
                    await started.wait()
                    raise RuntimeError("tile request failed")
                assert options.asset == "blocked", "Queued asset must not start after failure"
                started.set()
                try:
                    await forever.wait()
                finally:
                    await asyncio.sleep(0)
                    lifecycle.append("worker cleaned")

        monkeypatch.setattr(service, "AsyncGoogleArtDownloader", FakeDownloader)
        requests = [AsyncOptions(asset=asset) for asset in ("failing", "blocked", "queued")]
        with pytest.raises(ExceptionGroup) as caught:
            await asyncio.wait_for(service.download_many(requests, jobs=2), timeout=3)
        assert any(str(exc) == "tile request failed" for exc in leaves(caught.value))
        assert lifecycle == ["worker cleaned", "closed"]
        assert not (asyncio.all_tasks() - baseline)

    asyncio.run(run())


@pytest.mark.parametrize("case", ["jobs", "budgets", "duplicate_file"])
def test_invalid_batch_is_rejected_before_creating_downloader(monkeypatch, tmp_path: Path, case: str):
    def forbidden(**kwargs):
        pytest.fail("Invalid configuration must fail before creating a downloader")

    monkeypatch.setattr(service, "AsyncGoogleArtDownloader", forbidden)
    jobs = 0 if case == "jobs" else 2
    requests = [AsyncOptions(asset="first"), AsyncOptions(asset="second")]
    if case == "budgets":
        requests[1] = AsyncOptions(asset="second", net_concurrency=1)
    elif case == "duplicate_file":
        requests = [
            AsyncOptions(asset=asset, out_path=str(tmp_path / "same.png"), overwrite=True)
            for asset in ("first", "second")
        ]
    with pytest.raises(ValueError):
        asyncio.run(service.download_many(requests, jobs=jobs))


def test_empty_batch_does_not_create_downloader(monkeypatch):
    def forbidden(**kwargs):
        pytest.fail("An empty batch must not create a downloader")

    monkeypatch.setattr(service, "AsyncGoogleArtDownloader", forbidden)
    assert asyncio.run(service.download_many([])) == []


def test_same_title_cannot_overwrite_previous_batch_result(monkeypatch, tmp_path: Path):
    buffer = BytesIO()
    with Image.new("RGB", (8, 8), (12, 34, 56)) as image:
        image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    tile_requests = 0

    async def handler(request):
        nonlocal tile_requests
        if request.url.host == "artsandculture.google.com":
            return httpx.Response(
                200, text='[1],"//lh3.googleusercontent.com/ci/Base","token"]<script>{"name":"Same Title"}</script>'
            )
        if str(request.url).endswith("=g"):
            return httpx.Response(
                200,
                text='<TileInfo tile_width="8" tile_height="8">'
                '<pyramid_level num_tiles_x="1" num_tiles_y="1" '
                'empty_pels_x="0" empty_pels_y="0" /></TileInfo>',
            )
        tile_requests += 1
        return httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(
                service, "AsyncGoogleArtDownloader", lambda **kwargs: AsyncGoogleArtDownloader(client=client, **kwargs)
            )
            requests = [
                AsyncOptions(asset=asset, out_path=str(tmp_path), overwrite=True, assembler="pillow")
                for asset in ("first", "second")
            ]
            with pytest.raises(ExceptionGroup) as caught:
                await service.download_many(requests, jobs=1, show_progress=False)
            assert any(isinstance(exc, FileExistsError) for exc in leaves(caught.value))

    asyncio.run(run())
    assert tile_requests == 1
    assert (tmp_path / "Same_Title.png").exists()

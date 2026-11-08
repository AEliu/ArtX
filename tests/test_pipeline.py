from __future__ import annotations

import asyncio
from io import BytesIO
from threading import Event

import httpx
import pytest
from PIL import Image

from google_art import AsyncGoogleArtDownloader, AsyncOptions, DownloadOptions, GoogleArtDownloader
from google_art.models import clamp_dimensions
from google_art.output import staged_output

HTML = '[1],"//lh3.googleusercontent.com/ci/Test","token"]<script>{"name":"Same Title"}</script>'
XML = (
    '<TileInfo tile_width="32" tile_height="32">'
    '<pyramid_level num_tiles_x="1" num_tiles_y="1" empty_pels_x="0" empty_pels_y="16" />'
    "</TileInfo>"
)


def response_for(request: httpx.Request) -> httpx.Response:
    if request.url.host == "artsandculture.google.com":
        return httpx.Response(200, text=HTML)
    if str(request.url).endswith("=g"):
        return httpx.Response(200, text=XML)
    buffer = BytesIO()
    image = Image.new("RGB", (32, 32), (12, 34, 56))
    try:
        image.save(buffer, format="PNG")
    finally:
        image.close()
    return httpx.Response(200, content=buffer.getvalue(), headers={"Content-Type": "image/png"})


@pytest.mark.parametrize("asynchronous", [False, True])
def test_adapters_share_crop_resize_directory_and_format_rules(tmp_path, asynchronous):
    directory = tmp_path / "new-directory"
    if asynchronous:

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(response_for)) as client:
                async with AsyncGoogleArtDownloader(client=client, show_progress=False) as downloader:
                    return await downloader.download(
                        AsyncOptions(asset="sample", out_path=str(directory), max_edge=16, fmt="jpg")
                    )

        path = asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(response_for)) as client:
            with GoogleArtDownloader(client=client, show_progress=False) as downloader:
                path = downloader.download(
                    DownloadOptions(asset="sample", out_path=str(directory), max_edge=16, fmt="jpg")
                )
            assert not client.is_closed
    assert path == directory / "Same_Title.jpeg"
    with Image.open(path) as image:
        assert image.size == (16, 8)
        assert image.format == "JPEG"


@pytest.mark.parametrize("stage", ["begin", "paste", "save"])
def test_cancellation_waits_for_image_thread_before_cleanup(tmp_path, monkeypatch, stage):
    entered, release = Event(), Event()
    closed = False

    def block(where):
        if where == stage:
            entered.set()
            assert release.wait(5), "Test did not release image operation"
        assert not closed

    class BlockingAssembler:
        def begin(self, size):
            block("begin")

        def paste_tile(self, *args):
            block("paste")

        def finalize_save(self, path, *args):
            path.write_bytes(b"partial image")
            block("save")

        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr("google_art.async_downloader.pick_assembler", lambda *args: BlockingAssembler())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response_for)) as client:
            async with AsyncGoogleArtDownloader(client=client, show_progress=False) as downloader:
                task = asyncio.create_task(
                    downloader.download(AsyncOptions(asset="sample", out_path=str(tmp_path / "art.png")))
                )
                try:
                    assert await asyncio.to_thread(entered.wait, 3)
                    task.cancel()
                    await asyncio.sleep(0.01)
                    task.cancel()  # A second cancellation must not let the worker outlive cleanup.
                    await asyncio.sleep(0.01)
                    assert not closed
                    assert not task.done()
                    release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 3)
                    assert closed
                    assert list(tmp_path.iterdir()) == []
                finally:
                    release.set()
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_staged_output_preserves_existing_file_when_encoder_fails(tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"original")
    with pytest.raises(RuntimeError, match="encoder failed"):
        with staged_output(path, overwrite=True) as temporary:
            temporary.write_bytes(b"partial")
            raise RuntimeError("encoder failed")
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


def test_no_overwrite_protects_file_created_during_encoding(tmp_path):
    path = tmp_path / "race.png"
    with pytest.raises(FileExistsError):
        with staged_output(path, overwrite=False) as temporary:
            temporary.write_bytes(b"new image")
            path.write_bytes(b"other writer")
    assert path.read_bytes() == b"other writer"
    assert list(tmp_path.iterdir()) == [path]


def test_successful_overwrite_publishes_and_removes_temporary_file(tmp_path):
    path = tmp_path / "existing.png"
    path.write_bytes(b"original")
    with staged_output(path, overwrite=True) as temporary:
        temporary.write_bytes(b"complete image")
        assert path.read_bytes() == b"original"
    assert path.read_bytes() == b"complete image"
    assert list(tmp_path.iterdir()) == [path]


def test_narrow_image_keeps_at_least_one_pixel():
    assert clamp_dimensions(10000, 1, 1) == (1, 1)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_transient_http_failure_retries_and_saves_image(tmp_path, asynchronous):
    attempts = 0

    def handler(request):
        nonlocal attempts
        if "=x" in str(request.url):
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
        return response_for(request)

    destination = tmp_path / "retried.png"
    if asynchronous:

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                async with AsyncGoogleArtDownloader(client=client, show_progress=False) as downloader:
                    await downloader.download(AsyncOptions(asset="sample", out_path=str(destination)))

        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with GoogleArtDownloader(client=client, show_progress=False) as downloader:
                downloader.download(DownloadOptions(asset="sample", out_path=str(destination)))
    assert attempts == 2
    assert destination.exists()

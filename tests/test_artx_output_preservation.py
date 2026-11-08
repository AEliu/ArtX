from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from artx.download import downloader
from artx.download.http_client import HttpClient
from artx.download.stitch_from_tiles import stitch_from_tile_directory
from artx.errors import DownloadError
from artx.models import DownloadSize, OutputConflictPolicy, RetryConfig, StitchBackend
from artx.reporting import Reporter

HTML = '<title>Test Artwork</title>[123],"//lh3.googleusercontent.com/ci/Test","token"]'
XML = (
    '<TileInfo tile_width="8" tile_height="8">'
    '<pyramid_level num_tiles_x="1" num_tiles_y="1" empty_pels_x="0" empty_pels_y="0"/>'
    "</TileInfo>"
)


@pytest.mark.parametrize("failure_stage", ["download", "stitch", "directory"])
def test_overwrite_preserves_existing_output_on_failure(tmp_path, monkeypatch, failure_stage):
    output = tmp_path / "art.jpg"
    if failure_stage == "directory":
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
    else:
        output.write_bytes(b"original artwork")

    def response(request):
        return httpx.Response(200, text=XML if str(request.url).endswith("=g") else HTML)

    def fail(*args, **kwargs):
        raise DownloadError("simulated failure")

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        monkeypatch.setattr(downloader, "HttpClient", lambda **kwargs: HttpClient(client=client, **kwargs))
        if failure_stage == "download":
            monkeypatch.setattr(downloader, "await_download_tiles", fail)
        elif failure_stage == "stitch":
            monkeypatch.setattr(downloader, "await_download_tiles", lambda *args, **kwargs: {})
            monkeypatch.setattr(downloader, "stitch_tiles", fail)
        with pytest.raises(DownloadError):
            downloader.download_artwork(
                url="https://artsandculture.google.com/asset/sample/abcdefghijk",
                output_dir=tmp_path,
                filename="art.jpg",
                workers=1,
                jpeg_quality=85,
                retry_config=RetryConfig(attempts=1),
                download_size=DownloadSize.MAX,
                max_dimension=None,
                output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                write_metadata=False,
                write_sidecar=False,
                stitch_backend=StitchBackend.PILLOW,
                reporter=Reporter(),
                index=1,
                total=1,
            )
    if failure_stage == "directory":
        assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
    else:
        assert output.read_bytes() == b"original artwork"


def test_offline_stitch_preserves_existing_output_when_tile_is_corrupt(tmp_path: Path):
    tile_dir = tmp_path / "art.tiles"
    (tile_dir / "tiles").mkdir(parents=True)
    (tile_dir / "tiles/0-0-0.tile").write_bytes(b"corrupt")
    (tile_dir / "state.json").write_text(
        json.dumps(
            {
                "stage": "downloaded",
                "image_width": 8,
                "image_height": 8,
                "tile_width": 8,
                "tile_height": 8,
                "completed_tiles": 1,
                "total_tiles": 1,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "art.jpg"
    output.write_bytes(b"original artwork")
    with pytest.raises(Image.UnidentifiedImageError):
        stitch_from_tile_directory(
            tile_dir=tile_dir,
            output_dir=tmp_path,
            filename="art.jpg",
            jpeg_quality=85,
            output_conflict_policy=OutputConflictPolicy.OVERWRITE,
            stitch_backend=StitchBackend.PILLOW,
            reporter=Reporter(),
        )
    assert output.read_bytes() == b"original artwork"

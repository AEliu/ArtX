from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from googleart_download.download.cache import ensure_cache_layout
from googleart_download.download.image_writer import ensure_stitch_memory_budget
from googleart_download.download.tiles import download_tiles
from googleart_download.errors import DownloadError
from googleart_download.models import RetryConfig, TileJob, TileInfo, PyramidLevel
from googleart_download.reporters import Reporter


class SilentReporter(Reporter):
    pass


class FakeHttpClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def fetch_bytes(self, url: str, *, description: str) -> bytes:
        self.calls.append(url)
        return self.payload


def build_png_bytes(color: tuple[int, int, int]) -> bytes:
    with TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "tile.png"
        image = Image.new("RGB", (8, 8), color)
        image.save(path, format="PNG")
        return path.read_bytes()


class TileCacheTests(unittest.TestCase):
    def test_download_tiles_reuses_existing_cache(self) -> None:
        jobs = [
            TileJob(x=0, y=0, url="https://example.com/0"),
            TileJob(x=1, y=0, url="https://example.com/1"),
        ]
        cached_payload = build_png_bytes((255, 0, 0))
        fetched_payload = build_png_bytes((0, 255, 0))

        with TemporaryDirectory() as tmpdir:
            tiles_dir = ensure_cache_layout(Path(tmpdir))
            (tiles_dir / "0-0.tile").write_bytes(cached_payload)
            client = FakeHttpClient(fetched_payload)

            result = download_tiles(
                jobs,
                workers=2,
                reporter=SilentReporter(),
                http_client=client,
                tiles_dir=tiles_dir,
            )

            self.assertEqual(client.calls, ["https://example.com/1"])
            self.assertEqual(result[(0, 0)].read_bytes(), cached_payload)
            self.assertEqual(result[(1, 0)].read_bytes(), fetched_payload)

    def test_memory_budget_guard_rejects_oversized_canvas(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[PyramidLevel(z=0, num_tiles_x=10, num_tiles_y=10, empty_pels_x=0, empty_pels_y=0)],
        )

        from unittest.mock import patch

        with patch("googleart_download.download.image_writer._read_available_memory_bytes", return_value=1024):
            with self.assertRaises(DownloadError):
                ensure_stitch_memory_budget(tile_info)


if __name__ == "__main__":
    unittest.main()

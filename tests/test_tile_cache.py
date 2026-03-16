from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from googleart_download.download.cache import ensure_cache_layout, resolve_artwork_cache_dir
from googleart_download.download.image_writer import (
    _save_with_pillow,
    build_bigtiff_temp_path,
    build_temp_output_path,
    choose_stitch_backend,
    cleanup_stale_partial_outputs,
    ensure_stitch_memory_budget,
    resolve_backend_output_path,
    resolve_non_conflicting_output_path,
    resolve_output_path,
)
from googleart_download.download.size_selection import list_size_options, select_download_level
from googleart_download.download.tiles import download_tiles
from googleart_download.errors import DownloadError
from googleart_download.models import DownloadSize, PyramidLevel, StitchBackend, TileInfo, TileJob
from googleart_download.reporting import Reporter


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
            TileJob(z=0, x=0, y=0, url="https://example.com/0"),
            TileJob(z=0, x=1, y=0, url="https://example.com/1"),
        ]
        cached_payload = build_png_bytes((255, 0, 0))
        fetched_payload = build_png_bytes((0, 255, 0))

        with TemporaryDirectory() as tmpdir:
            tiles_dir = ensure_cache_layout(Path(tmpdir))
            (tiles_dir / "0-0-0.tile").write_bytes(cached_payload)
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

    def test_auto_backend_prefers_bigtiff_when_memory_is_not_safe(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[PyramidLevel(z=0, num_tiles_x=10, num_tiles_y=10, empty_pels_x=0, empty_pels_y=0)],
        )

        from unittest.mock import patch

        with patch("googleart_download.download.image_writer._read_available_memory_bytes", return_value=1024):
            self.assertEqual(choose_stitch_backend(tile_info, StitchBackend.AUTO), StitchBackend.BIGTIFF)

    def test_select_download_level_uses_size_presets(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[
                PyramidLevel(z=0, num_tiles_x=2, num_tiles_y=2, empty_pels_x=0, empty_pels_y=0),
                PyramidLevel(z=1, num_tiles_x=8, num_tiles_y=8, empty_pels_x=0, empty_pels_y=0),
                PyramidLevel(z=2, num_tiles_x=24, num_tiles_y=16, empty_pels_x=0, empty_pels_y=0),
            ],
        )

        self.assertEqual(select_download_level(tile_info, size=DownloadSize.PREVIEW, max_dimension=None).z, 0)
        self.assertEqual(select_download_level(tile_info, size=DownloadSize.MEDIUM, max_dimension=None).z, 1)
        self.assertEqual(select_download_level(tile_info, size=DownloadSize.MAX, max_dimension=None).z, 2)

    def test_select_download_level_honors_max_dimension(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[
                PyramidLevel(z=0, num_tiles_x=2, num_tiles_y=2, empty_pels_x=0, empty_pels_y=0),
                PyramidLevel(z=1, num_tiles_x=8, num_tiles_y=8, empty_pels_x=0, empty_pels_y=0),
                PyramidLevel(z=2, num_tiles_x=24, num_tiles_y=16, empty_pels_x=0, empty_pels_y=0),
            ],
        )

        self.assertEqual(select_download_level(tile_info, size=DownloadSize.MAX, max_dimension=1500).z, 0)
        self.assertEqual(select_download_level(tile_info, size=DownloadSize.MAX, max_dimension=3000).z, 1)
        self.assertEqual(select_download_level(tile_info, size=DownloadSize.MAX, max_dimension=10000).z, 2)

    def test_list_size_options_reports_all_levels(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[
                PyramidLevel(z=0, num_tiles_x=2, num_tiles_y=1, empty_pels_x=0, empty_pels_y=0),
                PyramidLevel(z=1, num_tiles_x=4, num_tiles_y=3, empty_pels_x=0, empty_pels_y=0),
            ],
        )

        options = list_size_options(tile_info)
        self.assertEqual([option.level.z for option in options], [0, 1])
        self.assertEqual(options[0].width, 512)
        self.assertEqual(options[1].tile_count, 12)
        self.assertEqual(options[0].raw_memory_bytes, 512 * 256 * 3)
        self.assertEqual(options[0].default_backend, StitchBackend.PILLOW)

    def test_list_size_options_marks_large_levels_for_bigtiff(self) -> None:
        tile_info = TileInfo(
            tile_width=256,
            tile_height=256,
            levels=[PyramidLevel(z=0, num_tiles_x=10, num_tiles_y=10, empty_pels_x=0, empty_pels_y=0)],
        )

        from unittest.mock import patch

        with patch("googleart_download.download.image_writer._read_available_memory_bytes", return_value=1024):
            options = list_size_options(tile_info)

        self.assertEqual(options[0].default_backend, StitchBackend.BIGTIFF)

    def test_resolve_output_path_adds_size_suffix_for_non_max(self) -> None:
        path = resolve_output_path(
            Path("/tmp"),
            None,
            "The Starry Night",
            download_size=DownloadSize.MEDIUM,
            max_dimension=None,
        )
        self.assertEqual(path.name, "The Starry Night.medium.jpg")

    def test_resolve_output_path_keeps_max_without_suffix(self) -> None:
        path = resolve_output_path(
            Path("/tmp"),
            None,
            "The Starry Night",
            download_size=DownloadSize.MAX,
            max_dimension=None,
        )
        self.assertEqual(path.name, "The Starry Night.jpg")

    def test_resolve_output_path_uses_max_dimension_suffix(self) -> None:
        path = resolve_output_path(
            Path("/tmp"),
            None,
            "The Starry Night",
            download_size=DownloadSize.MAX,
            max_dimension=8000,
        )
        self.assertEqual(path.name, "The Starry Night.maxdim-8000.jpg")

    def test_build_temp_output_path_preserves_image_extension(self) -> None:
        path = build_temp_output_path(Path("/tmp/The Starry Night.preview.jpg"))
        self.assertEqual(path.name, "The Starry Night.preview.part.jpg")

    def test_save_with_pillow_uses_configured_jpeg_quality(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "art.jpg"
            image = Image.new("RGB", (8, 8), (255, 255, 255))
            temp_output_path = build_temp_output_path(output_path)

            def fake_save(*args, **kwargs):  # type: ignore[no-untyped-def]
                temp_output_path.write_bytes(b"jpeg")

            with patch.object(image, "save", side_effect=fake_save) as save_mock:
                _save_with_pillow(
                    image,
                    output_path,
                    metadata=None,
                    write_metadata=False,
                    jpeg_quality=82,
                )

            save_mock.assert_called_once()
            self.assertEqual(save_mock.call_args.kwargs["quality"], 82)

    def test_build_bigtiff_temp_path_uses_tiff_extension(self) -> None:
        path = build_bigtiff_temp_path(Path("/tmp/The Starry Night.preview.jpg"))
        self.assertEqual(path.name, "The Starry Night.preview.part.bigtiff.tif")

    def test_resolve_backend_output_path_uses_tiff_for_bigtiff_backend(self) -> None:
        path = resolve_backend_output_path(Path("/tmp/The Starry Night.jpg"), StitchBackend.BIGTIFF)
        self.assertEqual(path.name, "The Starry Night.tif")

    def test_resolve_backend_output_path_keeps_existing_tiff_extension(self) -> None:
        path = resolve_backend_output_path(Path("/tmp/The Starry Night.tiff"), StitchBackend.BIGTIFF)
        self.assertEqual(path.name, "The Starry Night.tiff")

    def test_resolve_backend_output_path_keeps_normal_jpg_for_pillow(self) -> None:
        path = resolve_backend_output_path(Path("/tmp/The Great Wave.jpg"), StitchBackend.PILLOW)
        self.assertEqual(path.name, "The Great Wave.jpg")

    def test_resolve_non_conflicting_output_path_keeps_unused_path(self) -> None:
        path = resolve_non_conflicting_output_path(Path("/tmp/The Great Wave.jpg"))
        self.assertEqual(path.name, "The Great Wave.jpg")

    def test_resolve_non_conflicting_output_path_adds_numeric_suffix(self) -> None:
        with TemporaryDirectory() as tmpdir:
            original = Path(tmpdir) / "The Great Wave.jpg"
            original.write_bytes(b"existing")

            second = resolve_non_conflicting_output_path(original)
            self.assertEqual(second.name, "The Great Wave.2.jpg")
            second.write_bytes(b"existing")

            third = resolve_non_conflicting_output_path(original)
            self.assertEqual(third.name, "The Great Wave.3.jpg")

    def test_cleanup_stale_partial_outputs_removes_old_jpeg_temp_for_bigtiff(self) -> None:
        with TemporaryDirectory() as tmpdir:
            original = Path(tmpdir) / "The Starry Night.jpg"
            final = Path(tmpdir) / "The Starry Night.tif"
            stale = build_temp_output_path(original)
            stale.write_bytes(b"partial")

            removed = cleanup_stale_partial_outputs(original, final, StitchBackend.BIGTIFF)

            self.assertEqual(removed, [stale])
            self.assertFalse(stale.exists())

    def test_cleanup_stale_partial_outputs_keeps_normal_partial_for_non_bigtiff(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "The Great Wave.jpg"
            stale = build_temp_output_path(output)
            stale.write_bytes(b"partial")

            removed = cleanup_stale_partial_outputs(output, output, StitchBackend.PILLOW)

            self.assertEqual(removed, [])
            self.assertTrue(stale.exists())

    def test_resolve_artwork_cache_dir_uses_stable_asset_url(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            output_path = output_dir / "art.jpg"
            first = resolve_artwork_cache_dir(
                output_dir,
                "https://artsandculture.google.com/asset/foo/bgEuwDxel93-Pg",
                output_path,
            )
            second = resolve_artwork_cache_dir(
                output_dir,
                "https://artsandculture.google.com/asset/foo/bgEuwDxel93-Pg",
                output_path,
            )

        self.assertEqual(first, second)

    def test_resolve_artwork_cache_dir_migrates_legacy_cache_by_output_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            output_path = output_dir / "art.jpg"
            legacy_dir = output_dir / ".googleart-cache" / "legacy-random"
            tiles_dir = ensure_cache_layout(legacy_dir)
            (tiles_dir / "7-0-0.tile").write_bytes(b"tile")
            (legacy_dir / "state.json").write_text(
                json.dumps(
                    {
                        "output_path": str(output_path),
                        "completed_tiles": 123,
                    }
                ),
                encoding="utf-8",
            )

            resolved = resolve_artwork_cache_dir(
                output_dir,
                "https://artsandculture.google.com/asset/foo/bgEuwDxel93-Pg",
                output_path,
            )

            self.assertTrue(resolved.exists())
            self.assertTrue((resolved / "tiles" / "7-0-0.tile").exists())
            self.assertNotEqual(resolved.name, "legacy-random")


if __name__ == "__main__":
    unittest.main()

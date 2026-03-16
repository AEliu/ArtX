from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from googleart_download import cli
from googleart_download.download.downloader import download_artwork
from googleart_download.models import (
    ArtworkMetadata,
    DownloadResult,
    DownloadSize,
    OutputConflictPolicy,
    PageInfo,
    PyramidLevel,
    RetryConfig,
    StitchBackend,
    TileInfo,
    TileJob,
)
from googleart_download.reporting import Reporter


class SilentReporter(Reporter):
    pass


class CliIntegrationWorkflowTests(unittest.TestCase):
    def test_download_artwork_writes_sidecar_and_exif(self) -> None:
        metadata = ArtworkMetadata(
            title="The Great Wave",
            creator="Katsushika Hokusai",
            description="A famous ukiyo-e print.",
            source_url="https://artsandculture.google.com/asset/example/id",
            rights="Public domain",
        )
        page = PageInfo(
            title="The Great Wave",
            base_url="https://lh3.googleusercontent.com/example",
            token="token",
            asset_url="https://artsandculture.google.com/asset/example/id",
            metadata=metadata,
        )
        assert page.asset_url is not None
        tile_info = TileInfo(
            tile_width=8,
            tile_height=8,
            levels=[PyramidLevel(z=0, num_tiles_x=1, num_tiles_y=1, empty_pels_x=0, empty_pels_y=0)],
        )
        jobs = [TileJob(z=0, x=0, y=0, url="https://example.com/tile")]
        assert page.asset_url is not None

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            tile_path = output_dir / "tile.png"
            Image.new("RGB", (8, 8), (0, 128, 255)).save(tile_path, format="PNG")

            fake_client = SilentReporter()

            with patch("googleart_download.download.downloader.HttpClient") as client_cls:
                client = client_cls.return_value.__enter__.return_value
                client.fetch_text_with_url.return_value = ("<html></html>", page.asset_url)
                client.fetch_bytes.return_value = b"tile-metadata"

                with patch("googleart_download.download.downloader.AsyncHttpClient"):
                    with patch("googleart_download.download.downloader.parse_page_info", return_value=page):
                        with patch("googleart_download.download.downloader.parse_tile_info", return_value=tile_info):
                            with patch("googleart_download.download.downloader.build_jobs", return_value=jobs):
                                with patch(
                                    "googleart_download.download.downloader.await_download_tiles",
                                    return_value={(0, 0): tile_path},
                                ):
                                    result = download_artwork(
                                        url=page.asset_url,
                                        output_dir=output_dir,
                                        filename=None,
                                        workers=1,
                                        jpeg_quality=85,
                                        retry_config=RetryConfig(attempts=1),
                                        download_size=DownloadSize.MAX,
                                        max_dimension=None,
                                        output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                                        write_metadata=True,
                                        write_sidecar=True,
                                        stitch_backend=StitchBackend.PILLOW,
                                        reporter=fake_client,
                                        index=1,
                                        total=1,
                                    )

            self.assertTrue(result.output_path.exists())
            self.assertIsNotNone(result.sidecar_path)
            assert result.sidecar_path is not None
            self.assertTrue(result.sidecar_path.exists())

            sidecar_payload = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(sidecar_payload["title"], "The Great Wave")
            self.assertEqual(sidecar_payload["creator"], "Katsushika Hokusai")

            with Image.open(result.output_path) as output_image:
                exif = output_image.getexif()
                self.assertEqual(exif.get(315), "Katsushika Hokusai")
                self.assertIn("ukiyo-e", exif.get(270, ""))

    def test_download_artwork_uses_async_tile_download_path(self) -> None:
        page = PageInfo(
            title="The Great Wave",
            base_url="https://lh3.googleusercontent.com/example",
            token="token",
            asset_url="https://artsandculture.google.com/asset/example/id",
            metadata=None,
        )
        tile_info = TileInfo(
            tile_width=8,
            tile_height=8,
            levels=[PyramidLevel(z=0, num_tiles_x=1, num_tiles_y=1, empty_pels_x=0, empty_pels_y=0)],
        )
        jobs = [TileJob(z=0, x=0, y=0, url="https://example.com/tile")]
        assert page.asset_url is not None

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            tile_path = output_dir / "tile.png"
            Image.new("RGB", (8, 8), (0, 128, 255)).save(tile_path, format="PNG")

            with patch("googleart_download.download.downloader.HttpClient") as client_cls:
                client = client_cls.return_value.__enter__.return_value
                client.fetch_text_with_url.return_value = ("<html></html>", page.asset_url)
                client.fetch_bytes.return_value = b"tile-metadata"

                with patch("googleart_download.download.downloader.AsyncHttpClient"):
                    with patch("googleart_download.download.downloader.parse_page_info", return_value=page):
                        with patch("googleart_download.download.downloader.parse_tile_info", return_value=tile_info):
                            with patch("googleart_download.download.downloader.build_jobs", return_value=jobs):
                                with patch(
                                    "googleart_download.download.downloader.await_download_tiles",
                                    return_value={(0, 0): tile_path},
                                ) as await_download_tiles_mock:
                                    download_artwork(
                                        url=page.asset_url,
                                        output_dir=output_dir,
                                        filename=None,
                                        workers=3,
                                        jpeg_quality=85,
                                        retry_config=RetryConfig(attempts=1),
                                        download_size=DownloadSize.MAX,
                                        max_dimension=None,
                                        output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                                        write_metadata=False,
                                        write_sidecar=False,
                                        stitch_backend=StitchBackend.PILLOW,
                                        reporter=SilentReporter(),
                                        index=1,
                                        total=1,
                                    )

            await_download_tiles_mock.assert_called_once()
            self.assertEqual(await_download_tiles_mock.call_args.kwargs["workers"], 3)
            self.assertEqual(await_download_tiles_mock.call_args.args[0], jobs)
            self.assertEqual(await_download_tiles_mock.call_args.kwargs["retry_config"], RetryConfig(attempts=1))
            self.assertIsNone(await_download_tiles_mock.call_args.kwargs["proxy_url"])

    def test_resume_batch_via_cli_reuses_saved_state(self) -> None:
        first_url = "https://artsandculture.google.com/asset/example/one"
        second_url = "https://artsandculture.google.com/asset/example/two"

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            state_path = output_dir / ".googleart-batch-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:01+00:00",
                        "urls": [first_url, second_url],
                        "tasks": [
                            {
                                "index": 1,
                                "url": first_url,
                                "state": "succeeded",
                                "attempts": 1,
                                "result": {
                                    "url": first_url,
                                    "output_path": str(output_dir / "one.jpg"),
                                    "title": "one",
                                    "size": [10, 10],
                                    "tile_count": 1,
                                    "skipped": False,
                                },
                            },
                            {
                                "index": 2,
                                "url": second_url,
                                "state": "running",
                                "attempts": 2,
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            calls: list[str] = []

            def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
                calls.append(kwargs["url"])
                return DownloadResult(
                    url=kwargs["url"],
                    output_path=output_dir / "two.jpg",
                    title="two",
                    size=(10, 10),
                    tile_count=1,
                )

            with patch("googleart_download.cli.build_reporter", return_value=SilentReporter()):
                with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                    code = cli.main([first_url, second_url, "-o", tmpdir, "--resume-batch"])

            self.assertEqual(code, 0)
            self.assertEqual(calls, [second_url])

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["tasks"][0]["state"], "succeeded")
            self.assertEqual(payload["tasks"][0]["attempts"], 1)
            self.assertEqual(payload["tasks"][1]["state"], "succeeded")
            self.assertEqual(payload["tasks"][1]["attempts"], 3)

    def test_skip_and_rerun_failures_combination_via_batch_manager(self) -> None:
        skipped_url = "https://artsandculture.google.com/asset/example/skipped"
        flaky_url = "https://artsandculture.google.com/asset/example/flaky"

        with TemporaryDirectory() as tmpdir:
            calls: list[str] = []
            failure_count = {"flaky": 0}

            def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
                url = kwargs["url"]
                calls.append(url)
                if url == skipped_url:
                    return DownloadResult(
                        url=url,
                        output_path=Path(tmpdir) / "skipped.jpg",
                        title="skipped",
                        size=None,
                        tile_count=None,
                        skipped=True,
                    )
                if url == flaky_url and failure_count["flaky"] == 0:
                    failure_count["flaky"] += 1
                    from googleart_download.errors import DownloadError

                    raise DownloadError("boom")
                return DownloadResult(
                    url=url,
                    output_path=Path(tmpdir) / "flaky.jpg",
                    title="flaky",
                    size=(10, 10),
                    tile_count=1,
                )

            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                from googleart_download.batch import BatchDownloadManager

                manager = BatchDownloadManager(
                    urls=[skipped_url, flaky_url],
                    output_dir=Path(tmpdir),
                    filename=None,
                    workers=1,
                    jpeg_quality=85,
                    retry_config=RetryConfig(attempts=1),
                    reporter=SilentReporter(),
                    fail_fast=False,
                    download_size=DownloadSize.MAX,
                    max_dimension=None,
                    output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                    write_metadata=False,
                    write_sidecar=False,
                    rerun_failures=1,
                )
                run_result = manager.run()

            self.assertEqual(calls.count(skipped_url), 1)
            self.assertEqual(calls.count(flaky_url), 2)
            self.assertEqual(run_result.snapshot.skipped, 1)
            self.assertEqual(run_result.snapshot.succeeded, 1)

    def test_rerun_failed_via_cli_creates_rerun_state_and_runs_only_failed_tasks(self) -> None:
        failed_url = "https://artsandculture.google.com/asset/example/failed"
        succeeded_url = "https://artsandculture.google.com/asset/example/succeeded"

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            state_path = output_dir / ".googleart-batch-state.json"
            rerun_state_path = output_dir / ".googleart-batch-rerun-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:01+00:00",
                        "urls": [failed_url, succeeded_url],
                        "tasks": [
                            {
                                "index": 1,
                                "url": failed_url,
                                "state": "failed",
                                "attempts": 1,
                                "error": "boom",
                            },
                            {
                                "index": 2,
                                "url": succeeded_url,
                                "state": "succeeded",
                                "attempts": 1,
                                "result": {
                                    "url": succeeded_url,
                                    "output_path": str(output_dir / "done.jpg"),
                                    "title": "done",
                                    "size": [10, 10],
                                    "tile_count": 1,
                                    "skipped": False,
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            calls: list[str] = []

            def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
                calls.append(kwargs["url"])
                return DownloadResult(
                    url=kwargs["url"],
                    output_path=output_dir / "rerun.jpg",
                    title="rerun",
                    size=(10, 10),
                    tile_count=1,
                )

            with patch("googleart_download.cli.build_reporter", return_value=SilentReporter()):
                with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                    code = cli.main(["--rerun-failed", "-o", tmpdir])

            self.assertEqual(code, 0)
            self.assertEqual(calls, [failed_url])
            self.assertTrue(rerun_state_path.exists())
            payload = json.loads(rerun_state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["urls"], [failed_url])
            self.assertEqual(payload["tasks"][0]["state"], "succeeded")

    def test_output_conflict_policies_flow_from_cli_into_batch_downloads(self) -> None:
        url = "https://artsandculture.google.com/asset/example/id"

        scenarios = [
            (["--output-conflict", "rename"], OutputConflictPolicy.RENAME),
            (["--no-skip-existing"], OutputConflictPolicy.OVERWRITE),
        ]

        for extra_args, expected_policy in scenarios:
            with self.subTest(expected_policy=expected_policy):
                seen_policies: list[OutputConflictPolicy] = []
                with TemporaryDirectory() as tmpdir:

                    def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
                        seen_policies.append(kwargs["output_conflict_policy"])
                        return DownloadResult(
                            url=kwargs["url"],
                            output_path=Path(tmpdir) / "result.jpg",
                            title="result",
                            size=(10, 10),
                            tile_count=1,
                        )

                    with patch("googleart_download.cli.build_reporter", return_value=SilentReporter()):
                        with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                            code = cli.main([url, "-o", tmpdir, *extra_args])

                self.assertEqual(code, 0)
                self.assertEqual(seen_policies, [expected_policy])

    def test_large_image_result_via_cli_persists_tiff_backend_and_summary(self) -> None:
        url = "https://artsandculture.google.com/asset/example/large"

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            state_path = output_dir / ".googleart-batch-state.json"
            stdout = io.StringIO()

            def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
                return DownloadResult(
                    url=kwargs["url"],
                    output_path=output_dir / "large-artwork.tif",
                    title="Large Artwork",
                    size=(44567, 35291),
                    tile_count=6072,
                    backend_used=StitchBackend.BIGTIFF,
                )

            with patch("googleart_download.cli.build_reporter", return_value=SilentReporter()):
                with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                    with redirect_stdout(stdout):
                        code = cli.main([url, "-o", tmpdir])

            self.assertEqual(code, 0)
            summary = stdout.getvalue()
            self.assertIn("Format", summary)
            self.assertIn("TIF", summary)
            self.assertIn("bigti", summary)

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["tasks"][0]["result"]["output_path"], str(output_dir / "large-artwork.tif"))
            self.assertEqual(payload["tasks"][0]["result"]["backend_used"], "bigtiff")


if __name__ == "__main__":
    unittest.main()

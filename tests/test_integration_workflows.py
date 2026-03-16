from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from googleart_download import cli
from googleart_download.models import DownloadResult, OutputConflictPolicy, StitchBackend
from googleart_download.reporting import Reporter


class SilentReporter(Reporter):
    pass


class CliIntegrationWorkflowTests(unittest.TestCase):
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

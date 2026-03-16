from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from googleart_download import cli
from googleart_download.models import BatchRunResult, BatchSnapshot, DownloadResult, StitchBackend


class DummyReporter:
    def close(self) -> None:
        pass


class CliTests(unittest.TestCase):
    def test_canonicalize_batch_urls_dedupes_equivalent_asset_urls(self) -> None:
        urls = [
            "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q",
            "https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q?ms=%7B%7D",
        ]

        unique_urls, duplicate_messages = cli.canonicalize_batch_urls(urls, cli.RetryConfig(attempts=1))

        self.assertEqual(unique_urls, ["https://artsandculture.google.com/asset/girl-with-a-pearl-earring/3QFHLJgXCmQm2Q"])
        self.assertEqual(len(duplicate_messages), 1)
        self.assertIn("Duplicate artwork input skipped", duplicate_messages[0])

    def test_canonicalize_batch_urls_resolves_gco_short_link(self) -> None:
        mock_client = MagicMock()
        mock_client.resolve_url.return_value = (
            "https://artsandculture.google.com/asset/girl-with-a-pearl-earring-johannes-vermeer/3QFHLJgXCmQm2Q"
        )
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None

        with patch("googleart_download.cli.HttpClient", return_value=mock_client):
            unique_urls, duplicate_messages = cli.canonicalize_batch_urls(
                [
                    "https://g.co/arts/Qfd8qwjbwKsC417o8",
                    "3QFHLJgXCmQm2Q",
                ],
                cli.RetryConfig(attempts=1),
            )

        self.assertEqual(
            unique_urls,
            ["https://artsandculture.google.com/asset/girl-with-a-pearl-earring-johannes-vermeer/3QFHLJgXCmQm2Q"],
        )
        self.assertEqual(len(duplicate_messages), 1)
        self.assertIn("same artwork", duplicate_messages[0])

    def test_resume_batch_conflicts_with_metadata_only(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--resume-batch",
                    "--metadata-only",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--resume-batch cannot be used together with --metadata-only", stderr.getvalue())

    def test_resume_batch_conflicts_with_rerun_failed(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "--resume-batch",
                    "--rerun-failed",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--resume-batch cannot be used together with --rerun-failed", stderr.getvalue())

    def test_batch_state_file_conflicts_with_list_sizes(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--batch-state-file",
                    "state.json",
                    "--list-sizes",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--batch-state-file cannot be used together with --list-sizes", stderr.getvalue())

    def test_metadata_only_with_multiple_urls_rejects_filename(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/one",
                    "https://artsandculture.google.com/asset/example/two",
                    "--metadata-only",
                    "--filename",
                    "metadata.json",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--filename cannot be used with multiple URLs in --metadata-only mode", stderr.getvalue())

    def test_metadata_output_requires_metadata_only(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--metadata-output",
                    "out.json",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--metadata-output requires --metadata-only", stderr.getvalue())

    def test_metadata_only_conflicts_with_list_sizes(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--metadata-only",
                    "--list-sizes",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--metadata-only cannot be used together with --list-sizes", stderr.getvalue())

    def test_rerun_failed_rejects_direct_urls(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--rerun-failed",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--rerun-failed loads failed URLs from the batch state file", stderr.getvalue())
        self.assertIn("combined with direct batch URLs", stderr.getvalue())

    def test_single_url_metadata_only_writes_default_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with patch("googleart_download.cli.inspect_artwork_metadata", return_value={"title": "Artwork", "creator": "Artist"}):
                with patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        code = cli.main(
                            [
                                "https://artsandculture.google.com/asset/example/id",
                                "--metadata-only",
                                "-o",
                                tmpdir,
                            ]
                        )
            self.assertEqual(code, 0)
            output_path = Path(tmpdir) / "Artwork.metadata.json"
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, [{"title": "Artwork", "creator": "Artist"}])
            self.assertIn("Metadata saved", stderr.getvalue())

    def test_single_url_metadata_only_falls_back_to_google_art_filename_when_title_missing(self) -> None:
        fallback_payloads = [
            {},
            {"title": ""},
            {"title": 123},
        ]

        for payload in fallback_payloads:
            with self.subTest(payload=payload):
                with TemporaryDirectory() as tmpdir:
                    with patch("googleart_download.cli.inspect_artwork_metadata", return_value=payload):
                        with patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
                            stderr = io.StringIO()
                            with redirect_stderr(stderr):
                                code = cli.main(
                                    [
                                        "https://artsandculture.google.com/asset/example/id",
                                        "--metadata-only",
                                        "-o",
                                        tmpdir,
                                    ]
                                )
                    self.assertEqual(code, 0)
                    output_path = Path(tmpdir) / "google-art.metadata.json"
                    self.assertTrue(output_path.exists())
                    saved_payload = json.loads(output_path.read_text(encoding="utf-8"))
                    self.assertEqual(saved_payload, [payload])
                    self.assertIn("Metadata saved", stderr.getvalue())

    def test_multi_url_metadata_only_outputs_json_array_to_stdout(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch(
            "googleart_download.cli.inspect_artwork_metadata",
            side_effect=[{"title": "One"}, {"title": "Two"}],
        ):
            with patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = cli.main(
                        [
                            "https://artsandculture.google.com/asset/example/one",
                            "https://artsandculture.google.com/asset/example/two",
                            "--metadata-only",
                        ]
                    )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, [{"title": "One"}, {"title": "Two"}])
        self.assertIn("default to a JSON array on stdout", stderr.getvalue())

    def test_metadata_output_writes_file_instead_of_stdout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "metadata.json"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("googleart_download.cli.inspect_artwork_metadata", return_value={"title": "Artwork"}):
                with patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = cli.main(
                            [
                                "https://artsandculture.google.com/asset/example/id",
                                "--metadata-only",
                                "--metadata-output",
                                str(output_path),
                            ]
                        )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, [{"title": "Artwork"}])
            self.assertIn("Metadata saved", stderr.getvalue())

    def test_no_skip_existing_conflicts_with_output_conflict(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), patch("googleart_download.cli.build_reporter", return_value=DummyReporter()):
            code = cli.main(
                [
                    "https://artsandculture.google.com/asset/example/id",
                    "--no-skip-existing",
                    "--output-conflict",
                    "rename",
                ]
            )
        self.assertEqual(code, 1)
        self.assertIn("--no-skip-existing cannot be used together with --output-conflict", stderr.getvalue())

    def test_main_logs_when_batch_inputs_are_deduped(self) -> None:
        reporter = MagicMock()
        fake_manager = MagicMock()
        fake_manager.run.return_value = BatchRunResult(snapshot=BatchSnapshot(tasks=[]), succeeded=[], failed=[])

        with patch("googleart_download.cli.build_reporter", return_value=reporter):
            with patch(
                "googleart_download.cli.canonicalize_batch_urls",
                return_value=(
                    ["https://artsandculture.google.com/asset/example/id"],
                    ["Duplicate artwork input skipped: duplicate"],
                ),
            ):
                with patch("googleart_download.cli.BatchDownloadManager", return_value=fake_manager):
                    with patch("googleart_download.cli.render_summary"):
                        code = cli.main(
                            [
                                "https://artsandculture.google.com/asset/example/id",
                                "https://g.co/arts/example",
                            ]
                        )

        self.assertEqual(code, 0)
        reporter.log.assert_any_call("Duplicate artwork input skipped: duplicate")
        reporter.log.assert_any_call("Batch input normalized from 2 URL(s) to 1 unique artwork(s)")

    def test_rerun_failed_loads_failed_urls_into_new_batch(self) -> None:
        reporter = MagicMock()
        fake_manager = MagicMock()
        fake_manager.run.return_value = BatchRunResult(snapshot=BatchSnapshot(tasks=[]), succeeded=[], failed=[])

        with patch("googleart_download.cli.build_reporter", return_value=reporter):
            with patch(
                "googleart_download.cli.load_failed_batch_urls",
                return_value=(
                    [
                        "https://artsandculture.google.com/asset/example/failed-one",
                        "https://artsandculture.google.com/asset/example/failed-two",
                    ],
                    Path("downloads/.googleart-batch-state.json"),
                    Path("downloads/.googleart-batch-rerun-state.json"),
                ),
            ):
                with patch("googleart_download.cli.BatchDownloadManager", return_value=fake_manager) as manager_cls:
                    with patch("googleart_download.cli.render_summary"):
                        code = cli.main(["--rerun-failed"])

        self.assertEqual(code, 0)
        manager_cls.assert_called_once()
        kwargs = manager_cls.call_args.kwargs
        self.assertEqual(
            kwargs["urls"],
            [
                "https://artsandculture.google.com/asset/example/failed-one",
                "https://artsandculture.google.com/asset/example/failed-two",
            ],
        )
        self.assertEqual(kwargs["batch_state_file"], "downloads/.googleart-batch-rerun-state.json")
        reporter.log.assert_any_call("Loaded 2 failed artwork(s) from downloads/.googleart-batch-state.json")

    def test_rerun_failed_exits_cleanly_when_no_failed_tasks_exist(self) -> None:
        reporter = MagicMock()

        with patch("googleart_download.cli.build_reporter", return_value=reporter):
            with patch(
                "googleart_download.cli.load_failed_batch_urls",
                return_value=(
                    [],
                    Path("downloads/.googleart-batch-state.json"),
                    Path("downloads/.googleart-batch-rerun-state.json"),
                ),
            ):
                with patch("googleart_download.cli.BatchDownloadManager") as manager_cls:
                    code = cli.main(["--rerun-failed"])

        self.assertEqual(code, 0)
        manager_cls.assert_not_called()
        reporter.log.assert_any_call("No failed tasks found in batch state file: downloads/.googleart-batch-state.json")

    def test_render_summary_shows_output_format_and_backend(self) -> None:
        stdout = io.StringIO()
        run_result = BatchRunResult(
            snapshot=BatchSnapshot(tasks=[]),
            succeeded=[
                DownloadResult(
                    url="https://artsandculture.google.com/asset/example/id",
                    output_path=Path("downloads/The Starry Night.tif"),
                    title="The Starry Night",
                    size=(44567, 35291),
                    tile_count=6072,
                    backend_used=StitchBackend.BIGTIFF,
                )
            ],
            failed=[],
        )

        with redirect_stdout(stdout):
            cli.render_summary(run_result)

        output = stdout.getvalue()
        self.assertIn("Format", output)
        self.assertIn("TIF", output)
        self.assertIn("bigti", output)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from googleart_download import cli


class DummyReporter:
    def close(self) -> None:
        pass


class CliTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

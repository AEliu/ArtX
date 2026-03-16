from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from googleart_download.batch import BatchDownloadManager, BatchStateStore
from googleart_download.errors import DownloadError
from googleart_download.models import DownloadResult, DownloadSize, OutputConflictPolicy, RetryConfig, TaskState
from googleart_download.reporting import Reporter


class SilentReporter(Reporter):
    pass


class BatchManagerTests(unittest.TestCase):
    def test_batch_state_store_load_failed_urls(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / ".googleart-batch-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:01+00:00",
                        "urls": [
                            "https://artsandculture.google.com/asset/example/one",
                            "https://artsandculture.google.com/asset/example/two",
                        ],
                        "tasks": [
                            {
                                "index": 1,
                                "url": "https://artsandculture.google.com/asset/example/one",
                                "state": "failed",
                                "attempts": 1,
                                "error": "boom",
                            },
                            {
                                "index": 2,
                                "url": "https://artsandculture.google.com/asset/example/two",
                                "state": "succeeded",
                                "attempts": 1,
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            failed_urls = BatchStateStore(state_path).load_failed_urls()

        self.assertEqual(failed_urls, ["https://artsandculture.google.com/asset/example/one"])

    def test_persists_batch_state_file(self) -> None:
        first_url = "https://artsandculture.google.com/asset/example/one"
        second_url = "https://artsandculture.google.com/asset/example/two"

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            return DownloadResult(
                url=url,
                output_path=Path("/tmp/out.jpg"),
                title="ok",
                size=(10, 10),
                tile_count=1,
            )

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=[first_url, second_url],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                jpeg_quality=95,
                retry_config=RetryConfig(attempts=1),
                reporter=SilentReporter(),
                fail_fast=False,
                download_size=DownloadSize.MAX,
                max_dimension=None,
                output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                write_metadata=False,
                write_sidecar=False,
            )
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

            state_path = Path(tmpdir) / ".googleart-batch-state.json"
            self.assertTrue(state_path.exists())
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)
            self.assertEqual(len(payload["tasks"]), 2)
            self.assertEqual(result.snapshot.succeeded, 2)
            self.assertEqual(payload["tasks"][0]["state"], "succeeded")

    def test_reruns_failed_tasks_and_tracks_attempts(self) -> None:
        calls: list[str] = []
        bad_url = "https://artsandculture.google.com/asset/bad/example"
        good_url = "https://artsandculture.google.com/asset/good/example"

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            calls.append(url)
            if "bad" in url:
                raise DownloadError("boom")
            return DownloadResult(
                url=url,
                output_path=Path("/tmp/out.jpg"),
                title="ok",
                size=(10, 10),
                tile_count=1,
            )

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=[bad_url, good_url],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                jpeg_quality=95,
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
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

        self.assertEqual(calls.count(bad_url), 2)
        self.assertEqual(calls.count(good_url), 1)
        self.assertEqual(result.snapshot.succeeded, 1)
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.rerun_rounds, 1)
        failed_task = next(task for task in result.snapshot.tasks if task.url == bad_url)
        self.assertEqual(failed_task.state, TaskState.FAILED)
        self.assertEqual(failed_task.attempts, 2)

    def test_resume_batch_reuses_saved_state_and_resets_running_tasks(self) -> None:
        calls: list[str] = []

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            calls.append(url)
            return DownloadResult(
                url=url,
                output_path=Path("/tmp/out.jpg"),
                title="ok",
                size=(10, 10),
                tile_count=1,
            )

        with TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / ".googleart-batch-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:01+00:00",
                        "urls": ["https://artsandculture.google.com/asset/example/one", "https://artsandculture.google.com/asset/example/two"],
                        "tasks": [
                            {
                                "index": 1,
                                "url": "https://artsandculture.google.com/asset/example/one",
                                "state": "succeeded",
                                "attempts": 1,
                                "result": {
                                    "url": "https://artsandculture.google.com/asset/example/one",
                                    "output_path": "/tmp/one.jpg",
                                    "title": "one",
                                    "size": [10, 10],
                                    "tile_count": 1,
                                    "skipped": False,
                                },
                            },
                            {
                                "index": 2,
                                "url": "https://artsandculture.google.com/asset/example/two",
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
            manager = BatchDownloadManager(
                urls=[
                    "https://artsandculture.google.com/asset/example/one",
                    "https://artsandculture.google.com/asset/example/two",
                ],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                jpeg_quality=95,
                retry_config=RetryConfig(attempts=1),
                reporter=SilentReporter(),
                fail_fast=False,
                download_size=DownloadSize.MAX,
                max_dimension=None,
                output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                write_metadata=False,
                write_sidecar=False,
                resume_batch=True,
            )
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

            self.assertEqual(calls, ["https://artsandculture.google.com/asset/example/two"])
            first_task = result.snapshot.tasks[0]
            second_task = result.snapshot.tasks[1]
            self.assertEqual(first_task.state, TaskState.SUCCEEDED)
            self.assertEqual(first_task.attempts, 1)
            self.assertEqual(second_task.state, TaskState.SUCCEEDED)
            self.assertEqual(second_task.attempts, 3)

    def test_resume_batch_rejects_missing_state_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with self.assertRaises(DownloadError):
                BatchDownloadManager(
                    urls=["https://artsandculture.google.com/asset/example/one"],
                    output_dir=Path(tmpdir),
                    filename=None,
                    workers=1,
                    jpeg_quality=95,
                    retry_config=RetryConfig(attempts=1),
                    reporter=SilentReporter(),
                    fail_fast=False,
                    download_size=DownloadSize.MAX,
                    max_dimension=None,
                    output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                    write_metadata=False,
                    write_sidecar=False,
                    resume_batch=True,
                )

    def test_fail_fast_stops_current_round(self) -> None:
        calls: list[str] = []
        first_url = "https://artsandculture.google.com/asset/bad-1/example"
        second_url = "https://artsandculture.google.com/asset/bad-2/example"

        def fake_download_artwork(**kwargs):  # type: ignore[no-untyped-def]
            url = kwargs["url"]
            calls.append(url)
            raise DownloadError("boom")

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=[first_url, second_url],
                output_dir=Path(tmpdir),
                filename=None,
                workers=1,
                jpeg_quality=95,
                retry_config=RetryConfig(attempts=1),
                reporter=SilentReporter(),
                fail_fast=True,
                download_size=DownloadSize.MAX,
                max_dimension=None,
                output_conflict_policy=OutputConflictPolicy.OVERWRITE,
                write_metadata=False,
                write_sidecar=False,
                rerun_failures=2,
            )
            with patch("googleart_download.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

        self.assertEqual(calls, [first_url])
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.snapshot.pending, 1)


if __name__ == "__main__":
    unittest.main()

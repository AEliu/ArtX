from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from artx.batch import BatchDownloadManager, BatchStateStore
from artx.download.downloader import PreparedArtworkDownload
from artx.errors import DownloadError
from artx.models import DownloadResult, DownloadSize, OutputConflictPolicy, RetryConfig, TaskState
from artx.reporting import Reporter


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
            with patch("artx.batch.download_artwork", side_effect=fake_download_artwork):
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
            with patch("artx.batch.download_artwork", side_effect=fake_download_artwork):
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
                        "urls": [
                            "https://artsandculture.google.com/asset/example/one",
                            "https://artsandculture.google.com/asset/example/two",
                        ],
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
            with patch("artx.batch.download_artwork", side_effect=fake_download_artwork):
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
            with patch("artx.batch.download_artwork", side_effect=fake_download_artwork):
                result = manager.run()

        self.assertEqual(calls, [first_url])
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.snapshot.pending, 1)

    def test_pipeline_artworks_overlaps_next_download_with_previous_finalize(self) -> None:
        first_url = "https://artsandculture.google.com/asset/example/one"
        second_url = "https://artsandculture.google.com/asset/example/two"
        finalize_started = threading.Event()
        second_download_started = threading.Event()
        allow_finalize = threading.Event()
        prepared_by_url: dict[str, PreparedArtworkDownload] = {}

        def fake_prepare(task):  # type: ignore[no-untyped-def]
            prepared = PreparedArtworkDownload(data=MagicMock(), workspace=MagicMock(), tiles={})
            prepared_by_url[task.url] = prepared
            if task.url == second_url:
                second_download_started.set()
                self.assertTrue(finalize_started.is_set())
            return prepared

        def fake_finalize(prepared):  # type: ignore[no-untyped-def]
            finalize_started.set()
            allow_finalize.wait(timeout=2)
            matched_url = next(url for url, candidate in prepared_by_url.items() if candidate is prepared)
            return DownloadResult(
                url=matched_url,
                output_path=Path("/tmp/out.jpg"),
                title=matched_url.rsplit("/", 1)[-1],
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
                pipeline_artworks=True,
            )
            with (
                patch.object(manager, "_run_download_phase_for_task", side_effect=fake_prepare),
                patch.object(manager, "_run_finalize_phase_for_prepared", side_effect=fake_finalize),
            ):
                runner = threading.Thread(target=manager.run)
                runner.start()
                self.assertTrue(finalize_started.wait(timeout=2))
                self.assertTrue(second_download_started.wait(timeout=2))
                allow_finalize.set()
                runner.join(timeout=2)
                self.assertFalse(runner.is_alive())

    def test_pipeline_artworks_fail_fast_stops_launching_new_downloads(self) -> None:
        first_url = "https://artsandculture.google.com/asset/example/one"
        second_url = "https://artsandculture.google.com/asset/example/two"
        calls: list[str] = []

        def fake_prepare(task):  # type: ignore[no-untyped-def]
            calls.append(task.url)
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
                pipeline_artworks=True,
            )
            with patch.object(manager, "_run_download_phase_for_task", side_effect=fake_prepare):
                result = manager.run()

        self.assertEqual(calls, [first_url])
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.snapshot.pending, 1)

    def test_pipeline_fail_fast_on_finalize_allows_queued_finalize_and_stops_new_downloads(self) -> None:
        url1 = "https://artsandculture.google.com/asset/example/one"
        url2 = "https://artsandculture.google.com/asset/example/two"
        url3 = "https://artsandculture.google.com/asset/example/three"

        calls_prepare: list[str] = []
        calls_finalize: list[str] = []

        finalize_started_url1 = threading.Event()
        second_prepared_ready = threading.Event()

        prepared_by_url: dict[str, PreparedArtworkDownload] = {}

        def fake_prepare(task):  # type: ignore[no-untyped-def]
            calls_prepare.append(task.url)
            prepared = PreparedArtworkDownload(data=MagicMock(), workspace=MagicMock(), tiles={})
            prepared_by_url[task.url] = prepared
            if task.url == url2:
                # ensure overlap: finalize for url1 has started before url2 finishes preparing
                self.assertTrue(finalize_started_url1.wait(timeout=2))
                second_prepared_ready.set()
            return prepared

        def fake_finalize(prepared):  # type: ignore[no-untyped-def]
            matched_url = next(url for url, candidate in prepared_by_url.items() if candidate is prepared)
            calls_finalize.append(matched_url)
            if matched_url == url1:
                # Start finalize for url1, but don't fail until url2 is prepared/queued
                finalize_started_url1.set()
                self.assertTrue(second_prepared_ready.wait(timeout=2))
                raise DownloadError("finalize failed")
            else:
                return DownloadResult(
                    url=matched_url,
                    output_path=Path("/tmp/out.jpg"),
                    title=matched_url.rsplit("/", 1)[-1],
                    size=(10, 10),
                    tile_count=1,
                )

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=[url1, url2, url3],
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
                pipeline_artworks=True,
            )
            with (
                patch.object(manager, "_run_download_phase_for_task", side_effect=fake_prepare),
                patch.object(manager, "_run_finalize_phase_for_prepared", side_effect=fake_finalize),
            ):
                result = manager.run()

        # The first two downloads must launch in order; a third may start before the
        # finalize failure depending on scheduling timing.
        self.assertEqual(calls_prepare[:2], [url1, url2])
        self.assertIn(len(calls_prepare), [2, 3])
        # Finalize must include url1 (failed) and url2 (succeeded); url3 may or may not finalize.
        self.assertIn(url1, calls_finalize)
        self.assertIn(url2, calls_finalize)

        # Snapshot: url1 failed; url2 succeeded; url3 either pending (not launched/queued)
        # or succeeded (if its prepare finished before fail-fast).
        first_task, second_task, third_task = result.snapshot.tasks
        self.assertEqual(first_task.url, url1)
        self.assertEqual(first_task.state, TaskState.FAILED)
        self.assertEqual(second_task.url, url2)
        self.assertEqual(second_task.state, TaskState.SUCCEEDED)
        self.assertEqual(third_task.url, url3)
        self.assertIn(third_task.state, {TaskState.PENDING, TaskState.SUCCEEDED})

    def test_pipeline_fail_fast_on_finalize_allows_finalize_for_inflight_download(self) -> None:
        url1 = "https://artsandculture.google.com/asset/example/one"
        url2 = "https://artsandculture.google.com/asset/example/two"
        url3 = "https://artsandculture.google.com/asset/example/three"

        calls_prepare: list[str] = []
        calls_finalize: list[str] = []

        second_download_started = threading.Event()
        finalize_started_url1 = threading.Event()
        finalize_failed = threading.Event()

        prepared_by_url: dict[str, PreparedArtworkDownload] = {}

        def fake_prepare(task):  # type: ignore[no-untyped-def]
            calls_prepare.append(task.url)
            prepared = PreparedArtworkDownload(data=MagicMock(), workspace=MagicMock(), tiles={})
            if task.url == url2:
                # Start downloading url2 before url1 finalize fails, but finish after
                second_download_started.set()
                self.assertTrue(finalize_started_url1.wait(timeout=2))
                self.assertTrue(finalize_failed.wait(timeout=2))
            prepared_by_url[task.url] = prepared
            return prepared

        def fake_finalize(prepared):  # type: ignore[no-untyped-def]
            matched_url = next(url for url, candidate in prepared_by_url.items() if candidate is prepared)
            calls_finalize.append(matched_url)
            if matched_url == url1:
                finalize_started_url1.set()
                # Ensure url2 download has started before we fail
                self.assertTrue(second_download_started.wait(timeout=2))
                finalize_failed.set()
                raise DownloadError("finalize failed")
            else:
                return DownloadResult(
                    url=matched_url,
                    output_path=Path("/tmp/out.jpg"),
                    title=matched_url.rsplit("/", 1)[-1],
                    size=(10, 10),
                    tile_count=1,
                )

        with TemporaryDirectory() as tmpdir:
            manager = BatchDownloadManager(
                urls=[url1, url2, url3],
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
                pipeline_artworks=True,
            )
            with (
                patch.object(manager, "_run_download_phase_for_task", side_effect=fake_prepare),
                patch.object(manager, "_run_finalize_phase_for_prepared", side_effect=fake_finalize),
            ):
                result = manager.run()

        # url3 should never be launched
        self.assertEqual(calls_prepare, [url1, url2])
        # Finalize attempted for url1 (failed) and url2 (succeeded)
        self.assertEqual(calls_finalize, [url1, url2])

        # Snapshot: one failed (url1), one succeeded (url2), one pending (url3)
        self.assertEqual(result.snapshot.failed, 1)
        self.assertEqual(result.snapshot.succeeded, 1)
        self.assertEqual(result.snapshot.pending, 1)
        first_task, second_task, third_task = result.snapshot.tasks
        self.assertEqual(first_task.url, url1)
        self.assertEqual(first_task.state, TaskState.FAILED)
        self.assertEqual(second_task.url, url2)
        self.assertEqual(second_task.state, TaskState.SUCCEEDED)
        self.assertEqual(third_task.url, url3)
        self.assertEqual(third_task.state, TaskState.PENDING)


if __name__ == "__main__":
    unittest.main()

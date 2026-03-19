from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from typing import cast

from ..download.downloader import (
    PreparedArtworkDownload,
    finalize_artwork_download,
    prepare_artwork_download,
)
from ..errors import DownloadError
from ..models import (
    BatchRunResult,
    BatchSnapshot,
    BatchTask,
    DownloadResult,
    DownloadSize,
    OutputConflictPolicy,
    RetryConfig,
    StitchBackend,
    TaskState,
)
from ..reporting import Reporter
from .state import BatchStateStore, resolve_batch_state_path


class BatchDownloadManager:
    def __init__(
        self,
        *,
        urls: list[str],
        output_dir: Path,
        filename: str | None,
        workers: int,
        jpeg_quality: int,
        retry_config: RetryConfig,
        proxy_url: str | None = None,
        reporter: Reporter,
        fail_fast: bool,
        download_size: DownloadSize,
        max_dimension: int | None,
        output_conflict_policy: OutputConflictPolicy,
        write_metadata: bool,
        write_sidecar: bool,
        tile_only: bool = False,
        stitch_backend: StitchBackend = StitchBackend.AUTO,
        rerun_failures: int = 0,
        resume_batch: bool = False,
        pipeline_artworks: bool = False,
        batch_state_file: str | None = None,
    ) -> None:
        self.urls = urls
        self.output_dir = output_dir
        self.filename = filename
        self.workers = workers
        self.jpeg_quality = jpeg_quality
        self.retry_config = retry_config
        self.proxy_url = proxy_url
        self.reporter = reporter
        self.fail_fast = fail_fast
        self.download_size = download_size
        self.max_dimension = max_dimension
        self.output_conflict_policy = output_conflict_policy
        self.write_metadata = write_metadata
        self.write_sidecar = write_sidecar
        self.tile_only = tile_only
        self.stitch_backend = stitch_backend
        self.rerun_failures = rerun_failures
        self.resume_batch = resume_batch
        self.pipeline_artworks = pipeline_artworks
        self.state_store = BatchStateStore(resolve_batch_state_path(output_dir, batch_state_file))
        self.tasks = [
            BatchTask(index=index, url=url, state=TaskState.PENDING) for index, url in enumerate(urls, start=1)
        ]
        if self.resume_batch:
            load_result = self.state_store.load(urls=urls)
            self.tasks = load_result.tasks
            if load_result.reset_running_tasks:
                self.state_store.save(urls=self.urls, tasks=self.tasks)

    def run(self) -> BatchRunResult:
        if self.resume_batch:
            self.reporter.log(f"Resuming batch state from {self.state_store.path}")
        else:
            self.reporter.log(f"Batch state file: {self.state_store.path}")
        self.state_store.save(urls=self.urls, tasks=self.tasks)
        self.reporter.batch_started(len(self.tasks))
        self.reporter.batch_updated(self.snapshot)
        rerun_rounds_used = 0
        round_number = 0

        while True:
            round_number += 1
            rerun_candidates = [task for task in self.tasks if task.state in {TaskState.PENDING, TaskState.FAILED}]
            if not rerun_candidates:
                break

            if round_number > 1:
                rerun_rounds_used += 1
                self.reporter.log(
                    f"Rerun round {rerun_rounds_used}: retrying {len(rerun_candidates)} failed artwork(s)"
                )

            stop_batch = False
            if self.pipeline_artworks:
                stop_batch = self._run_pipeline_round(rerun_candidates)
            else:
                stop_batch = self._run_sequential_round(rerun_candidates)

            if stop_batch:
                break

            if rerun_rounds_used >= self.rerun_failures:
                break

        run_result = BatchRunResult(
            snapshot=self.snapshot,
            succeeded=[task.result for task in self.tasks if task.result is not None],
            failed=[task for task in self.tasks if task.state == TaskState.FAILED],
            rerun_rounds=rerun_rounds_used,
        )
        self.reporter.batch_finished(run_result)
        return run_result

    @property
    def snapshot(self) -> BatchSnapshot:
        return BatchSnapshot(tasks=list(self.tasks))

    def _run_sequential_round(self, rerun_candidates: list[BatchTask]) -> bool:
        for task in rerun_candidates:
            self._update_task(task.index, state=TaskState.RUNNING, error=None, attempts=task.attempts + 1)
            self.reporter.batch_updated(self.snapshot)

            try:
                from . import download_artwork

                result = download_artwork(
                    url=task.url,
                    output_dir=self.output_dir,
                    filename=self.filename,
                    workers=self.workers,
                    jpeg_quality=self.jpeg_quality,
                    retry_config=self.retry_config,
                    download_size=self.download_size,
                    max_dimension=self.max_dimension,
                    output_conflict_policy=self.output_conflict_policy,
                    write_metadata=self.write_metadata,
                    write_sidecar=self.write_sidecar,
                    tile_only=self.tile_only,
                    stitch_backend=self.stitch_backend,
                    reporter=self.reporter,
                    index=task.index,
                    total=len(self.tasks),
                    proxy_url=self.proxy_url,
                )
            except DownloadError as exc:
                failed_task = self._update_task(task.index, state=TaskState.FAILED, error=str(exc))
                self.reporter.task_failed(failed_task)
                self.reporter.batch_updated(self.snapshot)
                if self.fail_fast:
                    return True
            else:
                self._complete_task(task, result)
        return False

    def _run_pipeline_round(self, rerun_candidates: list[BatchTask]) -> bool:
        pending_tasks: deque[BatchTask] = deque(rerun_candidates)
        staged_queue: deque[tuple[BatchTask, PreparedArtworkDownload]] = deque()
        download_slot: tuple[BatchTask, Future[DownloadResult | PreparedArtworkDownload]] | None = None
        finalize_slot: tuple[BatchTask, Future[DownloadResult]] | None = None
        stop_batch = False

        with ThreadPoolExecutor(max_workers=2) as executor:
            while pending_tasks or staged_queue or download_slot is not None or finalize_slot is not None:
                if finalize_slot is None and staged_queue:
                    task, prepared = staged_queue.popleft()
                    self.reporter.log(f"Stitching started: {task.url}")
                    finalize_slot = (task, executor.submit(self._run_finalize_phase_for_prepared, prepared))

                if download_slot is None and pending_tasks and not stop_batch:
                    task = pending_tasks.popleft()
                    self._update_task(task.index, state=TaskState.RUNNING, error=None, attempts=task.attempts + 1)
                    self.reporter.log(f"Download phase started: {task.url}")
                    self.reporter.batch_updated(self.snapshot)
                    download_slot = (task, executor.submit(self._run_download_phase_for_task, task))

                active_futures: list[Future[object]] = []
                if download_slot is not None:
                    active_futures.append(cast(Future[object], download_slot[1]))
                if finalize_slot is not None:
                    active_futures.append(cast(Future[object], finalize_slot[1]))
                if not active_futures:
                    break

                done, _ = wait(active_futures, return_when=FIRST_COMPLETED)

                if download_slot is not None and download_slot[1] in done:
                    task, download_future = download_slot
                    download_slot = None
                    try:
                        download_phase_result = download_future.result()
                    except DownloadError as exc:
                        failed_task = self._update_task(task.index, state=TaskState.FAILED, error=str(exc))
                        self.reporter.task_failed(failed_task)
                        self.reporter.batch_updated(self.snapshot)
                        if self.fail_fast:
                            stop_batch = True
                    else:
                        if isinstance(download_phase_result, PreparedArtworkDownload):
                            staged_queue.append((task, download_phase_result))
                            self.reporter.log(f"Download phase complete, queued for stitching: {task.url}")
                        else:
                            assert isinstance(download_phase_result, DownloadResult)
                            self._complete_task(task, download_phase_result)

                if finalize_slot is not None and finalize_slot[1] in done:
                    task, finalize_future = finalize_slot
                    finalize_slot = None
                    try:
                        result = finalize_future.result()
                    except DownloadError as exc:
                        failed_task = self._update_task(task.index, state=TaskState.FAILED, error=str(exc))
                        self.reporter.task_failed(failed_task)
                        self.reporter.batch_updated(self.snapshot)
                        if self.fail_fast:
                            stop_batch = True
                    else:
                        self._complete_task(task, result)

                if stop_batch and download_slot is None and finalize_slot is None:
                    break

        return stop_batch

    def _run_download_phase_for_task(self, task: BatchTask) -> DownloadResult | PreparedArtworkDownload:
        return prepare_artwork_download(
            url=task.url,
            output_dir=self.output_dir,
            filename=self.filename,
            workers=self.workers,
            jpeg_quality=self.jpeg_quality,
            retry_config=self.retry_config,
            download_size=self.download_size,
            max_dimension=self.max_dimension,
            output_conflict_policy=self.output_conflict_policy,
            write_metadata=self.write_metadata,
            write_sidecar=self.write_sidecar,
            tile_only=self.tile_only,
            stitch_backend=self.stitch_backend,
            reporter=None,
            index=task.index,
            total=len(self.tasks),
            proxy_url=self.proxy_url,
        )

    def _run_finalize_phase_for_prepared(self, prepared: PreparedArtworkDownload) -> DownloadResult:
        return finalize_artwork_download(
            prepared,
            jpeg_quality=self.jpeg_quality,
            write_metadata=self.write_metadata,
            write_sidecar=self.write_sidecar,
            stitch_backend=self.stitch_backend,
            reporter=None,
        )

    def _complete_task(self, task: BatchTask, result: DownloadResult) -> None:
        state = TaskState.SKIPPED if result.skipped else TaskState.SUCCEEDED
        completed_task = self._update_task(task.index, state=state, result=result, error=None)
        if result.skipped:
            self.reporter.task_skipped(completed_task)
        else:
            self.reporter.artwork_finished(result)
        self.reporter.batch_updated(self.snapshot)

    def _update_task(
        self,
        index: int,
        *,
        state: TaskState,
        result: DownloadResult | None = None,
        error: str | None = None,
        attempts: int | None = None,
    ) -> BatchTask:
        task_index = index - 1
        updated = replace(
            self.tasks[task_index],
            state=state,
            result=result,
            error=error,
            attempts=self.tasks[task_index].attempts if attempts is None else attempts,
        )
        self.tasks[task_index] = updated
        self.state_store.save(urls=self.urls, tasks=self.tasks)
        return updated

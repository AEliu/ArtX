from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
        reporter: Reporter,
        fail_fast: bool,
        download_size: DownloadSize,
        max_dimension: int | None,
        output_conflict_policy: OutputConflictPolicy,
        write_metadata: bool,
        write_sidecar: bool,
        stitch_backend: StitchBackend = StitchBackend.AUTO,
        rerun_failures: int = 0,
        resume_batch: bool = False,
        batch_state_file: str | None = None,
    ) -> None:
        self.urls = urls
        self.output_dir = output_dir
        self.filename = filename
        self.workers = workers
        self.jpeg_quality = jpeg_quality
        self.retry_config = retry_config
        self.reporter = reporter
        self.fail_fast = fail_fast
        self.download_size = download_size
        self.max_dimension = max_dimension
        self.output_conflict_policy = output_conflict_policy
        self.write_metadata = write_metadata
        self.write_sidecar = write_sidecar
        self.stitch_backend = stitch_backend
        self.rerun_failures = rerun_failures
        self.resume_batch = resume_batch
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
                        stitch_backend=self.stitch_backend,
                        reporter=self.reporter,
                        index=task.index,
                        total=len(self.tasks),
                    )
                except DownloadError as exc:
                    failed_task = self._update_task(task.index, state=TaskState.FAILED, error=str(exc))
                    self.reporter.task_failed(failed_task)
                    self.reporter.batch_updated(self.snapshot)
                    if self.fail_fast:
                        stop_batch = True
                        break
                else:
                    state = TaskState.SKIPPED if result.skipped else TaskState.SUCCEEDED
                    completed_task = self._update_task(task.index, state=state, result=result, error=None)
                    if result.skipped:
                        self.reporter.task_skipped(completed_task)
                    else:
                        self.reporter.artwork_finished(result)
                    self.reporter.batch_updated(self.snapshot)

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

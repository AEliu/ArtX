from __future__ import annotations

from ..models import ArtworkContext, BatchRunResult, BatchSnapshot, BatchTask, DownloadResult


class Reporter:
    def log(self, message: str) -> None:
        pass

    def batch_started(self, total: int) -> None:
        pass

    def batch_updated(self, snapshot: BatchSnapshot) -> None:
        pass

    def artwork_started(self, context: ArtworkContext) -> None:
        pass

    def phase_changed(self, phase: str) -> None:
        pass

    def tile_advanced(self, completed: int, total: int) -> None:
        pass

    def retry_recorded(self, description: str, url: str, attempt: int, reason: str) -> None:
        pass

    def stitching_started(self) -> None:
        pass

    def artwork_finished(self, result: DownloadResult) -> None:
        pass

    def task_skipped(self, task: BatchTask) -> None:
        pass

    def task_failed(self, task: BatchTask) -> None:
        pass

    def batch_finished(self, run_result: BatchRunResult) -> None:
        pass

    def close(self) -> None:
        pass

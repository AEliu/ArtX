from __future__ import annotations

from threading import Lock
from time import monotonic

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn

from ..models import ArtworkContext, BatchRunResult, BatchSnapshot, BatchTask, DownloadResult
from .base import Reporter
from .telemetry import ArtworkProgressTelemetry, _format_eta, _format_finish_time


class RichCliReporter(Reporter):
    def __init__(self) -> None:
        self.console = Console(stderr=True)
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        )
        self.overall_task_id: TaskID | None = None
        self.tile_task_id: TaskID | None = None
        self.current_tile_total = 0
        self.stitching_in_progress = False
        self.last_snapshot: BatchSnapshot | None = None
        self.current_task_label = "Artwork"
        self.telemetry = ArtworkProgressTelemetry()
        self._lock = Lock()

    def log(self, message: str) -> None:
        self.console.print(f"[cyan]•[/cyan] {message}")

    def batch_started(self, total: int) -> None:
        self.progress.start()
        self.overall_task_id = self.progress.add_task("Total artworks", total=total)

    def batch_updated(self, snapshot: BatchSnapshot) -> None:
        self.last_snapshot = snapshot
        if self.overall_task_id is not None:
            self.progress.update(
                self.overall_task_id,
                completed=snapshot.succeeded + snapshot.failed + snapshot.skipped,
                total=snapshot.total,
            )

    def artwork_started(self, context: ArtworkContext) -> None:
        description = f"[{context.index}/{context.total}] {context.page.title[:60]}"
        total_tiles = context.selected_level.tile_count
        self.current_task_label = description
        self.current_tile_total = total_tiles
        self.stitching_in_progress = False
        with self._lock:
            self.telemetry.reset(total_tiles, preserve_retries=True)
        self.tile_task_id = self.progress.add_task(description, total=total_tiles)
        self.log(f"Output: {context.output_path}")
        self.log(
            f"Image: {context.tile_info.image_width_for(context.selected_level)}x"
            f"{context.tile_info.image_height_for(context.selected_level)}, "
            f"tiles: {context.selected_level.num_tiles_x}x{context.selected_level.num_tiles_y}"
        )

    def phase_changed(self, phase: str) -> None:
        with self._lock:
            if phase == "fetching":
                self.telemetry.retries = 0
                self.telemetry.completed_tiles = 0
                self.telemetry.total_tiles = 0
                self.telemetry.tile_timestamps.clear()
                self.telemetry.started_at = monotonic()
            self.telemetry.mark_phase(phase)

    def tile_advanced(self, completed: int, total: int) -> None:
        if self.tile_task_id is not None:
            with self._lock:
                self.telemetry.record_tile_progress(completed)
                rate = self.telemetry.tile_rate()
                eta = self.telemetry.eta_seconds()
                retries = self.telemetry.retries
            description = (
                f"{self.current_task_label} | {completed}/{total} tiles | "
                f"{rate:.1f} tiles/s | ETA {_format_eta(eta)} | Finish ~ {_format_finish_time(eta)} | retries {retries}"
            )
            self.progress.update(self.tile_task_id, completed=completed, total=total, description=description)

    def retry_recorded(self, description: str, url: str, attempt: int, reason: str) -> None:
        with self._lock:
            self.telemetry.record_retry()

    def stitching_started(self) -> None:
        if self.tile_task_id is not None:
            self.stitching_in_progress = True
            with self._lock:
                self.telemetry.mark_phase("stitching")
            self.progress.update(self.tile_task_id, description="Stitching image", completed=0, total=1)

    def artwork_finished(self, result: DownloadResult) -> None:
        if self.tile_task_id is not None:
            if self.stitching_in_progress:
                self.progress.update(self.tile_task_id, completed=1, total=1)
            else:
                self.progress.update(self.tile_task_id, completed=self.current_tile_total)
        self.log(f"Saved: {result.output_path}")
        if result.sidecar_path is not None:
            self.log(f"Sidecar: {result.sidecar_path}")

    def task_skipped(self, task: BatchTask) -> None:
        result = task.result
        if result is not None:
            self.log(f"Skipped existing: {result.output_path}")
            if result.sidecar_path is not None:
                self.log(f"Existing sidecar: {result.sidecar_path}")

    def task_failed(self, task: BatchTask) -> None:
        if self.tile_task_id is not None and self.stitching_in_progress:
            self.progress.update(self.tile_task_id, description="Stitching failed", completed=0, total=1)
        self.log(f"Failed: {task.url} | {task.error}")

    def batch_finished(self, run_result: BatchRunResult) -> None:
        self.progress.stop()
        snapshot = run_result.snapshot
        style = "bold green" if snapshot.failed == 0 else "bold yellow"
        self.console.print(
            f"[{style}]Completed {snapshot.succeeded} succeeded, {snapshot.skipped} skipped, "
            f"{snapshot.failed} failed, {snapshot.pending} pending.[/{style}]"
        )
        if run_result.rerun_rounds:
            self.log(f"Rerun rounds used: {run_result.rerun_rounds}")

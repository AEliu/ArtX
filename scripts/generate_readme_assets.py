from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from rich.console import Console

from googleart_download.reporting import RichTuiReporter

ASSETS_DIR = Path("docs/assets")


def export_svg(output_path: Path, renderable: object, *, width: int = 160) -> None:
    console = Console(record=True, width=width, file=StringIO())
    console.print(renderable)
    output_path.write_text(console.export_svg(title="googleart-download"), encoding="utf-8")


def export_reporter_svg(output_path: Path, configure: Callable[[RichTuiReporter], None]) -> None:
    stderr_buffer = StringIO()
    with redirect_stderr(stderr_buffer):
        reporter = RichTuiReporter()
        try:
            configure(reporter)
            reporter.live.stop()
            export_svg(output_path, reporter.render(), width=160)
        finally:
            reporter.close()


def build_tui_preview(reporter: RichTuiReporter) -> None:
    reporter.batch_started(1)
    reporter.current_status = "Completed"
    reporter.current_title = "Girl with a Pearl Earring - Johannes Vermeer"
    reporter.current_output = "downloads/Girl with a Pearl Earring - Johannes Vermeer.medium.jpg"
    reporter.current_size = "5571x4411"
    reporter.current_tiles = "96/96 (96 total)"
    reporter.current_phase = "done"
    reporter.current_rate = "6.2 tiles/s"
    reporter.current_eta = "00:00"
    reporter.current_finish_time = "14:37"
    reporter.current_retries = 1
    reporter.completed_artworks = 1
    reporter.pending_artworks = 0
    reporter.progress.update(reporter.total_task_id, total=1, completed=1)
    reporter.progress.update(reporter.tile_task_id, description="Stitching", total=1, completed=1)
    reporter.log_line("Saved: downloads/Girl with a Pearl Earring - Johannes Vermeer.medium.jpg")
    reporter.log_line("Stitch backend: pillow")
    reporter.log_line("Output format: JPG")


def build_large_image_preview(reporter: RichTuiReporter) -> None:
    reporter.batch_started(1)
    reporter.current_status = "Completed"
    reporter.current_title = "The Starry Night - Vincent van Gogh"
    reporter.current_output = "downloads/The Starry Night - Vincent van Gogh.tif"
    reporter.current_size = "44567x35291"
    reporter.current_tiles = "6072/6072 (6072 total)"
    reporter.current_phase = "done"
    reporter.current_retries = 2
    reporter.completed_artworks = 1
    reporter.pending_artworks = 0
    reporter.progress.update(reporter.total_task_id, total=1, completed=1)
    reporter.progress.update(reporter.tile_task_id, description="Stitching", total=1, completed=1)
    reporter.log_line("Saved: downloads/The Starry Night - Vincent van Gogh.tif")
    reporter.log_line("Stitch backend: bigtiff")
    reporter.log_line("Output format: TIFF")


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    export_reporter_svg(ASSETS_DIR / "tui-preview.svg", build_tui_preview)
    export_reporter_svg(ASSETS_DIR / "large-image-tiff.svg", build_large_image_preview)
    export_reporter_svg(ASSETS_DIR / "tui-overview.svg", build_tui_preview)
    export_reporter_svg(ASSETS_DIR / "large-image-overview.svg", build_large_image_preview)


if __name__ == "__main__":
    main()

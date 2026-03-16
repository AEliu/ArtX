from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from googleart_download.models import (
    ArtworkContext,
    ArtworkMetadata,
    BatchTask,
    DownloadResult,
    PageInfo,
    PyramidLevel,
    TaskState,
    TileInfo,
)
from googleart_download.reporters import RichCliReporter, RichTuiReporter


class ReporterTests(unittest.TestCase):
    def make_context(self) -> ArtworkContext:
        level = PyramidLevel(z=4, num_tiles_x=3, num_tiles_y=2, empty_pels_x=0, empty_pels_y=0)
        tile_info = TileInfo(tile_width=256, tile_height=256, levels=[level])
        return ArtworkContext(
            index=1,
            total=1,
            url="https://example.com/art",
            page=PageInfo(title="Artwork", base_url="https://example.com/base", token="", metadata=ArtworkMetadata()),
            tile_info=tile_info,
            selected_level=level,
            output_path=Path("/tmp/art.jpg"),
        )

    def test_cli_reporter_uses_separate_stitching_stage_progress(self) -> None:
        reporter = RichCliReporter()
        reporter.batch_started(1)
        reporter.artwork_started(self.make_context())
        assert reporter.tile_task_id is not None

        reporter.tile_advanced(6, 6)
        reporter.stitching_started()
        task = reporter.progress.tasks[reporter.tile_task_id]
        self.assertEqual(task.description, "Stitching image")
        self.assertEqual(task.completed, 0)
        self.assertEqual(task.total, 1)

        reporter.artwork_finished(
            DownloadResult(
                url="https://example.com/art",
                output_path=Path("/tmp/art.jpg"),
                title="Artwork",
                size=(768, 512),
                tile_count=6,
            )
        )
        task = reporter.progress.tasks[reporter.tile_task_id]
        self.assertEqual(task.completed, 1)
        self.assertEqual(task.total, 1)

    def test_cli_reporter_marks_failed_stitching_without_100_percent(self) -> None:
        reporter = RichCliReporter()
        reporter.batch_started(1)
        reporter.artwork_started(self.make_context())
        assert reporter.tile_task_id is not None

        reporter.tile_advanced(6, 6)
        reporter.stitching_started()
        reporter.task_failed(BatchTask(index=1, url="https://example.com/art", state=TaskState.FAILED, error="boom"))

        task = reporter.progress.tasks[reporter.tile_task_id]
        self.assertEqual(task.description, "Stitching failed")
        self.assertEqual(task.completed, 0)
        self.assertEqual(task.total, 1)

    def test_cli_reporter_includes_rate_eta_and_retries_during_download(self) -> None:
        reporter = RichCliReporter()
        reporter.batch_started(1)
        with patch("googleart_download.reporters.monotonic", side_effect=[0.0, 1.0, 2.0, 2.0]), patch(
            "googleart_download.reporters.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = __import__("datetime").datetime(2026, 3, 16, 14, 30, 0)
            reporter.artwork_started(self.make_context())
            reporter.retry_recorded("tile x=0 y=0", "https://example.com/tile", 2, "timeout")
            reporter.tile_advanced(3, 6)

        assert reporter.tile_task_id is not None
        task = reporter.progress.tasks[reporter.tile_task_id]
        self.assertIn("3/6 tiles", task.description)
        self.assertIn("tiles/s", task.description)
        self.assertIn("ETA", task.description)
        self.assertIn("Finish ~", task.description)
        self.assertIn("retries 1", task.description)

    def test_tui_reporter_skipped_task_updates_current_artwork_fields(self) -> None:
        reporter = RichTuiReporter()
        try:
            reporter.task_skipped(
                BatchTask(
                    index=1,
                    url="https://example.com/art",
                    state=TaskState.SKIPPED,
                    result=DownloadResult(
                        url="https://example.com/art",
                        output_path=Path("downloads/art.jpg"),
                        title="Artwork",
                        size=None,
                        tile_count=None,
                        skipped=True,
                    ),
                )
            )
            self.assertEqual(reporter.current_title, "Artwork")
            self.assertEqual(reporter.current_output, "downloads/art.jpg")
            self.assertEqual(reporter.current_phase, "skipped")
        finally:
            reporter.close()


if __name__ == "__main__":
    unittest.main()

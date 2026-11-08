"""One progress display can track several concurrent artworks."""

from contextlib import contextmanager
from typing import Callable, Iterator

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


class DownloadProgress:
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._active = 0
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            transient=True,
        )

    @contextmanager
    def track(self, name: str, total: int) -> Iterator[Callable[[], None]]:
        if not self._enabled:
            yield lambda: None
            return
        if self._active == 0:
            self._progress.start()
        self._active += 1
        task = self._progress.add_task(name, total=total)
        try:
            yield lambda: self._progress.advance(task)
        finally:
            self._progress.remove_task(task)
            self._active -= 1
            if self._active == 0:
                self._progress.stop()

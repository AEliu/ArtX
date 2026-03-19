from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import monotonic


@dataclass
class ArtworkProgressTelemetry:
    phase: str = "idle"
    retries: int = 0
    total_tiles: int = 0
    completed_tiles: int = 0
    started_at: float = 0.0
    tile_timestamps: deque[float] = field(default_factory=deque)

    def reset(self, total_tiles: int, *, preserve_retries: bool = False) -> None:
        retries = self.retries if preserve_retries else 0
        self.phase = "downloading"
        self.retries = retries
        self.total_tiles = total_tiles
        self.completed_tiles = 0
        self.started_at = monotonic()
        self.tile_timestamps.clear()

    def mark_phase(self, phase: str) -> None:
        self.phase = phase

    def record_tile_progress(self, completed: int) -> None:
        now = monotonic()
        delta = max(0, completed - self.completed_tiles)
        for _ in range(delta):
            self.tile_timestamps.append(now)
        self.completed_tiles = completed
        self._trim(now)

    def record_retry(self) -> None:
        self.retries += 1

    def tile_rate(self) -> float:
        if self.phase != "downloading":
            return 0.0
        now = monotonic()
        self._trim(now)
        if len(self.tile_timestamps) >= 2:
            window_span = self.tile_timestamps[-1] - self.tile_timestamps[0]
            if window_span > 0:
                return (len(self.tile_timestamps) - 1) / window_span
        elapsed = max(0.0, now - self.started_at)
        if elapsed > 0 and self.completed_tiles > 0:
            return self.completed_tiles / elapsed
        return 0.0

    def eta_seconds(self) -> float | None:
        rate = self.tile_rate()
        remaining = max(0, self.total_tiles - self.completed_tiles)
        if rate <= 0 or remaining <= 0:
            return None
        return remaining / rate

    def _trim(self, now: float) -> None:
        while self.tile_timestamps and now - self.tile_timestamps[0] > 30:
            self.tile_timestamps.popleft()


def _format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _format_finish_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    finish_at = datetime.now() + timedelta(seconds=max(0, seconds))
    return finish_at.strftime("%H:%M")

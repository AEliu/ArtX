from .base import Reporter
from .cli import RichCliReporter
from .telemetry import ArtworkProgressTelemetry
from .tui import RichTuiReporter


def build_reporter(use_tui: bool) -> Reporter:
    return RichTuiReporter() if use_tui else RichCliReporter()


__all__ = [
    "ArtworkProgressTelemetry",
    "Reporter",
    "RichCliReporter",
    "RichTuiReporter",
    "build_reporter",
]

from __future__ import annotations

import warnings as _warnings

from artx.reporting.telemetry import *  # noqa: F401,F403

_warnings.warn(
    "'googleart_download.reporting.telemetry' is deprecated; use 'artx.reporting.telemetry'",
    DeprecationWarning,
    stacklevel=2,
)

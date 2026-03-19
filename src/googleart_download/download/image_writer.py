from __future__ import annotations

import warnings as _warnings

from artx.download.image_writer import *  # noqa: F401,F403

_warnings.warn(
    "'googleart_download.download.image_writer' is deprecated; use 'artx.download.image_writer'",
    DeprecationWarning,
    stacklevel=2,
)

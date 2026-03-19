from __future__ import annotations

import warnings as _warnings

from artx.download.downloader import *  # noqa: F401,F403

_warnings.warn(
    "'googleart_download.download.downloader' is deprecated; use 'artx.download.downloader'",
    DeprecationWarning,
    stacklevel=2,
)

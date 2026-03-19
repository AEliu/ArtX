from __future__ import annotations

import warnings as _warnings

from artx.download.http_client import *  # noqa: F401,F403

_warnings.warn(
    "'googleart_download.download.http_client' is deprecated; use 'artx.download.http_client'",
    DeprecationWarning,
    stacklevel=2,
)

from __future__ import annotations

import warnings as _warnings

from artx.download.transport import *  # noqa: F401,F403

_warnings.warn(
    "'googleart_download.download.transport' is deprecated; use 'artx.download.transport'",
    DeprecationWarning,
    stacklevel=2,
)

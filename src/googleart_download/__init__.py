from __future__ import annotations

import warnings as _warnings

from artx import *  # noqa: F401,F403

_warnings.warn(
    "Package 'googleart_download' is deprecated; use 'artx' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export public API from artx

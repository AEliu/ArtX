"""Bridge blocking image operations without closing resources under a worker."""

from __future__ import annotations

import asyncio
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_blocking(operation: Callable[..., T], *args: object) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Python cannot stop a running thread. Even repeated cancellation must
        # wait for it before the caller's finally block closes its resources.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()  # Retrieve a worker failure while preserving cancellation.
        raise

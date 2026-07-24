"""Folder-level workspace lock (决策④: 同 folder 跨会话并发写 → 串行排队).

A workspace (a folder's shared space, or an ungrouped conversation's own space)
admits **one task at a time**; concurrent tasks on the *same* workspace queue.
Intra-task parallelism (a delegated worker team) is collaboration and is *not*
limited here — the lock is taken once per task at the caller, not per worker.

Why it matters: same-folder turns write the same files and the snapshot manifest
read-modify-write (storage/_archive.py) is only safe under this lock. Reads are
intentionally not locked.

The lock registry is keyed by the running event loop (via a ``WeakKeyDictionary``)
so a lock is never reused across loops — robust under pytest's per-test loops,
while production (one loop) keeps exactly one registry. Multi-process scaling
swaps this for a Redis lock behind the same ``workspace_lock`` seam.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# loop -> {storage_key: Lock}. WeakKeyDictionary so a finished loop's locks are
# garbage-collected with it (no stale-loop reuse, no id() collisions).
_registries: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _get_lock(key: str) -> asyncio.Lock:
    """Return the process-wide lock for ``key`` on the current loop (create once).

    Synchronous and free of ``await``, so the get-or-create is atomic within the
    single-threaded event loop — no guard lock needed.
    """
    loop = asyncio.get_running_loop()
    registry = _registries.get(loop)
    if registry is None:
        registry = {}
        _registries[loop] = registry
    lock = registry.get(key)
    if lock is None:
        lock = asyncio.Lock()
        registry[key] = lock
    return lock


@asynccontextmanager
async def workspace_lock(key: str) -> AsyncIterator[None]:
    """Hold the workspace's folder-level lock for the duration of the block.

    ``key`` is the workspace storage key (``workspace.locate.workspace_storage_key``)
    so all of a folder's conversations serialize on one lock.
    """
    lock = _get_lock(key)
    async with lock:
        yield

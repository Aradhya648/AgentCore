"""Per-user long-term memory lock (offline consolidation serialization).

A user's memory file is a single markdown document mutated read-modify-write by the
consolidation pass. Two consolidations for the *same user* (e.g. a debounce firing
while the periodic sweeper also picks the user up, or two of the user's
conversations settling at once) must not interleave or one would clobber the
other's write. This lock serializes them per user; different users never contend.

Mirrors workspace/locks.py: the registry is keyed by the running event loop (via a
``WeakKeyDictionary``) so locks are never reused across loops — robust under
pytest's per-test loops, one registry in production. Multi-process scaling swaps
this for a Redis lock behind the same ``user_memory_lock`` seam.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# loop -> {user_id: Lock}. WeakKeyDictionary so a finished loop's locks are
# garbage-collected with it (no stale-loop reuse, no id() collisions).
_registries: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _get_lock(user_id: str) -> asyncio.Lock:
    """Return the process-wide lock for ``user_id`` on the current loop (create once).

    Synchronous and free of ``await``, so the get-or-create is atomic within the
    single-threaded event loop — no guard lock needed.
    """
    loop = asyncio.get_running_loop()
    registry = _registries.get(loop)
    if registry is None:
        registry = {}
        _registries[loop] = registry
    lock = registry.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        registry[user_id] = lock
    return lock


@asynccontextmanager
async def user_memory_lock(user_id: str) -> AsyncIterator[None]:
    """Hold the user's memory lock for the duration of the block."""
    lock = _get_lock(user_id)
    async with lock:
        yield

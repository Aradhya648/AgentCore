"""Per-conversation ``code_execute`` serial lock.

Same-session workers (delegate fan-out) share one sandbox working tree; concurrent
``code_execute`` calls on that conversation queue so copy-in/out and cwd mutation
do not interleave. ``test_run`` / ``terminal`` deliberately bypass this lock —
they keep their own budgets and must not be stalled behind short scripts.

Keyed by ``ToolContext.conversation_id``. Empty / missing id → no lock (tests /
evals stay unserialized). Registry mirrors ``workspace.locks``: loop →
``WeakKeyDictionary`` → ``dict[str, Lock]``.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# loop -> {conversation_id: Lock}. WeakKeyDictionary so a finished loop's locks
# are garbage-collected with it (no stale-loop reuse, no id() collisions).
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
async def code_execute_lock(conversation_id: str | None) -> AsyncIterator[None]:
    """Hold the conversation's ``code_execute`` lock for the duration of the block.

    Empty / whitespace-only / ``None`` → yield without locking (unscoped call sites).
    """
    key = (conversation_id or "").strip()
    if not key:
        yield
        return
    lock = _get_lock(key)
    async with lock:
        yield

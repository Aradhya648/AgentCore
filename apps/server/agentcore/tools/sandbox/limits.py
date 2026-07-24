"""Global execution-slot limiter for cloud sandbox runs — 灰度护栏.

One asyncio semaphore per API process caps how many gVisor executions run at
once (production is a single uvicorn process, so this is effectively the host
cap; sized for the 2C8G box). Rejection semantics: a caller waits a **bounded**
grace period for a slot (``gvisor_slot_wait_seconds``), then fails fast with an
explainable busy result — pure fast-fail would flake under mild contention,
an unbounded queue would pile waiters past the engine's tool deadline.

The semaphore is (re)created lazily so tests with fresh event loops / patched
settings never trip "bound to a different event loop"; capacity changes take
effect on the next acquire (dev-only concern — production settings are static).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from agentcore.config import settings

_limiter: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore, int] | None = None


def reset_execution_slots() -> None:
    """Drop the process-level limiter (test isolation)."""
    global _limiter
    _limiter = None


def _current_semaphore() -> asyncio.Semaphore:
    global _limiter
    loop = asyncio.get_running_loop()
    capacity = max(1, int(settings.gvisor_max_concurrent_executions))
    if _limiter is None or _limiter[0] is not loop or _limiter[2] != capacity:
        _limiter = (loop, asyncio.Semaphore(capacity), capacity)
    return _limiter[1]


async def try_acquire_execution_slot(
    *, wait_seconds: float | None = None
) -> Callable[[], None] | None:
    """Acquire a global execution slot, waiting at most the configured grace.

    Returns a release callable, or ``None`` when no slot freed up in time (the
    caller should fail fast with a busy result). The release callable is
    idempotent-unsafe by design — call it exactly once, in a ``finally``.
    """
    sem = _current_semaphore()
    timeout = (
        float(settings.gvisor_slot_wait_seconds) if wait_seconds is None else wait_seconds
    )
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
    except TimeoutError:
        return None
    return sem.release

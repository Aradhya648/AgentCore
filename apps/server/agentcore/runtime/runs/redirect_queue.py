"""Turn-scoped queue for user-initiated worker redirects (跑一半改方向).

While ``delegate`` is driving, the CEO coroutine is blocked — user mid-flight steer
must arrive on a separate channel. This module holds pending ``(execution_id, run_id,
feedback)`` requests until the WaveScheduler / drive loop drains them.

Drive semantics (热优先 · 冷诚实回落):
- cancel the target worker (``task.cancel("redirect")``) + salvage partial transcript
- if salvage clears the hot gate → ``continue_run`` on the same author (revision chain)
- else → cold ``{run_id}_redir`` with ``replaces_run_id`` + ``steer`` (接手, not parallel)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunRedirectRequest:
    execution_id: str
    run_id: str
    feedback: str
    conversation_id: str


_pending: dict[str, list[RunRedirectRequest]] = {}


def enqueue_redirect(
    *,
    execution_id: str,
    run_id: str,
    feedback: str,
    conversation_id: str,
) -> RunRedirectRequest:
    """Queue a user redirect for the given batch execution. Returns the enqueued item."""
    item = RunRedirectRequest(
        execution_id=execution_id.strip(),
        run_id=run_id.strip(),
        feedback=feedback.strip(),
        conversation_id=conversation_id.strip(),
    )
    bucket = _pending.setdefault(item.execution_id, [])
    bucket.append(item)
    return item


def take_redirects(execution_id: str) -> list[RunRedirectRequest]:
    """Drain and return all pending redirects for ``execution_id`` (FIFO)."""
    return _pending.pop(execution_id.strip(), [])


def peek_redirect_count(execution_id: str) -> int:
    """How many redirects are queued for ``execution_id`` (does not drain)."""
    return len(_pending.get(execution_id.strip(), []))

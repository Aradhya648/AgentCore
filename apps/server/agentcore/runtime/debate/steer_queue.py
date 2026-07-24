"""Turn-scoped queue for ambient debate steering (老板随时插手).

While ``debate`` drives, the Moderator coroutine runs continuously — user mid-flight
steer must arrive on a separate channel (same pattern as
:mod:`agentcore.runtime.runs.redirect_queue`). This module holds pending structured
``(execution_id, decision, focus, ask, ask_target)`` requests until the Moderator
drains them at the **next round boundary** (non-blocking).

Drain semantics:
- empty → ``None`` (judge auto-convergence continues)
- any ``conclude`` → ``CONCLUDE`` (last ask kept for unanswered record)
- else → ``CONTINUE`` (last non-empty focus; last ask + target)
- never blocks; conclude applies at the next boundary (current round finishes first)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DebateSteerDecision = Literal["continue", "conclude"]


@dataclass(frozen=True, slots=True)
class DebateSteerRequest:
    execution_id: str
    conversation_id: str
    decision: DebateSteerDecision
    focus: str = ""
    ask: str = ""
    ask_target: str = ""


_pending: dict[str, list[DebateSteerRequest]] = {}


def enqueue_steer(
    *,
    execution_id: str,
    conversation_id: str,
    decision: DebateSteerDecision,
    focus: str = "",
    ask: str = "",
    ask_target: str = "",
) -> DebateSteerRequest:
    """Queue an ambient steer for the given debate execution. Returns the enqueued item."""
    item = DebateSteerRequest(
        execution_id=execution_id.strip(),
        conversation_id=conversation_id.strip(),
        decision=decision,
        focus=focus.strip(),
        ask=ask.strip(),
        ask_target=ask_target.strip(),
    )
    bucket = _pending.setdefault(item.execution_id, [])
    bucket.append(item)
    return item


def take_steers(execution_id: str) -> list[DebateSteerRequest]:
    """Drain and return all pending steers for ``execution_id`` (FIFO). Never blocks."""
    return _pending.pop(execution_id.strip(), [])


def peek_steer_count(execution_id: str) -> int:
    """How many steers are queued for ``execution_id`` (does not drain)."""
    return len(_pending.get(execution_id.strip(), []))


def fold_steers(steers: list[DebateSteerRequest]):
    """Fold drained steers into one :class:`~agentcore.runtime.debate.types.RoundBoundary` or None.

    Last-wins for focus / ask; any ``conclude`` wins the decision (凌驾裁判收场).
    """
    from agentcore.runtime.debate.types import RoundBoundary, RoundDecision

    if not steers:
        return None
    focus = ""
    ask = ""
    ask_target = ""
    conclude = False
    for s in steers:
        if s.focus:
            focus = s.focus
        if s.ask:
            ask = s.ask
            ask_target = s.ask_target
        if s.decision == "conclude":
            conclude = True
    if conclude:
        return RoundBoundary(
            decision=RoundDecision.CONCLUDE, ask=ask, ask_target=ask_target
        )
    return RoundBoundary(
        decision=RoundDecision.CONTINUE,
        focus=focus,
        ask=ask,
        ask_target=ask_target,
    )

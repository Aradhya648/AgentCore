"""Coordination-session terminal event helpers for the drive loop."""

from __future__ import annotations

from typing import Any

from agentcore.core.logging import get_logger

logger = get_logger(__name__)


def post_session_all_completed(
    session: Any,
    *,
    output: str,
    completed: int | None = None,
    total: int | None = None,
    output_limit: int = 4000,
) -> None:
    """Post the coordination terminal event (happy path + criteria-gap / partial-fail)."""
    from agentcore.runtime.coordination.session import (
        CoordinationEvent,
        CoordinationEventKind,
    )

    completed_n = (
        completed if completed is not None else len(session.completed_run_ids)
    )
    total_n = total if total is not None else session.total_workers
    session.post(
        CoordinationEvent(
            kind=CoordinationEventKind.ALL_COMPLETED,
            payload={
                "completed": completed_n,
                "total": total_n,
                "output": output[:output_limit],
            },
        )
    )
    # Drive 终态 ≡ wait 可唤醒：终态投递必须可观测（与 wait_end / coord_inject 对照）。
    logger.info(
        "coordination.terminal_posted",
        execution_id=getattr(session, "execution_id", "") or "",
        completed=completed_n,
        total=total_n,
        output_chars=min(len(output), output_limit),
    )

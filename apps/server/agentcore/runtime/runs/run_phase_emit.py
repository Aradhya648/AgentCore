"""Emit worker mid-flight ``run_phase`` SSE (thinking / tool / waiting_children / winding_down).

Call sites own *when*; this module only shapes the event. ``queued`` / ``skipped`` are
lifecycle ``RunStatus`` (pending / skipped) — not emitted here.
"""

from __future__ import annotations

from typing import Any


def emit_run_phase(
    sink: Any,
    run_id: str,
    agent_id: str,
    phase: str,
    *,
    tool_name: str | None = None,
) -> None:
    """No-op when ``sink`` / ``run_id`` missing (CEO / tests / unscoped)."""
    if sink is None or not run_id:
        return
    from agentcore.runtime.events import run_phase

    sink.emit(
        run_phase(
            run_id,
            agent_id or run_id,
            phase,
            tool_name=tool_name,
        )
    )

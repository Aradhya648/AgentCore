"""Team kickoff gate — thin re-exports of the orchestration-layer kickoff module.

Historical import path for delegate tests / patches. Prefer
``agentcore.runtime.kickoff`` for new call sites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.kickoff import (
    await_kickoff,
    delegate_kickoff_summary,
    kickoff_tools,
    needs_capability_auth,
    should_preview_delegate_plan,
    skip_after_confirmed_ask,
)
from agentcore.runtime.kickoff import (
    should_kickoff as _should_kickoff_core,
)
from agentcore.runtime.kickoff.summary import worker_rows

if TYPE_CHECKING:
    from agentcore.core.types import PermissionAxes
    from agentcore.runtime.runs.plan import RunPlan

DelegateTool = Any

# Back-compat aliases.
should_preview_plan = should_preview_delegate_plan
should_preview = should_preview_delegate_plan


def should_kickoff(
    plan: RunPlan,
    *,
    finalize: bool,
    local_gate: bool,
    axes: PermissionAxes,
) -> bool:
    """Delegate-shaped wrapper: plan_preview from :func:`should_preview_delegate_plan`."""
    return _should_kickoff_core(
        plan_preview=should_preview_delegate_plan(plan, finalize=finalize),
        local_gate=local_gate,
        axes=axes,
    )


async def persist_team_preview(
    tool: DelegateTool,
    checkpoint_id: str,
    plan: RunPlan,
    workers: list[dict[str, Any]],
    required_event: Any,
    *,
    tools: list[str] | None = None,
) -> bool:
    """Back-compat: build a delegate KickoffSummary and persist via shared path."""
    from agentcore.runtime.kickoff.pause import persist_kickoff
    from agentcore.runtime.kickoff.summary import KickoffSummary

    summary = KickoffSummary(
        primitive="delegate",
        workers=list(workers),
        tools=list(tools or []),
    )
    return await persist_kickoff(tool, checkpoint_id, summary, required_event, plan=plan)


async def await_team_preview(
    tool: DelegateTool,
    plan: RunPlan,
    *,
    show_capabilities: bool = True,
) -> CheckpointDecision | None:
    """Pause before the first wave; return the decision, or None if suspended."""
    tools = kickoff_tools(show_capabilities=show_capabilities)
    summary = delegate_kickoff_summary(plan, tools=tools)
    return await await_kickoff(tool, summary, plan=plan)


__all__ = [
    "await_team_preview",
    "kickoff_tools",
    "needs_capability_auth",
    "persist_team_preview",
    "should_kickoff",
    "should_preview",
    "should_preview_plan",
    "skip_after_confirmed_ask",
    "worker_rows",
]

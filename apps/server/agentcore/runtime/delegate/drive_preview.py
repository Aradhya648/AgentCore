"""Team preview gate that runs before workers / coordination fork."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.tools.protocol import ToolResult

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan

type DelegateTool = Any

logger = get_logger(__name__)


async def team_preview_before_workers(
    tool: DelegateTool,
    plan: RunPlan,
    *,
    finalize: bool,
    complexity_hint: str,
    seed_completed: dict[str, Any] | None,
    call_idx: int,
) -> ToolResult | None:
    """Hang for the kickoff card (计划+能力) before any worker / coordinate fork.

    Returns an early ToolResult (SUSPEND / stop) or None to proceed. Under
    AutonomyPolicy.full_auto, skips the card entirely and silently marks a
    delegation grant for later application.
    """
    playbook_name = str(getattr(tool, "_active_playbook", None) or "").strip()
    # light 通常跳过开工卡；organize_folder 例外——落盘工具依赖 kickoff grant，
    # 跳过会导致 GRANTABLE（mkdir 等）静默挂在 ApprovalGate。
    skip_for_light = complexity_hint == "light" and playbook_name != "organize_folder"
    if seed_completed is not None or skip_for_light or tool._depth != 0:
        return None
    from agentcore.core.types import DEFAULT_PERMISSION_AXES
    from agentcore.runtime.delegate.preview import (
        await_team_preview,
        needs_capability_auth,
        should_kickoff,
        should_preview_plan,
        skip_after_confirmed_ask,
    )
    from agentcore.runtime.sandbox_approval import worker_gate_applies

    axes = getattr(tool, "_permission_axes", None) or DEFAULT_PERMISSION_AXES
    local_gate = worker_gate_applies(tool._base_tool_context.backend)
    plan_preview = should_preview_plan(plan, finalize=finalize)
    if not should_kickoff(
        plan, finalize=finalize, local_gate=local_gate, axes=axes
    ):
        # Card skipped: still silent-grant when command=auto, OR when team_kickoff=skip
        # with command=kickoff (少打断 — 跳组团卡但仍开工授执行类).
        if (
            local_gate
            and tool._approval_gate is not None
            and (
                axes.auto_executes
                or (axes.skips_team_kickoff and axes.honors_kickoff_grant)
            )
        ):
            tool._auto_grant_pending = True  # type: ignore[attr-defined]
        return None
    # Plan half skipped after confirmed ask; capability half may still need a card.
    # If only plan would have shown, skip entirely (legacy dual-card avoidance).
    if (
        skip_after_confirmed_ask(tool)
        and not needs_capability_auth(local_gate=local_gate, axes=axes)
        and plan_preview
    ):
        return None
    # 批 B：stage_card research_first 决议 → 当次 MLR 一次性 pre-auth（不得泛化）。
    if playbook_name == "multi_lens_research":
        from agentcore.runtime.kickoff.stage_card import (
            consume_mlr_preauth,
            mark_turn_keeps_stage_card,
        )

        if consume_mlr_preauth():
            # 真正跳过开工卡并开跑 → keep pending stage_card。
            mark_turn_keeps_stage_card()
            logger.info("delegate.mlr_preauth_skip_team_preview", call=call_idx)
            return None
    show_capabilities = needs_capability_auth(local_gate=local_gate, axes=axes)
    preview_decision = await await_team_preview(
        tool, plan, show_capabilities=show_capabilities
    )
    if tool._pending_pause:
        logger.info("delegate.team_preview_paused", call=call_idx, nodes=len(plan.nodes))
        return ToolResult(tool_call_id="", success=True, output="", effect=ToolEffect.SUSPEND)
    if preview_decision is CheckpointDecision.STOP:
        from agentcore.runtime.delegate.supervised import finalize_stopped
        from agentcore.runtime.kickoff.stage_card import clear_turn_keeps_stage_card

        # 用户 STOP：清 keep，允许回合收尾 orphan 未消费推进卡。
        if playbook_name == "multi_lens_research":
            clear_turn_keeps_stage_card()
        return await finalize_stopped(tool, plan, {})
    # CONTINUE / ADJUST：MLR 真正开跑 → keep。
    if playbook_name == "multi_lens_research":
        from agentcore.runtime.kickoff.stage_card import mark_turn_keeps_stage_card

        mark_turn_keeps_stage_card()
    return None

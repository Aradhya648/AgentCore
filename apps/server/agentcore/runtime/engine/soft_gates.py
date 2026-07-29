"""Captain soft gates after a no-tool Return: team-gate direct-reject + debate + audit.

Team-gate hard stop itself is investigation-only (tool-round path in ``governance.py``);
the direct-reject path here catches unclassified long wrap-ups after that hard stop.
"""

from __future__ import annotations

from collections.abc import Callable

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.loop_controller import LoopController

from .directive import Continue, LoopDirective, Return
from .governance import (
    maybe_inject_audit_gate,
    maybe_inject_audit_hard_block,
    maybe_inject_debate_gate,
    maybe_inject_team_gate_direct_reject,
    should_audit_gate,
    should_audit_hard_block,
    should_debate_gate,
    should_team_gate_direct_reject,
)
from .outcome import RoundOutcome


def maybe_soft_gate_no_tool_return(
    *,
    directive: LoopDirective,
    outcome: RoundOutcome,
    controller: LoopController,
    messages: list[LLMMessage],
    role: str,
    round_idx: int,
    run_id: str,
    content_before_round: str,
    emit_reset: Callable[[str], None],
) -> tuple[LoopDirective, str | None]:
    """Possibly discard a captain wrap-up draft and inject a soft/hard gate nudge.

    Order: debate-commitment, then team-gate direct-reject, then audit soft/hard.
    Soft audit is one-shot; hard audit (成篇) may re-block end_turn until review
    is dispatched.

    Returns ``(directive, rolled_back_content)``. ``rolled_back_content`` is
    ``content_before_round`` when a gate fired (caller must assign it to
    ``final_content``); ``None`` when the directive is unchanged.
    """
    if not isinstance(directive, Return) or not outcome.content:
        return directive, None

    # CEO / worker wrap-up: keep hard constraint on the system prompt when this
    # run still has uncompensated tool failures (same tally as the circuit breaker),
    # or when a delegate tool result still carries succeeded_after=false.
    from agentcore.runtime.tool_failures import (
        sync_tool_failure_constraint_in_system,
        team_outstanding_constraint_from_messages,
    )

    outstanding = controller.outstanding_tool_failures()
    team_text = team_outstanding_constraint_from_messages(messages)
    sync_tool_failure_constraint_in_system(
        messages,
        outstanding,
        constraint_text=None if outstanding else team_text,
    )

    if should_debate_gate(controller, role=role, messages=messages) and maybe_inject_debate_gate(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
    ):
        emit_reset("soft_gate")
        return Continue(), content_before_round

    # team_gate 后：无归类长文直答 / 摸底·改文件禁直答 → 丢稿再催一次（在审计闸之前）。
    if should_team_gate_direct_reject(
        controller, role=role, content=outcome.content or ""
    ) and maybe_inject_team_gate_direct_reject(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
        content=outcome.content or "",
    ):
        emit_reset("soft_gate")
        return Continue(), content_before_round

    if should_audit_gate(controller, role=role) and maybe_inject_audit_gate(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
    ):
        emit_reset("soft_gate")
        return Continue(), content_before_round

    if should_audit_hard_block(controller, role=role) and maybe_inject_audit_hard_block(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
    ):
        emit_reset("soft_gate")
        return Continue(), content_before_round
    return directive, None

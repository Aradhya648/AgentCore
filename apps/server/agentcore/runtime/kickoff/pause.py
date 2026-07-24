"""Durable kickoff pause — emit ``team_preview_*`` and capture a suspension frame."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.events import team_preview_required
from agentcore.runtime.kickoff.summary import KickoffSummary
from agentcore.tools.builtin import delegation_grantable_tool_names

logger = get_logger(__name__)


class KickoffHost(Protocol):
    """Minimal surface shared by ``DelegateTool`` / ``DebateTool`` for durable kickoff."""

    _sink: Any
    _message_id: str | None
    _conversation_id: str | None
    _suspension_saver: Any
    _pending_pause: bool
    _depth: int
    _captain_run_id: str | None
    _user_message: str
    _folder_id: str | None
    _memory_enabled: bool
    _base_tool_context: Any
    _registry: Any

    def _kickoff_system_prompt(self) -> str: ...

    def _kickoff_tool_name(self) -> str: ...


def kickoff_tools(*, show_capabilities: bool) -> list[str]:
    """GRANTABLE whitelist shown on the kickoff card as「将授权的能力范围」.

    Empty when AutonomyPolicy hides the capability half (not plan-derived).
    """
    if not show_capabilities:
        return []
    return sorted(delegation_grantable_tool_names())


def can_persist_kickoff(host: KickoffHost) -> bool:
    return bool(
        host._depth == 0
        and host._message_id
        and host._suspension_saver is not None
        and host._conversation_id
    )


async def persist_kickoff(
    host: KickoffHost,
    checkpoint_id: str,
    summary: KickoffSummary,
    required_event: Any,
    *,
    plan: Any | None = None,
) -> bool:
    """Capture + persist the durable kickoff frame. Returns True iff saved."""
    if not can_persist_kickoff(host):
        return False
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.suspension import TeamPreviewSuspension, find_tool_call_id
    from agentcore.runtime.suspension_capture import SuspensionCapture, persist_suspension_capture

    tool_name = host._kickoff_tool_name()
    plan_obj = plan if plan is not None else RunPlan()

    def build_frame(capture: SuspensionCapture) -> TeamPreviewSuspension:
        return TeamPreviewSuspension(
            message_id=host._message_id or "",
            conversation_id=host._conversation_id or "",
            user_id=host._base_tool_context.user_id,
            captain_run_id=host._captain_run_id or "",
            checkpoint_id=checkpoint_id,
            tool_call_id=find_tool_call_id(capture.transcript, tool_name),
            base_system_prompt=host._kickoff_system_prompt(),
            user_message=host._user_message,
            folder_id=host._folder_id,
            memory_enabled=host._memory_enabled,
            transcript=capture.transcript,
            history=capture.history,
            plan=plan_obj,
            completed={},
            journal_entries=capture.journal_entries,
            workers=list(summary.workers),
            tools=list(summary.tools),
            primitive=summary.primitive,
            motion=summary.motion,
            form=summary.form,
            sides=list(summary.sides),
            max_rounds=summary.max_rounds,
            thorough=summary.thorough,
            debate_arguments=dict(summary.debate_arguments),
            offer_research_first=bool(summary.offer_research_first),
            research_first_recommended=bool(summary.research_first_recommended),
            # 委派批次协作参数：挂起点在 setup_note_wall 之前，这三样只活在工具实例上，
            # 不落帧则耐久恢复（全新工具实例）后 wall 批降级 none、seed 便签丢失。
            # DebateTool 无这些属性 → getattr 缺省（辩论批无便签墙）。
            coordination=str(getattr(host, "_coordination", "none") or "none"),
            team_brief=getattr(host, "_team_brief", None),
            seed_notes=list(getattr(host, "_seed_notes", None) or []),
            citations=capture.citations,
            trace_id=capture.trace_id,
        )

    return await persist_suspension_capture(
        checkpoint_id=checkpoint_id,
        required_event=required_event,
        build_frame=build_frame,
        saver=host._suspension_saver,
        sink=host._sink,
        suspension_kind="team_preview",
    )


async def await_kickoff(
    host: KickoffHost,
    summary: KickoffSummary,
    *,
    plan: Any | None = None,
) -> CheckpointDecision | None:
    """Pause before fan-out / moderator start; return decision, or None when suspended.

    On durable save: sets ``host._pending_pause`` and returns ``None`` so the caller
    ends with SUSPEND. Config unavailable (no transcript): CONTINUE. Runtime saver
    failure raises (D11 — no silent continue).
    """
    registry = host._registry
    conversation_id = host._conversation_id
    if registry is None or conversation_id is None:
        return CheckpointDecision.CONTINUE
    if host._depth != 0:
        return CheckpointDecision.CONTINUE

    checkpoint_id = new_id()
    # Debate kickoff: compute「先多视角调研再辩」— journal 卡/MLR ∪ 工作区 research/ 产物；
    # research_first_recommended：零调研案卷 ∧ 用户输入命中多维取证触发词。
    offer_research_first = False
    research_first_recommended = False
    if summary.primitive == "debate":
        from agentcore.runtime.debate.research_dossier import (
            workspace_has_research_artifacts,
        )
        from agentcore.runtime.facts import snapshot_fact_log
        from agentcore.runtime.kickoff.research_first import (
            should_offer_research_first,
            should_recommend_research_first,
        )

        has_research = False
        backend = getattr(host._base_tool_context, "backend", None)
        if backend is not None:
            try:
                has_research = await workspace_has_research_artifacts(backend)
            except Exception:
                logger.exception("kickoff.research_dossier_probe_failed")
                has_research = False
        journal = snapshot_fact_log()
        offer_research_first = should_offer_research_first(
            journal,
            has_research_artifacts=has_research,
        )
        research_first_recommended = should_recommend_research_first(
            journal,
            has_research_artifacts=has_research,
            user_message=host._user_message,
        )
    summary_with_offer = (
        summary
        if (
            summary.offer_research_first == offer_research_first
            and summary.research_first_recommended == research_first_recommended
        )
        else replace(
            summary,
            offer_research_first=offer_research_first,
            research_first_recommended=research_first_recommended,
        )
    )
    card = summary_with_offer.card_payload()
    required = team_preview_required(
        checkpoint_id=checkpoint_id,
        conversation_id=conversation_id,
        workers=card["workers"],
        tools=card["tools"],
        primitive=card["primitive"],
        motion=card["motion"],
        form=card["form"],
        sides=card["sides"],
        max_rounds=card["max_rounds"],
        thorough=card["thorough"],
        offer_research_first=offer_research_first,
        research_first_recommended=research_first_recommended,
    )
    try:
        saved = await persist_kickoff(
            host, checkpoint_id, summary_with_offer, required, plan=plan
        )
    except Exception:
        # D11：运行态落帧失败（saver 抛错）⇒ 显式终止，不许静默 CONTINUE 开工。
        logger.exception(
            "team_preview.persist_failed",
            checkpoint_id=checkpoint_id,
            primitive=summary_with_offer.primitive,
        )
        raise
    if saved:
        host._sink.emit(required)
        host._pending_pause = True
        logger.info(
            "team_preview.finalized",
            checkpoint_id=checkpoint_id,
            primitive=summary_with_offer.primitive,
            workers=len(summary_with_offer.workers),
            tools=summary_with_offer.tools,
            offer_research_first=offer_research_first,
            research_first_recommended=research_first_recommended,
        )
        return None

    # 配置态不可用（无 transcript 等非生产场景）⇒ CONTINUE。
    logger.warning(
        "team_preview.persist_unavailable",
        checkpoint_id=checkpoint_id,
        reason="no_durable_frame",
        primitive=summary_with_offer.primitive,
    )
    return CheckpointDecision.CONTINUE

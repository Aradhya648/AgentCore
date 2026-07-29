"""Durable resume pipeline orchestrator for plan_review / ask_user checkpoints."""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict

import agentcore.runtime.pipeline as pipeline_pkg
from agentcore.core.error_codes import ErrorCode
from agentcore.core.errors import error_fields_for
from agentcore.core.logging import get_logger
from agentcore.core.types import DEFAULT_PERMISSION_AXES, PermissionAxes, new_id
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import TurnProfiles as ProfileSet
from agentcore.llm.profiles import turn_profiles_for_turn
from agentcore.runtime.approvals import ApprovalGate  # noqa: F401 — test seam
from agentcore.runtime.audit.hooks import bind_recorder
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.costing import captain_run_cost_from_state
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    content_delta,
    error_event,
    message_end,
)
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer
from agentcore.runtime.pipeline.resume.finish import finish_resume_turn, finish_terminal_resume
from agentcore.runtime.pipeline.resume.recover_path import recover_and_rebuild_window
from agentcore.runtime.pipeline.resume.rehydrate import (
    arm_content_reset_reinjection,
    bootstrap_resume_display,
    mark_controller_after_settle,
)
from agentcore.runtime.pipeline.resume.wire import restamp_workspace_facts, wire_resume_turn
from agentcore.runtime.resolve.prepare import _assemble_ceo_toolset  # noqa: F401 — wire seam
from agentcore.runtime.runs import RunKind, RunPhase, RunSpec, build_captain_resumer
from agentcore.runtime.session_persistence import SessionRosterWriter
from agentcore.runtime.sessions import SessionLoader, SessionSaver
from agentcore.runtime.settlement import seed_settlement_dedupe_from_entries
from agentcore.runtime.suspension import (
    SuspensionDeleter,
    SuspensionSaver,
    TurnSuspension,
    turn_citations,
    turn_evidence_ledger,
    turn_history,
)
from agentcore.workspace.protocol import WorkspaceBackend

logger = get_logger(__name__)

# Compat: tests import the private name from this module.
_restamp_workspace_facts = restamp_workspace_facts


async def resume_chat_pipeline(
    *,
    suspension: TurnSuspension,
    decision: CheckpointDecision,
    note: str,
    selected: list[str] | None = None,
    style_id: str | None = None,
    format_id: str | None = None,
    sink: EventSink,
    backend: WorkspaceBackend,
    history: list[dict] | None = None,
    board_id: str | None = None,
    llm_credentials: LLMCredentials | None = None,
    profile_set: ProfileSet | None = None,
    session_saver: SessionSaver | None = None,
    session_loader: SessionLoader | None = None,
    suspension_saver: SuspensionSaver | None = None,
    suspension_deleter: SuspensionDeleter | None = None,
    llm_supports_tools: bool | None = None,
    permission_axes: PermissionAxes | None = None,
    x_client_platform: str | None = None,
) -> dict:
    """Continue a turn paused at a plan_review / ask_user checkpoint (结构化挂起 2b resume).

    Rebuilds the turn from the §8.3 turn journal and finishes it: re-wire the CEO
    toolset, seed the display journal with the pre-pause graph, **rebuild the CEO window
    by folding the journal facts** (:func:`resumed_captain_window` — the captain
    transcript is a projection of the journal, no longer read from ``frame.transcript``,
    执行级事件溯源 Phase 2 ④), apply the user's decision to the paused frame by kind
    (:func:`recover_turn`), feed the settled result back as the suspended
    tool result, and — unless the answer ended the turn in-band (ask_user ``stop``) — run
    the CEO loop on the rebuilt window to its reply. ``history`` is the reloaded prior
    context (the caller passes ``load_chat_context(...)[:-1]`` exactly as a fresh send),
    spliced into the window head since the journal stores only its length. The whole turn
    is billed ONCE here, under the ORIGINAL ``message_id`` so the assistant row + ledger
    reuse it. A downstream checkpoint can pause again — the same hooks re-persist a fresh
    frame, so resume is fully re-entrant. ``selected`` carries the user's option picks
    (ask_user only). ``style_id`` is the structured website style pick when present.
    ``format_id`` is the structured presentation format pick when present.
    Returns the same result shape as :func:`run_chat_pipeline`.

    ``board_id`` marks the resumed turn as a 白板会话 (AI协作白板.md §六 M2): re-derived by
    the caller from the conversation's board binding (authoritative in the DB, not stored in
    the frame), so a board turn that paused at a checkpoint regains the ``board_ops`` tool +
    its :class:`BoardChannel` on resume and can keep drawing on the user's canvas. ``None``
    for every ordinary chat — then ``board_ops`` is neither wired nor reachable, exactly as
    on the fresh-turn path.

    ``permission_axes`` mirrors :func:`run_chat_pipeline`: the conversation's CURRENT
    three-axis permission mode, resolved by the caller at resume time — not frozen
    into the frame. ``None`` falls back to write_code defaults.
    """
    if permission_axes is None:
        permission_axes = DEFAULT_PERMISSION_AXES
    profiles = turn_profiles_for_turn(profile_set, llm_credentials)
    message_id = suspension.message_id
    conversation_id = suspension.conversation_id
    captain_run_id = suspension.captain_run_id or new_id()
    # Same ambient pricing bind as prepare_chat_turn — resume must not lose BYOK
    # ``credential_source`` or calculate_cost falls through to platform billing.
    from agentcore.llm.credentials import bind_credential_pricing_context

    bind_credential_pricing_context(llm_credentials)
    # 真·多模型辩手：同 run.py，回合 llm = DeepSeek 默认外包一层 ProviderRouter（resume 也可能
    # 续跑含多模型辩手的辩论）。Cross-provider Worker 默认经 build_turn_router 注入。
    llm = await pipeline_pkg.build_turn_router(
        llm_credentials, user_id=suspension.user_id, profiles=profiles
    )
    # Republish history so a re-pause DURING the settle (a downstream checkpoint while
    # resume_plan runs) captures it into the fresh frame — symmetric with the live turn
    # (Phase 2 ⑤). Reset in finally.
    history_token = turn_history.set(history or [])
    memory_cache_token = None
    from agentcore.core.log_context import get_log_value

    # Seed past both the pause snapshot AND any live append-on-emit rows that outran
    # the sidecar (tool_use_end / message_final / … after pause) — else UniqueViolation.
    journal_base = len(suspension.journal_entries)
    db_max_seq: int | None = None
    initial_seq = journal_base
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as db:
            db_max_seq = await TurnJournalRepository(db).max_seq(message_id)
        if db_max_seq is not None:
            initial_seq = max(journal_base, db_max_seq + 1)
    except Exception as e:  # noqa: BLE001 — best-effort; never block resume on journal probe
        logger.warning(
            "pipeline.resume_initial_seq_fallback",
            message_id=message_id,
            journal_entries_count=journal_base,
            error=str(e),
        )
        initial_seq = journal_base

    logger.info(
        "pipeline.resume_start",
        message_id=message_id,
        conversation_id=conversation_id,
        decision=decision.value,
        journal_entries_count=journal_base,
        initial_seq=initial_seq,
        db_max_seq=db_max_seq,
    )

    journal_writer = TurnJournalWriter(
        turn_id=message_id,
        conversation_id=conversation_id,
        trace_id=suspension.trace_id or get_log_value("trace_id"),
        initial_seq=initial_seq,
    )
    # D8：冷路端点已预写 ``*_resolved``；claim 把它收进 journal_entries。种子化 dedupe，
    # 使 recover 路径的同形 emit 跳过重复落库（SSE 仍发）。
    seed_settlement_dedupe_from_entries(journal_writer, suspension.journal_entries)
    journal_writer_token = current_journal_writer.set(journal_writer)
    audit_recorder, audit_token = bind_recorder(
        user_id=suspension.user_id,
        conversation_id=conversation_id,
        turn_id=message_id,
        trace_id=suspension.trace_id or get_log_value("trace_id"),
        captain_run_id=captain_run_id,
        delegated=bool(
            (getattr(suspension, "plan", None) and getattr(suspension.plan, "nodes", None))
            or permission_axes.implies_deep_research_auto
        ),
        permission_preset=(
            json.dumps(permission_axes.to_dict()) if permission_axes is not None else None
        ),
    )
    # Session roster write-through (as-built: 成本配额 §三): fire-and-forget + turn-end flush (parity with run).
    roster_writer = SessionRosterWriter.wrap(session_saver)
    session_saver = roster_writer.save if roster_writer is not None else None
    fact_log = TurnFactLog(inherited_entries=list(suspension.journal_entries))
    fact_log_token = current_fact_log.set(fact_log)
    from agentcore.runtime.turn_token_budget import (
        bind_turn_token_meter,
        reset_turn_token_meter,
        tokens_from_journal_entries,
    )

    # Resume 续计：从 journal llm_call 事实播种已花 token，再累加本段新调用。
    turn_token_meter_token = bind_turn_token_meter(
        seed=tokens_from_journal_entries(suspension.journal_entries)
    )
    execution_id_token = None
    bound_execution_id: str | None = None
    pre_pause = ""
    pre_pause_reasoning = ""
    citations_token = None
    ledger_token = None
    try:
        wired = await wire_resume_turn(
            suspension=suspension,
            llm=llm,
            sink=sink,
            backend=backend,
            board_id=board_id,
            conversation_id=conversation_id,
            message_id=message_id,
            captain_run_id=captain_run_id,
            profiles=profiles,
            permission_axes=permission_axes,
            session_saver=session_saver,
            session_loader=session_loader,
            suspension_saver=suspension_saver,
            suspension_deleter=suspension_deleter,
            x_client_platform=x_client_platform,
        )
        bound_execution_id = wired.bound_execution_id
        execution_id_token = wired.execution_id_token

        # Shared display open (live + tape): message_start + journal seed + turn_paused.
        hydrated = bootstrap_resume_display(
            sink=sink,
            suspension=suspension,
            conversation_id=conversation_id,
        )
        pre_pause_reasoning = hydrated.pre_pause_reasoning
        citations: list[dict] = list(hydrated.citations)
        # G2 dual落点: citation_sink list + turn_citations contextvar (same list).
        citations_token = turn_citations.set(citations)
        # P1 第 3 步：resume 再水化 turn_paused 台账快照（空快照 = 空台账，新登记续号）。
        resume_ledger = EvidenceLedgerCore(id_prefix="#r")
        if hydrated.evidence_ledger:
            resume_ledger.load_entries(hydrated.evidence_ledger)
        ledger_token = turn_evidence_ledger.set(resume_ledger)
        # P1a：建站风格确认从 turn_paused / journal 再水化进 conversation ledger。
        from agentcore.runtime.runs.website_style import rehydrate_style_confirmation

        rehydrate_style_confirmation(
            conversation_id,
            entries=list(suspension.journal_entries or []),
            turn_paused_style=hydrated.website_style,
        )
        # 演讲/PPT 交付形态确认从 turn_paused / journal 再水化。
        from agentcore.runtime.runs.presentation_format import (
            rehydrate_format_confirmation,
        )

        rehydrate_format_confirmation(
            conversation_id,
            entries=list(suspension.journal_entries or []),
            turn_paused_format=hydrated.presentation_format,
        )
        # Agent/自动化开工形态确认从 turn_paused / journal 再水化。
        from agentcore.runtime.runs.automation_delivery import (
            rehydrate_delivery_confirmation,
        )

        rehydrate_delivery_confirmation(
            conversation_id,
            entries=list(suspension.journal_entries or []),
            turn_paused_delivery=hydrated.automation_delivery,
        )
        controller_seed = hydrated.controller_seed

        recovered = await recover_and_rebuild_window(
            suspension=suspension,
            decision=decision,
            note=note,
            selected=selected,
            style_id=style_id,
            format_id=format_id,
            history=history,
            sink=sink,
            delegate_tool=wired.delegate_tool,
            debate_tool=wired.debate_tool,
            execution_id=wired.base_tool_context.execution_id,
            captain_run_id=captain_run_id,
            pre_pause_override=hydrated.pre_pause_content,
        )
        pre_pause = recovered.pre_pause
        settled = recovered.settled
        messages = recovered.messages

        # 记忆复用：帧内已查主题 + 窗口里历史 consult_memory 对 → 同 key 不再打 store。
        from agentcore.runtime.memory_consult_cache import (
            consulted_memory_cache,
            get_consult_cache,
            seed_consult_cache_from_window,
        )

        memory_cache_token = consulted_memory_cache.set(
            dict(getattr(suspension, "consulted_memory", None) or {})
        )
        seeded = seed_consult_cache_from_window(messages)
        if seeded or get_consult_cache():
            logger.info(
                "consult_memory.cache_seeded",
                from_frame=len(getattr(suspension, "consulted_memory", None) or {}),
                from_window=seeded,
                total=len(get_consult_cache()),
            )

        # G6: resume-segment content_reset must reinject the authoritative pre_pause
        # into the client bubble (display-only). Engine CEO on_reset stays None.
        arm_content_reset_reinjection(sink, pre_pause)

        # G5 settle 侧补标: team_preview / plan_review paused before tool return.
        if hydrated.from_turn_paused:
            controller_seed = mark_controller_after_settle(controller_seed, suspension)

        # ask_user stop: the closing note IS the reply (terminal effect) — finish
        # without another CEO round, mirroring the engine's terminal-effect branch.
        if settled.terminal_text is not None:
            if settled.terminal_text:
                sink.emit(content_delta(settled.terminal_text))
            result = finish_terminal_resume(
                message_id=message_id,
                pre_pause_content=pre_pause,
                closing=settled.terminal_text,
                sink=sink,
                pre_pause_reasoning=pre_pause_reasoning,
            )
            await audit_recorder.flush()
            if roster_writer is not None:
                await roster_writer.flush()
            result["audit_drops"] = audit_recorder.drops
            return result

        # Otherwise run the CEO loop to its reply (it may delegate / ask again).
        from agentcore.runtime.captain_profile import apply_captain_max_rounds

        profile = apply_captain_max_rounds(profiles.get("chat"))
        turn_model = profiles.model_for("chat")
        captain_spec = RunSpec(
            run_id=captain_run_id,
            agent_id=captain_run_id,
            agent_name="CEO",
            kind=RunKind.CAPTAIN,
            task=suspension.user_message,
            role="CEO",
            depth=0,
            parent_run_id=None,
        )
        run_captain = build_captain_resumer(
            llm=llm,
            tools=wired.chat_tools,
            sink=sink,
            base_tool_context=wired.base_tool_context,
            profile=profile,
            turn_model=turn_model,
            citation_sink=citations,
            approval_gate=wired.approval_gate,
            supports_tools=llm_supports_tools,
            controller_seed=controller_seed,
            turn_evidence_ledger=turn_evidence_ledger.get(),
        )
        captain_state = await run_captain(captain_spec, messages)

        if captain_state.phase is RunPhase.FAILED:
            err = captain_state.error or "captain resume failed"
            sink.emit(error_event(ErrorCode.PIPELINE_ERROR, err))
            sink.emit(message_end(FinishReason.ERROR))
            with contextlib.suppress(Exception):
                await sink.flush_stream_state()
            from agentcore.conversation.store.merge import pick_longest
            from agentcore.runtime.events.stream_checkpointer import (
                CHANNEL_CAPTAIN_CONTENT,
                CHANNEL_CAPTAIN_REASONING,
            )

            mem = sink.stream_memory_snapshot()
            post = pick_longest(
                mem.get(CHANNEL_CAPTAIN_CONTENT),
                captain_state.content,
                sink.streamed_content(),
            )
            from agentcore.runtime.closing_posture import reconcile_resume_closing

            salvaged_content = reconcile_resume_closing(pre_pause, post)
            salvaged_reasoning = pick_longest(
                mem.get(CHANNEL_CAPTAIN_REASONING),
                captain_state.reasoning,
                sink.streamed_reasoning(),
            )
            # Bill the resumed captain's partial spend on a hard failure (B-deep 失败
            # 计费), same as the fresh-turn path: priced onto captain_state, persisted
            # by _persist_turn_result even without an assistant reply. No usage → no row.
            cost_runs = [
                *(
                    [asdict(captain_run_cost_from_state(captain_run_id, captain_state))]
                    if captain_state.usage
                    else []
                ),
                # A board_read after the checkpoint may have billed before the captain
                # died (§九.4 Gap ②): carry those vision rows so the spend isn't lost.
                *(asdict(r) for r in wired.vision_cost_sink),
            ]
            await audit_recorder.flush()
            if roster_writer is not None:
                await roster_writer.flush()
            return {
                "message_id": message_id,
                "content": salvaged_content,
                "reasoning_content": salvaged_reasoning or None,
                "error": err,
                "error_code": ErrorCode.PIPELINE_ERROR,
                "finish_reason": FinishReason.ERROR,
                "cost_runs": cost_runs,
                "audit_drops": audit_recorder.drops,
            }

        result = await finish_resume_turn(
            message_id=message_id,
            captain_run_id=captain_run_id,
            captain_state=captain_state,
            pre_pause_content=pre_pause,
            delegate_tool=wired.delegate_tool,
            debate_tool=wired.debate_tool,
            profile=profile,
            citations=citations,
            sink=sink,
            vision_cost_runs=wired.vision_cost_sink,
            audit_drops=audit_recorder.drops,
            pre_pause_reasoning=pre_pause_reasoning,
        )
        # Drain journal → audit projection fully BEFORE 定格 audit_drops (parity with
        # run_chat_pipeline): the finally re-flush would otherwise drop more audit writes
        # after drops was read, undercounting turn_metrics.audit_drops. Best-effort.
        with contextlib.suppress(Exception):
            await journal_writer.flush()
        await audit_recorder.flush()
        if roster_writer is not None:
            await roster_writer.flush()
        with contextlib.suppress(Exception):
            await sink.flush_stream_state()
        result["audit_drops"] = audit_recorder.drops
        return result

    except Exception as e:
        logger.error("pipeline.resume_error", error=str(e), exc_info=True)
        # Preserve a structured AgentCoreError.code that escaped to the resume
        # boundary instead of flattening every crash to PIPELINE_ERROR (统一错误码).
        code, message, err_ctx = error_fields_for(
            e, fallback_code=ErrorCode.PIPELINE_ERROR, fallback_message=str(e)
        )
        sink.emit(error_event(code, message, context=err_ctx))
        sink.emit(message_end(FinishReason.ERROR))
        with contextlib.suppress(Exception):
            await sink.flush_stream_state()
        from agentcore.conversation.store.merge import pick_longest
        from agentcore.runtime.events.stream_checkpointer import (
            CHANNEL_CAPTAIN_CONTENT,
            CHANNEL_CAPTAIN_REASONING,
        )

        mem = sink.stream_memory_snapshot()
        post = pick_longest(mem.get(CHANNEL_CAPTAIN_CONTENT), sink.streamed_content())
        # pre_pause may be unbound if the crash was before it was computed.
        from agentcore.runtime.closing_posture import reconcile_resume_closing

        salvaged_content = (
            reconcile_resume_closing(pre_pause, post) if pre_pause or post else ""
        )
        salvaged_reasoning = pick_longest(
            mem.get(CHANNEL_CAPTAIN_REASONING),
            sink.streamed_reasoning(),
        )
        await audit_recorder.flush()
        if roster_writer is not None:
            await roster_writer.flush()
        return {
            "message_id": message_id,
            "content": salvaged_content,
            "reasoning_content": salvaged_reasoning or None,
            "error": str(e),
            "error_code": code,
            "finish_reason": FinishReason.ERROR,
            "audit_drops": audit_recorder.drops,
        }
    finally:
        # 触发点①：resume turn 结束防御性 orphan
        with contextlib.suppress(Exception):
            from agentcore.runtime.interaction_orphan import orphan_registry_pending

            await orphan_registry_pending(conversation_id, turn_id=message_id)
        with contextlib.suppress(Exception):
            from agentcore.conversation.stage_card_resolve import (
                maybe_orphan_stage_cards_at_turn_end,
            )

            await maybe_orphan_stage_cards_at_turn_end(conversation_id, sink=sink)
        current_fact_log.reset(fact_log_token)
        # Drain the append-on-emit journal BEFORE dropping the writer: an abandoned in-flight
        # write leaves a checked-out DB connection for the GC to terminate (asyncpg
        # connection_lost noise). Best-effort — a drain failure must never break turn teardown.
        with contextlib.suppress(Exception):
            await journal_writer.flush()
        current_journal_writer.reset(journal_writer_token)
        from agentcore.runtime.audit.recorder import current_audit_recorder

        with contextlib.suppress(Exception):
            await audit_recorder.flush()
        with contextlib.suppress(Exception):
            if roster_writer is not None:
                await roster_writer.flush()
        current_audit_recorder.reset(audit_token)
        turn_history.reset(history_token)
        if memory_cache_token is not None:
            from agentcore.runtime.memory_consult_cache import consulted_memory_cache

            consulted_memory_cache.reset(memory_cache_token)
        if citations_token is not None:
            turn_citations.reset(citations_token)
        if ledger_token is not None:
            turn_evidence_ledger.reset(ledger_token)
        reset_turn_token_meter(turn_token_meter_token)
        if execution_id_token is not None:
            from agentcore.runtime.coordination.session import (
                current_execution_id,
                release_turn_coordination,
            )

            # Settle may realign to the pause-turn id; release that registry key
            # (preserve live background drives — async team model).
            eid = current_execution_id.get() or bound_execution_id
            if eid:
                with contextlib.suppress(Exception):
                    release_turn_coordination(eid)
            current_execution_id.reset(execution_id_token)
        # Do NOT close the sink here (see run_chat_pipeline): its owner closes it, so the
        # resumed turn's persist_turn_result tail (title / followups) still reaches the client.
        with contextlib.suppress(Exception):
            await llm.close()

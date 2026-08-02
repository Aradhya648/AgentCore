"""Fresh-turn chat pipeline: Prepare -> Assemble -> Execute -> Settle."""

from __future__ import annotations

import contextlib
import json
import time

from agentcore.core.logging import get_logger
from agentcore.core.types import PermissionAxes, new_id
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import TurnProfiles as ProfileSet
from agentcore.llm.profiles import turn_profiles_for_turn
from agentcore.memory import default_memory_store  # noqa: F401 — test seam
from agentcore.runtime.audit.hooks import bind_recorder
from agentcore.runtime.events import EventSink, message_start
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import (
    TurnFactLog,
    TurnStartedFact,
    current_fact_log,
    record_turn_fact,
)
from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer
from agentcore.runtime.pipeline.assemble import assemble_ceo_turn
from agentcore.runtime.pipeline.prepare import prepare_fresh_turn
from agentcore.runtime.pipeline.settle import (
    captain_failed,
    salvage_failed_captain,
    salvage_pipeline_exception,
    settle_successful_turn,
)
from agentcore.runtime.resolve.prepare import _assemble_ceo_toolset  # noqa: F401 — test seam
from agentcore.runtime.runs import RunKind, RunSpec, build_captain_executor
from agentcore.runtime.session_persistence import SessionRosterWriter
from agentcore.runtime.sessions import SessionLoader, SessionSaver
from agentcore.runtime.suspension import (
    SuspensionDeleter,
    SuspensionSaver,
    turn_citations,
    turn_evidence_ledger,
    turn_history,
)
from agentcore.runtime.turn_latency import get_turn_latency
from agentcore.workspace.protocol import WorkspaceBackend

# Re-exported so tests can monkeypatch lookup sites on this module (see
# ``test_pipeline_governance._patch_pipeline``). prepare/assemble resolve these
# via this module so patches keep working after the structural split.
__all_seams__ = ("default_memory_store", "_assemble_ceo_toolset")

logger = get_logger(__name__)


async def run_chat_pipeline(
    *,
    conversation_id: str,
    user_message: str,
    history: list[dict],
    sink: EventSink,
    user_id: str,
    backend: WorkspaceBackend,
    folder_id: str | None = None,
    board_id: str | None = None,
    attachments: list[dict] | None = None,
    approvals_enabled: bool = True,
    memory_enabled: bool = True,
    conversation_history_access: bool = True,
    permission_axes: PermissionAxes | None = None,
    profile_set: ProfileSet | None = None,
    llm_credentials: LLMCredentials | None = None,
    session_saver: SessionSaver | None = None,
    session_loader: SessionLoader | None = None,
    suspension_saver: SuspensionSaver | None = None,
    suspension_deleter: SuspensionDeleter | None = None,
    llm_supports_tools: bool | None = None,
    message_id: str | None = None,
    x_client_platform: str | None = None,
) -> dict:
    """Run the full chat pipeline for a single user message.

    Returns a dict with final_content, usage, and metadata.
    The sink receives all SSE events during execution.

    ``approvals_enabled`` gates GRANTABLE tools behind the user's consent (the
    default interactive path). It is set False for an autonomous local→云 handoff
    job (双模式工作区 P2e / e2): that run has no live client to answer prompts and
    operates on an isolated server sandbox, so — like cloud-mode workers — it needs
    no gate; leaving it on would deadlock every file/exec tool on a timeout-deny.

    ``memory_enabled`` is a caller-supplied runtime gate (product resolve is always
    True / 定案 A): False injects no memory <rules> this turn — kept for internal
    False-path unit tests and durable suspension frames.

    ``permission_axes`` is the conversation's three-axis permission mode
    (安全权限与治理 · 会话级权限): file_write / command / team_kickoff.
    ask_user / plan_review / circuit-breakers are orthogonal. ``command=ask``
    withholds the execution class at worker registry.

    ``folder_id`` is the conversation's project (None for a bare/global chat): it selects
    the memory SCOPE so a project conversation also gets that project's memory layer
    injected (global + project), and ``consult_memory`` searches both (Agent记忆与知识系统 §二).

    ``board_id`` marks this turn as a 白板会话 (AI协作白板.md §六 M2): when set, the CEO
    gains the ``board_ops`` tool + a :class:`BoardChannel` bound to that board, so it can
    apply structured ops to the user's open whiteboard canvas. ``None`` for every ordinary
    chat — then ``board_ops`` is neither wired nor reachable.

    ``x_client_platform`` is the raw ``X-Client-Platform`` header (desktop / mobile-web /
    …). Gates ``ask_user``'s ``action=bind_local_folder`` advertisement and the
    ``<workspace_context>`` desktop-online line — cloud web/mobile must not see the bind
    action. ``None`` / absent defaults to desktop (legacy tests).

    ``profile_set`` is the turn's per-scenario model set — which model each scenario
    (chat / agent / ...) runs this turn — resolved by the caller from the user's
    configured model. ``None`` (e.g. the autonomous handoff job) falls back to the
    default profile set.

    ``llm_credentials`` are the turn's resolved BYOK key + endpoint (config.
    billing_mode); the caller resolves them once (route preflight) and threads them
    here so the whole turn runs on the user's own DeepSeek quota. ``None`` falls
    back to the global server key (platform mode).
    """
    profiles = turn_profiles_for_turn(profile_set, llm_credentials)
    message_id = message_id or new_id()
    # The CEO captain is the turn's root Run node (kind=captain): it owns the reply
    # voice and may delegate. Its run id parents every delegated member's ledger row
    # and labels the captain cost row; agent_id == run_id (阶段1 convention). When
    # the CEO delegates, this id is declared as the graph's CAPTAIN 汇聚点 the
    # workers hang under (see delegate.plan_events.plan_event).
    captain_run_id = new_id()

    # 执行级事件溯源 (§8.3): the turn's single ordered fact log. Bound to the ambient
    # contextvar BEFORE any sink.emit / captain run so the engine's execution facts
    # (round_boundary / llm_call / note / message_final) AND the sink's display facts
    # (run_*/tool_use_*/interaction) accumulate here in ONE order — copied into each
    # delegated worker's task, so the whole team writes to this log. Reset in finally.
    fact_log = TurnFactLog()
    fact_log_token = current_fact_log.set(fact_log)
    # Append-on-emit: every fact is durably written before its SSE event is delivered.
    from agentcore.core.log_context import get_log_value
    from agentcore.runtime.kickoff.stage_card import reset_stage_card_turn_flags

    reset_stage_card_turn_flags()

    journal_writer = TurnJournalWriter(
        turn_id=message_id,
        conversation_id=conversation_id,
        trace_id=get_log_value("trace_id"),
    )
    journal_writer_token = current_journal_writer.set(journal_writer)
    audit_recorder, audit_token = bind_recorder(
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=message_id,
        trace_id=get_log_value("trace_id"),
        captain_run_id=captain_run_id,
        # P2: managed axes (command=auto ∧ team_kickoff=skip) collect fuller trail.
        delegated=(
            permission_axes is not None and permission_axes.implies_deep_research_auto
        ),
        permission_axes=(
            json.dumps(permission_axes.to_dict()) if permission_axes is not None else None
        ),
    )
    # Session roster write-through (as-built: 成本配额 §三): fire-and-forget on the hot path,
    # flush with audit at turn-end so cross-turn load-on-miss stays durable.
    roster_writer = SessionRosterWriter.wrap(session_saver)
    session_saver = roster_writer.save if roster_writer is not None else None
    # 执行级事件溯源 Phase 2 ⑤: publish this turn's history so a suspending face captures it
    # into the durable frame — the resume window splices it ahead of the journal-folded
    # rounds (the journal stores only history's LENGTH). Reset in finally.
    history_token = turn_history.set(history)
    # Web sources the chat agent consults this turn (web_search / read_url), aggregated +
    # de-duped by the loop for source cards + persistence. Published on ``turn_citations``
    # (same pattern as history) so a suspending face snapshots the pool into the durable
    # frame — the resume re-seeds it and pre-pause [n] markers keep their cards (引用池
    # 单一权威). The loop mutates this same list via ``citation_sink``. Reset in finally.
    citations: list[dict] = []
    citations_token = turn_citations.set(citations)
    from agentcore.llm.turn_auth_dead import bind_turn_auth_dead, reset_turn_auth_dead
    from agentcore.runtime.memory_consult_cache import consulted_memory_cache
    from agentcore.runtime.turn_token_budget import bind_turn_token_meter, reset_turn_token_meter

    # Turn 级 token 累计 meter（CEO + 全树 worker）；log_llm_call 写入，触顶禁新派。
    turn_token_meter_token = bind_turn_token_meter(seed=0)
    # Turn 级 API Key 鉴权死位（甲+乙）：首次 LLMAuthError 后短路未启动 LLM。
    turn_auth_dead_token = bind_turn_auth_dead()

    memory_cache_token = consulted_memory_cache.set({})
    # 回合共享调研台账（引用即出处 P1）：与引用池同入口创建；captain / 调研 worker
    # 注入同一对象，并行登记原子拿 ``#rN``。辩论场级 ``#e`` 台账不经此路径。
    # 跨回合 hydrate：合并本会话历史 assistant 的 evidence_ledger（引擎核；LLM 可不带全文）。
    evidence_ledger = EvidenceLedgerCore(id_prefix="#r")
    evidence_ledger.merge_history_ledgers(history)
    ledger_token = turn_evidence_ledger.set(evidence_ledger)
    # CEO 协调模式: turn-level execution_id for registry lookup (captain wait path).
    # Bound after base_tool_context is minted (inside try); reset in finally.
    execution_id_token = None
    bound_execution_id: str | None = None
    llm = None

    try:
        latency_probe = get_turn_latency()
        prepare_t0 = time.monotonic()
        prepared = await prepare_fresh_turn(
            conversation_id=conversation_id,
            user_id=user_id,
            backend=backend,
            sink=sink,
            folder_id=folder_id,
            board_id=board_id,
            attachments=attachments,
            memory_enabled=memory_enabled,
            conversation_history_access=conversation_history_access,
            permission_axes=permission_axes,
            llm_credentials=llm_credentials,
            x_client_platform=x_client_platform,
            profiles=profiles,
        )
        if latency_probe is not None:
            latency_probe.mark_prepare(int((time.monotonic() - prepare_t0) * 1000))
        llm = prepared.llm
        bound_execution_id = prepared.bound_execution_id
        execution_id_token = prepared.execution_id_token

        assemble_t0 = time.monotonic()
        assembled = await assemble_ceo_turn(
            prepared=prepared,
            conversation_id=conversation_id,
            user_message=user_message,
            history=history,
            sink=sink,
            backend=backend,
            folder_id=folder_id,
            memory_enabled=memory_enabled,
            conversation_history_access=conversation_history_access,
            approvals_enabled=approvals_enabled,
            permission_axes=permission_axes,
            profiles=profiles,
            captain_run_id=captain_run_id,
            message_id=message_id,
            session_saver=session_saver,
            session_loader=session_loader,
            suspension_saver=suspension_saver,
            suspension_deleter=suspension_deleter,
            x_client_platform=x_client_platform,
        )
        if latency_probe is not None:
            latency_probe.mark_assemble(int((time.monotonic() - assemble_t0) * 1000))

        # 出处诚实：hydrate 后注入「已登记来源」结构化摘要（对照台账字段，禁占位叙事）。
        from agentcore.runtime.evidence_ledger import format_registered_sources_prompt

        sources_block = format_registered_sources_prompt(evidence_ledger)
        chat_system_prompt = assembled.chat_system_prompt
        if sources_block:
            chat_system_prompt = f"{chat_system_prompt}\n\n{sources_block}"

        # --- Phase 3: Execute ---
        sink.emit(message_start(message_id, conversation_id=conversation_id))

        from agentcore.runtime.captain_profile import apply_captain_max_rounds

        profile = apply_captain_max_rounds(profiles.get("chat"))
        turn_model = profiles.model_for("chat")

        record_turn_fact(
            TurnStartedFact(
                system_prompt=chat_system_prompt,
                user_message=user_message,
                model_profile=turn_model,
                history_len=len(history),
            ).to_fact()
        )

        # The CEO captain runs through the run executor as the turn's ROOT Run node
        # — the same react_loop assembly the workers use — instead of the pipeline
        # driving react_loop itself. It owns the reply voice (content/reasoning
        # stream to the chat bubble), runs the chat profile, holds the
        # read/retrieval tools + delegate, and writes the user-facing answer,
        # delegating mid-loop when a team is needed. When it delegates, its run id
        # is the graph's CAPTAIN 汇聚点 the workers hang under.
        captain_spec = RunSpec(
            run_id=captain_run_id,
            agent_id=captain_run_id,
            agent_name="CEO",
            kind=RunKind.CAPTAIN,
            task=user_message,
            role="CEO",
            depth=0,
            parent_run_id=None,
        )
        run_captain = build_captain_executor(
            llm=prepared.llm,
            tools=assembled.chat_tools,
            sink=sink,
            base_tool_context=prepared.base_tool_context,
            chat_system_prompt=chat_system_prompt,
            history=history,
            user_message=user_message,
            profile=profile,
            turn_model=turn_model,
            citation_sink=citations,
            approval_gate=assembled.approval_gate,
            supports_tools=llm_supports_tools,
            turn_evidence_ledger=evidence_ledger,
        )
        captain_state = await run_captain(captain_spec)

        if captain_failed(captain_state):
            return await salvage_failed_captain(
                message_id=message_id,
                captain_run_id=captain_run_id,
                captain_state=captain_state,
                vision_cost_sink=prepared.vision_cost_sink,
                sink=sink,
                audit_recorder=audit_recorder,
                roster_writer=roster_writer,
            )

        return await settle_successful_turn(
            message_id=message_id,
            captain_run_id=captain_run_id,
            captain_state=captain_state,
            delegate_tool=assembled.delegate_tool,
            debate_tool=assembled.debate_tool,
            profile=profile,
            citations=citations,
            vision_cost_sink=prepared.vision_cost_sink,
            sink=sink,
            fact_log=fact_log,
            audit_recorder=audit_recorder,
            roster_writer=roster_writer,
            journal_writer=journal_writer,
        )

    except Exception as e:
        return await salvage_pipeline_exception(
            e=e,
            message_id=message_id,
            sink=sink,
            fact_log=fact_log,
            audit_recorder=audit_recorder,
            roster_writer=roster_writer,
        )
    finally:
        # 触发点①：turn 结束防御性 orphan 未 settle 的热路交互
        with contextlib.suppress(Exception):
            from agentcore.runtime.interaction_orphan import orphan_registry_pending

            await orphan_registry_pending(conversation_id, turn_id=message_id)
        # 批 B 失效修订：收尾时未调 debate / 未起 MLR → pending stage_card 落 orphan 事实
        with contextlib.suppress(Exception):
            from agentcore.conversation.stage_card_resolve import (
                maybe_orphan_stage_cards_at_turn_end,
            )

            await maybe_orphan_stage_cards_at_turn_end(conversation_id, sink=sink)
        # 未消费的 MLR 预授权在 turn 出口显式丢弃（不依赖 ContextVar 消亡）。
        with contextlib.suppress(Exception):
            from agentcore.runtime.kickoff.stage_card import discard_mlr_preauth

            discard_mlr_preauth()
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
        turn_citations.reset(citations_token)
        consulted_memory_cache.reset(memory_cache_token)
        turn_evidence_ledger.reset(ledger_token)
        reset_turn_token_meter(turn_token_meter_token)
        reset_turn_auth_dead(turn_auth_dead_token)
        if execution_id_token is not None:
            from agentcore.runtime.coordination.session import (
                current_execution_id,
                release_turn_coordination,
            )

            # Prefer the live ContextVar (may have been switched to a host
            # execution_id by跨回合同图追加); also release the mint-at-prepare id
            # when it differs. Live background drives are preserved (async team
            # model) — only idle sessions are cleared.
            live_eid = current_execution_id.get() or bound_execution_id
            if live_eid:
                with contextlib.suppress(Exception):
                    release_turn_coordination(live_eid)
            if bound_execution_id and bound_execution_id != live_eid:
                with contextlib.suppress(Exception):
                    release_turn_coordination(bound_execution_id)
            current_execution_id.reset(execution_id_token)
        # Do NOT close the sink here. The pipeline is a *producer* on a sink it did not
        # create; closing it would silently drop the post-turn tail (title_generated /
        # followups_generated), which persist_turn_result emits AFTER this returns —
        # emit() is a no-op once closed (sink.py). The sink's OWNER (the coordinator that
        # created it: stream_chat / regenerate_chat / resume_chat / handoff / sidecar)
        # closes it, so the tail reaches the client. (Title survived the old early-close
        # via its DB write; transport-only followups vanished — the 「下一步推荐」 bug.)
        if llm is not None:
            with contextlib.suppress(Exception):
                await llm.close()

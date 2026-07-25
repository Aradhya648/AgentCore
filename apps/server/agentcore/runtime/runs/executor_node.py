"""Single AGENT-node execution (contract retries, escalate, notes, salvage)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import asdict, replace
from typing import Any

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.llm.pricing import calculate_cost
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.runtime.debate.speech_pipeline import research_then_draft
from agentcore.runtime.events import (
    FinishReason,
    escalation_raised,
    run_cancelled,
    run_completed,
    run_context,
    run_failed,
    run_started,
    team_note_posted,
)
from agentcore.runtime.facts import RunHeadFact, record_turn_fact
from agentcore.runtime.runs.constants import (
    AMEND_NOTE_TOOL_NAME,
    DEFAULT_CONTRACT_RETRIES,
    ESCALATE_TOOL_NAME,
    HANDOFF_TOOL_NAME,
    MAX_CONTRACT_RETRIES,
    MAX_DELEGATION_DEPTH,
    POST_NOTE_TOOL_NAME,
    READ_NOTES_TOOL_NAME,
)
from agentcore.runtime.runs.contract import (
    ContractVerdict,
    check_contract,
    debrief_meets_minimum,
    format_feedback,
    format_handoff_feedback,
    format_light_repair_feedback,
    is_format_repairable,
    needs_file_contents,
    node_has_dependents,
    synthesize_debrief,
)
from agentcore.runtime.runs.executor_context import (
    _build_messages,
    _context_block_payloads,
    _load_artifact_contents,
    _safe_index_files,
    ensure_design_md_for_web_quality,
    load_context_inject_files,
    load_web_seam_scope_contents,
)
from agentcore.runtime.runs.executor_env import AgentExecutorEnv
from agentcore.runtime.runs.executor_escalation import build_escalation_channel
from agentcore.runtime.runs.executor_identities import (
    _WORKER_TEAM_NOTE_POLICY,
    LeadSubteam,
    build_worker_identity,
)
from agentcore.runtime.runs.executor_shared import (
    _apply_cutoff_reasons,
    _apply_finish_interrupt,
    _delivery_gaps_from_warnings,
    _hard_gap_blocks_completion,
    _is_hard_failure,
    _priced_failure,
    _react_and_capture,
    _registry_with,
    _registry_without,
    _retry_message,
)
from agentcore.runtime.runs.notewall import NOTE_NUDGE_TEXT, format_notes_for_injection
from agentcore.runtime.runs.retrieval_budget import (
    RETRIEVAL_TOOL_NAMES,
    rework_refill_slots,
)
from agentcore.runtime.runs.salvage import cancelled_state_from_salvage, try_salvage_session
from agentcore.runtime.runs.serialize import (
    debrief_from_transcript,
    escalations_from_transcript,
    files_touched_from_transcript,
)
from agentcore.runtime.runs.types import ContextBlock, RunPhase, RunSpec, RunState
from agentcore.runtime.runs.website_visual_critic import (
    MAX_VISUAL_REWORK,
    apply_visual_critic_to_verdict,
    browser_tool_available,
    make_vision_bill,
    resolve_screenshot_port,
)
from agentcore.runtime.runs.worker_budget import DIRECTED_SEARCH_TOOL_NAMES
from agentcore.tools.protocol import RetrievalBudgetState

logger = get_logger(__name__)

# Light-repair allow-list: format backfill / handoff enrichment only — no re-investigation.
_LIGHT_REPAIR_TOOL_NAMES: frozenset[str] = frozenset(
    {
        HANDOFF_TOOL_NAME,
        "file_write",
        "file_append",
        "str_replace",
        "write_section",
        "file_read",
    }
)
_LIGHT_REPAIR_MAX_ROUNDS = 4


def _retry_token_budget(*, ceiling: int, spent: int) -> int:
    """Remaining token budget for a correction pass (总预算约束).

    ``ceiling <= 0`` means the hard ceiling is disabled (pass through 0).
    When already at/over the ceiling, return 1 so the next react_loop hits the
    hard top immediately（二次触顶立即收口）instead of resetting to a fresh ceiling.
    """
    if ceiling <= 0:
        return 0
    remaining = ceiling - spent
    if remaining <= 0:
        return 1
    return remaining


def _wind_down_entered(
    *,
    cutoff_reasons: list[str],
    token_ceiling: int,
    tokens_spent: int,
) -> bool:
    """True when this run already entered token/timeout wind_down (or past soft reserve)."""
    if "token_budget" in cutoff_reasons or "worker_timeout" in cutoff_reasons:
        return True
    if token_ceiling <= 0:
        return False
    from agentcore.runtime.runs.cutoff import (
        DEFAULT_TOKEN_WIND_DOWN_RESERVE,
        should_enter_token_wind_down,
    )

    reserve = int(
        settings.engine_worker_token_wind_down_reserve or DEFAULT_TOKEN_WIND_DOWN_RESERVE
    )
    return should_enter_token_wind_down(tokens_spent, token_ceiling, reserve)


def _narrow_for_light_repair(
    worker_tools: Any,
    allowed_tools: list[str] | None,
) -> tuple[Any, list[str]]:
    """Strip investigation tools for a format-only light repair pass."""
    withhold = tuple(
        sorted(
            RETRIEVAL_TOOL_NAMES
            | DIRECTED_SEARCH_TOOL_NAMES
            | frozenset({"file_list", "code_execute", "test_run", "terminal"})
        )
    )
    narrowed_registry = _registry_without(worker_tools, *withhold)
    if allowed_tools is None:
        # Unrestricted → explicit light-repair allow-list (intersect registry).
        present = {
            s.name
            for s in narrowed_registry.list_all()
            if s.name in _LIGHT_REPAIR_TOOL_NAMES
        }
        return narrowed_registry, sorted(present)
    narrowed_allowed = [t for t in allowed_tools if t in _LIGHT_REPAIR_TOOL_NAMES]
    if HANDOFF_TOOL_NAME not in narrowed_allowed:
        narrowed_allowed = [*narrowed_allowed, HANDOFF_TOOL_NAME]
    return narrowed_registry, narrowed_allowed


def _can_light_repair(
    *,
    verdict: ContractVerdict,
    handoff_ok: bool,
    light_repair_used: bool,
) -> bool:
    """Format / handoff-thin failures get one in-place light repair before full retry."""
    if light_repair_used:
        return False
    if verdict.ok and handoff_ok:
        return False
    return not (not verdict.ok and not is_format_repairable(verdict))


async def execute_agent_node(
    env: AgentExecutorEnv,
    spec: RunSpec,
    completed: Mapping[str, RunState],
    agent_id: str,
) -> RunState:
    env.sink.emit(
        run_started(
            spec.run_id,
            agent_id,
            parent_run_id=spec.parent_run_id,
            kind=spec.kind,
            replaces_run_id=spec.replaces_run_id,
        )
    )
    start = time.monotonic()
    deliverable = spec.deliverable
    # Hoisted out of the try so a hard exception can still bill what this run
    # already spent (B-deep 失败计费): ``run_usage``/``run_rounds`` accumulate the
    # completed contract-retry attempts, ``inflight`` mirrors the in-flight pass's
    # spend (filled by react_loop, read only if that pass raises), and
    # ``priced_model`` is the tier to price against once the profile resolves
    # (None before that → an early setup failure carries no usage to price).
    run_usage = TokenUsage()
    run_rounds = 0
    inflight: list[TokenUsage] = []
    priced_model: str | None = None
    # Hoisted so mid-flight CancelledError can salvage partial transcript (run_redirect 热续写).
    messages: list[LLMMessage] = []
    # Live draft chunks (run_output_delta) — may exist before the final assistant
    # turn is appended to ``messages``; folded into salvage on redirect cancel.
    streamed_content: list[str] = []
    # 阻塞式求决策: this worker's blocking-escalate resolutions, keyed by question, so the
    # transcript harvest below can fold the user's answer / timeout disposition into
    # ``RunState.escalations`` for CEO synthesis — driven by the structured channel below,
    # NOT by re-parsing the tool result prose (防补丁绊线, 设计 §4.7). A worker is
    # sequential, so escalates land here in call order, one at a time.
    resolutions: dict[str, dict[str, Any]] = {}
    # Escalation Gate (routing Phase 1): scheme-layer signals collected during react
    # rounds, merged into RunState.escalations alongside transcript-harvested escalate
    # tool calls.
    gate_escalations: list[dict[str, Any]] = []
    # 受监督子计划 B: a lead's nested-delegation handle (delegate + replan + dispose),
    # hoisted so the finally can fold a sub-plan the lead yielded-but-never-resumed back
    # into the ledger before the parent absorbs this child (堵漏账). Stays None for a leaf
    # worker (no opt-in / at the depth cap / no factory wired).
    lead_subteam: LeadSubteam | None = None
    try:
        profile = env.profiles.agent()
        from agentcore.runtime.costing import resolve_run_models

        priced_model, request_model = resolve_run_models(
            env.profiles, spec.model, cost_role=env.cost_role
        )
        tool_ctx = replace(
            env.base_tool_context,
            run_id=spec.run_id,
            agent_id=agent_id,
            execution_id=env.execution_id,
            write_coordinator=env.write_coordinator,
            write_ancestors=env.ancestors_by_id.get(spec.run_id, frozenset()),
            # 升级实时可见: give this worker's escalate tool a live channel back to the
            # run's SSE stream. The executor owns event shape (引擎纯化) — escalate just
            # hands it the (question, assumption, blocking) triple. run_id/agent_id are
            # bound here so the team UI attributes the escalation to the right node.
            on_escalate=lambda question, assumption, blocking, kind="normal", _rid=spec.run_id, _aid=agent_id: (  # noqa: E501
                env.sink.emit(
                    escalation_raised(
                        _rid,
                        _aid,
                        question=question,
                        assumption=assumption,
                        blocking=blocking,
                        kind=kind,
                    )
                )
            ),
            # 阻塞式求决策: the suspend-for-the-user channel for escalate(blocking=true).
            # None when no bridge (CEO / tests) → escalate stays non-blocking.
            escalation=build_escalation_channel(env, spec.run_id, agent_id, resolutions),
            # 团队便签墙 (§2.2 通): the batch wall this worker's post_note broadcasts onto,
            # its display role stamped on its notes (谁贴的), and a live emit so the
            # team-notes panel lights up the instant a note is pinned. The executor owns
            # event shape (引擎纯化) — post_note just hands it the TeamNote; run/agent come
            # off the note so the UI attributes it to the right sibling. The durable record
            # rides the journaled team_note_posted event emitted here.
            note_wall=env.note_wall,
            agent_role=spec.role or "",
            on_note=lambda note: env.sink.emit(
                team_note_posted(
                    execution_id=env.execution_id,
                    note_id=note.note_id,
                    run_id=note.run_id,
                    agent_id=note.agent_id,
                    role=note.role,
                    kind=note.kind,
                    text=note.text,
                    ts=note.ts,
                    # 改写/作废 (§2.2 supersession): an amendment note carries the target it
                    # 改写/作废s + the mode; a fresh post leaves both None (omitted from the
                    # payload). The same on_note path serves post_note AND amend_note.
                    supersedes=note.supersedes,
                    supersede_mode=note.supersede_mode,
                )
            ),
            # 检索预算 (提案 A1): per-run counter for tool_exec; None = no enforce.
            retrieval_budget=(
                RetrievalBudgetState(limit=spec.retrieval_budget)
                if spec.retrieval_budget is not None
                else None
            ),
            # Debate evidence posture: structured run signal → web_search filter.
            search_policy=spec.search_policy or "",
            # 成篇交接：有下游时禁止空 body handoff。
            handoff_requires_body=node_has_dependents(env.plan, spec.run_id),
        )
        # 阶段2 嵌套子任务: hand this worker delegation tools when opted in.
        worker_tools = env.tools
        # spec.tools is None for an unrestricted worker → react_loop offers all
        # team tools (the fail-safe default); a non-empty list restricts to those.
        allowed_tools = spec.tools
        # A worker may nest a sub-team purely by tree position: any depth below the
        # cap is a captain (delegation is on by default); depth-2 sub-workers are
        # leaves because the executor withholds the delegate tools here.
        is_captain = (
            env.delegate_factory is not None
            and spec.depth < MAX_DELEGATION_DEPTH
        )
        if is_captain:
            # The lead gets BOTH its own delegate AND the companion replan bound to
            # that delegate instance, so it supervises its sub-plan's 波边界
            # (bind_after_deps / 子队员 escalate scope) exactly like the CEO
            # (受监督子计划 B 去特例). Its turn-end dispose runs in the finally below.
            lead_subteam = env.delegate_factory(spec.run_id, spec.depth)
            worker_tools = _registry_with(env.tools, *lead_subteam.tools)
            # Unrestricted (None) stays None — the new tools now live in worker_tools,
            # so "offer all" already includes them. A restricted list must explicitly
            # gain their names (delegate + replan) to keep them callable.
            allowed_tools = (
                None if spec.tools is None else [*spec.tools, *lead_subteam.tool_names]
            )
        # Topology-split handoff wording + deliverable.form: DAG is known at identity
        # build — upstream nodes get imperative「必须 handoff」; leaves get conditional
        # 「有增量才写」. form=prose/files selects the landing block (omit = legacy).
        # requires_files / artifacts with form omitted → files block (not「可当文字」).
        deliverable_form = deliverable.form if deliverable is not None else None
        identity = build_worker_identity(
            has_dependents=node_has_dependents(env.plan, spec.run_id),
            captain=is_captain,
            form=deliverable_form,
            requires_files=bool(deliverable.requires_files) if deliverable else False,
            artifacts=list(deliverable.artifacts) if deliverable else None,
            # 能写≠能跑 (能力闸门与交付诚实性): the registry is the capability truth —
            # execution class absent (cloud without sandbox) ⇒ the identity says so,
            # instead of the generic wording implying the worker can run code.
            can_execute=env.tools.get_optional("code_execute") is not None,
        )
        if not env.collaboration:
            identity = identity.replace(_WORKER_TEAM_NOTE_POLICY, "").replace("\n\n\n", "\n\n")
        # form=prose: withhold write tools (hard constraint — not just prompt).
        if deliverable_form == "prose":
            from agentcore.runtime.runs.executor_identities import (
                PROSE_WITHHELD_WRITE_TOOLS,
            )

            worker_tools = _registry_without(
                worker_tools, *PROSE_WITHHELD_WRITE_TOOLS
            )
            if allowed_tools is not None:
                withheld = set(PROSE_WITHHELD_WRITE_TOOLS)
                allowed_tools = [t for t in allowed_tools if t not in withheld]
        # 检索预算 0 (提案 A1): strip web_search/read_url even for unrestricted workers
        # (builder already tightens tasks[].tools when valid_tools is known).
        if spec.retrieval_budget == 0:
            worker_tools = _registry_without(worker_tools, *RETRIEVAL_TOOL_NAMES)
            if allowed_tools is not None:
                allowed_tools = [t for t in allowed_tools if t not in RETRIEVAL_TOOL_NAMES]
        # 非协作批次 (env.collaboration=False, e.g. debate): strip the 团队便签 tools from the
        # offered registry so even an UNRESTRICTED worker (allowed_tools=None → "offer all
        # team tools") is never handed post/read/amend — "no env.collaboration" means no channel
        # at all, not "no channel only for a least-privilege worker". Restricted workers are
        # covered by skipping the grants below; this closes the unrestricted path too.
        if not env.collaboration:
            worker_tools = _registry_without(
                worker_tools,
                POST_NOTE_TOOL_NAME,
                READ_NOTES_TOOL_NAME,
                AMEND_NOTE_TOOL_NAME,
            )
        # escalate is a worker's always-available upward channel — a safety primitive,
        # not a capability the CEO restricts away. An unrestricted worker (None) is
        # already offered it; a least-privilege worker (non-empty allow-list) must
        # keep it explicitly, so it can still flag a blocker instead of guessing.
        if allowed_tools is not None and ESCALATE_TOOL_NAME not in allowed_tools:
            allowed_tools = [*allowed_tools, ESCALATE_TOOL_NAME]
        # 团队便签三件套 (post/read/amend_note) 仅协作批次授予 (便签墙 broadcast, §2.2 通): a
        # collaborating team keeps them always-available even for a least-privilege worker so
        # siblings align mid-flight; a non-collaborative batch (env.collaboration=False, e.g.
        # debate) skips them entirely — they are also stripped from worker_tools above, so an
        # unrestricted worker in such a batch isn't offered them either (opponents get no
        # 便签 channel).
        if env.collaboration:
            if allowed_tools is not None and POST_NOTE_TOOL_NAME not in allowed_tools:
                allowed_tools = [*allowed_tools, POST_NOTE_TOOL_NAME]
            # read_notes is post_note's pull dual (§2.4 变·worker 的「拉」): even a
            # least-privilege worker can look up what a sibling already decided.
            if allowed_tools is not None and READ_NOTES_TOOL_NAME not in allowed_tools:
                allowed_tools = [*allowed_tools, READ_NOTES_TOOL_NAME]
            # amend_note completes the trio (便签会过期 → 改写/作废, §2.2 supersession): a
            # worker must be able to correct its OWN stale note so a sibling never builds on
            # a dead decision.
            if allowed_tools is not None and AMEND_NOTE_TOOL_NAME not in allowed_tools:
                allowed_tools = [*allowed_tools, AMEND_NOTE_TOOL_NAME]
        from agentcore.runtime.audit.hooks import on_permission_effective

        on_permission_effective(
            execution_id=env.execution_id,
            run_id=spec.run_id,
            parent_run_id=spec.parent_run_id,
            declared_tools=None if spec.tools is None else list(spec.tools),
            effective_tools=None if allowed_tools is None else list(allowed_tools),
            depth=spec.depth,
        )
        # Produce → check contract → re-prompt with the specific shortfalls.
        # This content-quality retry is intentionally separate from the
        # scheduler's infra-failure retry (RunPolicy.on_failure): they answer
        # different questions and must not be conflated.
        content = ""
        # Keep the last non-empty prose across contract retries. A handoff-gate
        # correction often only calls ``handoff`` (empty streamed content); without
        # retention the prior ~合格正文 is wiped and check_contract mis-fires「产出为空」.
        retained_content = ""
        # The worker's full thinking from the LAST attempt (parallel to
        # ``content``, which each attempt overwrites): carried onto the terminal
        # RunState → its ``message_final`` fact so resume / reload rebuild the
        # worker's 思考全文 from the journal, not from the (being-retired)
        # ``run_reasoning_delta`` stream (执行级事件溯源: deltas 退场).
        reasoning = ""
        verdict = ContractVerdict(ok=True)
        # Web sources this worker consults, de-duped across contract retries.
        # Pool merge still collect-only into this list → DelegateTool → turn card.
        # Stable ``#rN`` annotation (when ``env.turn_evidence_ledger`` is set) is
        # separate — not the old ``[n]`` annotate path (引用即出处 P1).
        worker_citations: list[dict] = []
        ledger_registrant = f"worker:{agent_id}"
        # Pre-existing workspace files (uploads / prior turns) for the worker's
        # opening manifest — a per-turn snapshot walked once and shared by the whole
        # batch (see ``env.preexisting_files``); peer products are layered on per worker
        # from the completion map inside ``_build_messages``.
        index_paths = await env.preexisting_files()
        # Wave3 B: force-inject skeleton/contract summaries before first file_read.
        context_inject = await load_context_inject_files(
            env.base_tool_context.backend,
            list(getattr(spec, "context_inject_files", None) or []),
        )
        # Build the worker's opening (system + task) ONCE; auto-rework then
        # CONTINUES on this SAME transcript (append the shortfall, re-run)
        # instead of rebuilding from scratch — so the worker sees its own prior
        # draft when correcting (修隐患), and the finished transcript is captured
        # as a recoverable RunSession for 定向唤回 (统一「续写」原语, 见 §三).
        # received_blocks captures the SAME ContextBlocks the opening was rendered
        # from (单一源), so the run_context event ships exactly what the LLM was fed.
        received_blocks: list[ContextBlock] = []
        messages[:] = _build_messages(
            env.plan,
            spec,
            completed,
            env.system_prompt,
            env.user_message,
            deliverable,
            identity=identity,
            index_paths=index_paths,
            blocks_sink=received_blocks,
            team_brief=env.team_brief,
            shared_workspace=env.shared_workspace,
            batch_completion_criteria=env.batch_completion_criteria,
            context_inject=context_inject or None,
        )
        # Worker window head (§8.3): journal the opening task-prompt so
        # ``window_from_journal(run_id=…)`` anchors on THIS run's system+user, not the
        # turn-level CEO ``turn_started``. ``user_origin=context_blocks`` marks the
        # opening user as the ContextBlock join (diagnostic UI replaces it with the
        # structured ``run_context`` segments).
        record_turn_fact(
            RunHeadFact(
                run_id=spec.run_id,
                system_prompt=messages[0].content or "",
                user_message=messages[1].content or "",
                user_origin="context_blocks",
            ).to_fact()
        )
        # 上下文传递可视化: emit the received context right after assembly (before the
        # LLM react loop) so the frontend's run detail lights up its「收到的上下文」as
        # soon as the worker starts thinking. Bodies capped + journaled (see run_context).
        env.sink.emit(run_context(spec.run_id, agent_id, _context_block_payloads(received_blocks)))

        # Worker 累计 token 硬顶 (loose backstop · 真执行): compaction (tool_clear)
        # 挑大梁做上下文瘦身,这只在失控时收口。≤0 = 关闭。
        # react_loop 每轮末比对累计 usage。CEO / solo 路径不经此分支,保持 0。
        # 辩论辩手两阶段检索与普通 worker 共用 ``engine_worker_token_ceiling``：
        # 优先 ``spec.token_ceiling``（派单统一 backstop）；未解析则回落全局默认。
        # 全局 ``engine_worker_token_ceiling≤0`` 仍表示关闭硬顶（已回填的 spec 值亦忽略）。
        if settings.engine_worker_token_ceiling <= 0:
            token_ceiling = 0
        elif spec.token_ceiling is not None and spec.token_ceiling > 0:
            token_ceiling = spec.token_ceiling
        else:
            token_ceiling = settings.engine_worker_token_ceiling

        # 团队便签墙 推增量 (§2.2 通): pull the notes siblings posted since this worker last
        # looked and hand them to react_loop as one user message before each of its NEXT
        # steps — so it builds on the team's evolving decisions / heads-ups, not a snapshot
        # frozen at its opening. new_for already excludes self-posted, caps the burst, and
        # advances this run's cursor (each note delivered at most once). Empty (solo / no
        # fresh notes) → [] → a no-op round, identical to today's behaviour.
        _note_nudged: list[bool] = [False]

        def _pull_notes(_rid: str = spec.run_id) -> list[LLMMessage]:
            if env.note_wall is None:  # non-collaborative batch: no wall to push
                return []
            injected: list[LLMMessage] = []
            fresh = env.note_wall.new_for(_rid)
            if fresh:
                injected.append(
                    LLMMessage(role="user", content=format_notes_for_injection(fresh))
                )
            if (
                not _note_nudged[0]
                and not env.note_wall.own_active(_rid)
                and len(env.note_wall.all_for(_rid)) >= 2
            ):
                _note_nudged[0] = True
                injected.append(LLMMessage(role="user", content=NOTE_NUDGE_TEXT))
            return injected

        attempts = 1 + min(DEFAULT_CONTRACT_RETRIES, MAX_CONTRACT_RETRIES)
        if deliverable and deliverable.visual_critic:
            # P1c: up to 2 visual rework rounds on top of the initial pass.
            attempts = 1 + min(
                max(DEFAULT_CONTRACT_RETRIES, MAX_VISUAL_REWORK),
                MAX_CONTRACT_RETRIES,
            )
        # Accepted react pass's finish override (cleared each attempt so a clean
        # rework after an interrupted first pass does not keep the interrupt warning).
        finish_override: list[FinishReason] = []
        # C·掐断透明化：正轨 token 撞顶等结构化原因码（与 DEGRADED 分流正交）。
        cutoff_reasons: list[str] = []
        # Last accepted react pass's tool-failure facts (circuit-breaker tally).
        tool_failures: list[dict] = []
        # Format-only / handoff-thin: one in-place light repair before full contract.retry.
        light_repair_used = False
        light_mode = False
        visual_rework_used = 0
        attempt = 0
        while attempt < attempts:
            streamed_content.clear()
            finish_override.clear()
            cutoff_reasons.clear()
            tool_failures.clear()
            pass_token_budget = _retry_token_budget(
                ceiling=token_ceiling, spent=run_usage.total_tokens
            )
            pass_profile = profile
            pass_tools = worker_tools
            pass_allowed = allowed_tools
            if light_mode:
                # 不重置 rounds：扣减已消耗轮次；工具面收窄，禁止重新调查。
                remaining_rounds = max(1, profile.max_rounds - run_rounds)
                pass_profile = replace(
                    profile,
                    max_rounds=min(_LIGHT_REPAIR_MAX_ROUNDS, remaining_rounds),
                )
                pass_tools, pass_allowed = _narrow_for_light_repair(
                    worker_tools, allowed_tools
                )
                light_mode = False
            use_rtd = (
                attempt == 0
                and not light_repair_used
                and spec.research_then_draft
                and (spec.draft_brief or "").strip()
            )
            if use_rtd:
                content, reasoning, round_usage, round_rounds = await research_then_draft(
                    messages,
                    llm=env.llm,
                    tools=pass_tools,
                    sink=env.sink,
                    tool_ctx=tool_ctx,
                    profile=pass_profile,
                    turn_model=request_model,
                    allowed_tools=pass_allowed,
                    run_id=spec.run_id,
                    agent_id=agent_id,
                    citation_sink=worker_citations,
                    approval_gate=env.approval_gate,
                    draft_system=spec.draft_system or (spec.system_prompt_supplement or ""),
                    draft_brief=spec.draft_brief,
                    allow_research=True,
                    evidence_ledger=env.evidence_ledger,
                    side_key=spec.side_key,
                    check_evidence_ledger=spec.evidence_ledger_check,
                    usage_sink=inflight,
                    on_round_begin=_pull_notes,
                    streamed_content=streamed_content,
                    gate_escalation_sink=gate_escalations,
                    token_budget=pass_token_budget,
                    finish_override_sink=finish_override,
                    cutoff_reason_sink=cutoff_reasons,
                )
            else:
                content, reasoning, round_usage, round_rounds = await _react_and_capture(
                    messages,
                    llm=env.llm,
                    tools=pass_tools,
                    sink=env.sink,
                    tool_ctx=tool_ctx,
                    profile=pass_profile,
                    turn_model=request_model,
                    allowed_tools=pass_allowed,
                    run_id=spec.run_id,
                    agent_id=agent_id,
                    citation_sink=worker_citations,
                    turn_evidence_ledger=env.turn_evidence_ledger,
                    ledger_registrant=ledger_registrant,
                    approval_gate=env.approval_gate,
                    usage_sink=inflight,
                    on_round_begin=_pull_notes,
                    streamed_content=streamed_content,
                    gate_escalation_sink=gate_escalations,
                    token_budget=pass_token_budget,
                    finish_override_sink=finish_override,
                    cutoff_reason_sink=cutoff_reasons,
                    tool_failure_sink=tool_failures,
                )
            run_usage = run_usage + round_usage
            run_rounds += round_rounds
            # This pass's usage is now folded into run_usage via its return value;
            # drop the mirror so a later non-react raise can't double-count it.
            inflight.clear()
            # Handoff-only / tool-only correction passes often stream no prose —
            # keep the prior non-empty body so contract checks and the terminal
            # RunState still see the already-qualified product.
            if (content or "").strip():
                retained_content = content
            elif retained_content:
                content = retained_content
            # files_written backs the contract's requires_files gate; workspace_paths
            # reconciles declarative artifacts against the live workspace (+ this
            # run's own writes). Handoff gate: nodes with downstream dependents must
            # submit a minimum-quality brief (one correction shot, then degraded synth).
            touched_now = files_touched_from_transcript(messages)
            debrief_now = debrief_from_transcript(messages)
            # Re-index the live workspace only when reconciling declarative
            # artifacts — otherwise keep the once-per-turn opening snapshot
            # (peer/preexisting manifest) and this run's own writes.
            # 交付形态对齐: for a FILE deliverable, load the landed files' text so the
            # contract's content checks (length / keyword / section) read the product on
            # disk, not just chat prose — artifacts declared → matching paths; else this
            # run's own writes. Also loads when this run's writes are a web batch
            # (HTML+CSS/JS) so the seam gate can cross-check selectors. ``needs_file_contents``
            # skips the read for prose / existence-only non-web deliverables.
            artifact_contents: dict[str, str] | None = None
            load_contents = needs_file_contents(deliverable, landed_paths=touched_now)
            if deliverable and deliverable.artifacts:
                live_index = await _safe_index_files(tool_ctx.backend)
                workspace_paths = list(dict.fromkeys([*live_index, *touched_now]))
                if load_contents:
                    patterns = list(
                        dict.fromkeys([*deliverable.artifacts, *touched_now])
                    )
                    artifact_contents = await _load_artifact_contents(
                        tool_ctx.backend,
                        patterns,
                        workspace_paths,
                    )
            else:
                workspace_paths = list(touched_now)
                if touched_now and load_contents:
                    artifact_contents = await _load_artifact_contents(
                        tool_ctx.backend,
                        touched_now,
                        workspace_paths,
                    )
            if deliverable and deliverable.web_seam_scope:
                artifact_contents = await load_web_seam_scope_contents(
                    tool_ctx.backend,
                    deliverable.web_seam_scope,
                    workspace_paths or [],
                    artifact_contents or {},
                )
            if deliverable and deliverable.web_quality_scan:
                artifact_contents = await ensure_design_md_for_web_quality(
                    tool_ctx.backend,
                    artifact_contents,
                    web_quality_scan=True,
                )
            verdict = check_contract(
                content,
                deliverable,
                files_written=len(touched_now),
                debrief=debrief_now,
                workspace_paths=workspace_paths,
                artifact_contents=artifact_contents,
            )
            # P1c visual critic: only after web_quality / contract **hard** gates pass.
            if (
                deliverable
                and deliverable.visual_critic
                and not verdict.failures
            ):
                shot_port = resolve_screenshot_port(
                    conversation_id=tool_ctx.conversation_id or "",
                    browser_tool_available=browser_tool_available(worker_tools),
                )

                async def _persist_visual(path: str, text: str) -> None:
                    try:
                        await tool_ctx.backend.write(path, text)
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "website.visual_critic_artifact_write_failed",
                            path=path,
                            exc_info=True,
                        )

                verdict, visual_result, visual_rework_used = await apply_visual_critic_to_verdict(
                    verdict,
                    vision_reader=tool_ctx.vision_reader,
                    screenshot=shot_port,
                    artifact_contents=artifact_contents or {},
                    visual_rework_used=visual_rework_used,
                    bill=make_vision_bill(
                        cost_sink=tool_ctx.cost_sink,
                        parent_run_id=spec.run_id,
                    ),
                    persist_artifact=_persist_visual,
                )
                if visual_result.critical_findings and verdict.visual_failures:
                    logger.info(
                        "contract.visual_critic_findings",
                        run_id=spec.run_id,
                        round=visual_rework_used,
                        count=len(visual_result.critical_findings),
                    )
            # Handoff gate only forces a correction shot when the tool is actually
            # offered (production worker registry). Empty-registry unit tests still
            # get a degraded synth below without burning an extra LLM round.
            needs_handoff = node_has_dependents(env.plan, spec.run_id)
            handoff_offered = worker_tools.get_optional(HANDOFF_TOOL_NAME) is not None
            handoff_ok = (
                (not needs_handoff)
                or debrief_meets_minimum(debrief_now)
                or not handoff_offered
            )
            if (verdict.ok and handoff_ok) or attempt == attempts - 1:
                break
            # 二次触顶：已达硬顶则不再开 correction pass（立即收口）。
            if token_ceiling > 0 and run_usage.total_tokens >= token_ceiling:
                logger.info(
                    "contract.retry_skipped_budget",
                    run_id=spec.run_id,
                    tokens=run_usage.total_tokens,
                    ceiling=token_ceiling,
                )
                break
            checked_files = (
                list(artifact_contents.keys()) if artifact_contents else None
            )
            if _can_light_repair(
                verdict=verdict,
                handoff_ok=handoff_ok,
                light_repair_used=light_repair_used,
            ):
                light_repair_used = True
                light_mode = True
                parts: list[str] = []
                if not verdict.ok:
                    parts.append(
                        format_light_repair_feedback(
                            verdict,
                            prior_content=content,
                            checked_files=checked_files,
                        )
                    )
                if needs_handoff and handoff_offered and not debrief_meets_minimum(
                    debrief_now
                ):
                    parts.append(
                        format_handoff_feedback(present_but_thin=debrief_now is not None)
                    )
                messages.append(_retry_message("\n\n".join(p for p in parts if p)))
                logger.info(
                    "contract.light_repair",
                    run_id=spec.run_id,
                    failures=verdict.failures,
                    handoff_ok=handoff_ok,
                    tokens_spent=run_usage.total_tokens,
                    rounds_spent=run_rounds,
                )
                continue
            parts = []
            if not verdict.ok:
                parts.append(format_feedback(verdict, checked_files=checked_files))
                if verdict.visual_failures:
                    parts.append(
                        f"视觉 critic 第 {max(1, visual_rework_used)}/{MAX_VISUAL_REWORK} 轮回炉："
                        "请用 str_replace / file_append **定向修补** site/ 下既有文件，"
                        "禁止整站重写；修完更新 site/QA.md 与 site/VISUAL_CRITIC.json。"
                    )
            if needs_handoff and handoff_offered and not debrief_meets_minimum(debrief_now):
                parts.append(
                    format_handoff_feedback(present_but_thin=debrief_now is not None)
                )
            messages.append(_retry_message("\n\n".join(p for p in parts if p)))
            # Full contract.retry: refill only within original retrieval cap, and
            # never after wind_down（不得恢复全量检索）.
            rb = tool_ctx.retrieval_budget
            original_rb = int(spec.retrieval_budget or (rb.limit if rb else 0) or 0)
            wind_down = _wind_down_entered(
                cutoff_reasons=cutoff_reasons,
                token_ceiling=token_ceiling,
                tokens_spent=run_usage.total_tokens,
            )
            slice_n = rework_refill_slots(
                original_limit=original_rb, wind_down_entered=wind_down
            )
            if rb is not None and slice_n > 0:
                new_remaining = await rb.refill_within_cap(slice_n, cap=original_rb)
                logger.info(
                    "retrieval_budget.rework_refill",
                    run_id=spec.run_id,
                    added=slice_n,
                    remaining=new_remaining,
                    limit=rb.limit,
                    cap=original_rb,
                    wind_down=wind_down,
                )
            elif wind_down:
                logger.info(
                    "retrieval_budget.rework_refill_skipped",
                    run_id=spec.run_id,
                    reason="wind_down",
                    original_limit=original_rb,
                )
            logger.info(
                "contract.retry",
                run_id=spec.run_id,
                attempt=attempt + 1,
                failures=verdict.failures,
                handoff_ok=handoff_ok,
            )
            attempt += 1

        duration_ms = int((time.monotonic() - start) * 1000)
        # Price this run once (the only place a worker's cost is computed),
        # carried on the state so the per-run ledger and UI payroll read it
        # without re-pricing. Cost is recorded even on FAILED so a stopped
        # run still shows what it已花费.
        usage = run_usage.as_dict()
        cost = asdict(calculate_cost(priced_model, run_usage))
        # Upward escalations this worker raised (escalate tool calls), harvested
        # once from the transcript and carried on BOTH terminal states — a worker
        # that flags a blocker then fails its contract should still surface that
        # blocker to the CEO. 阻塞式求决策: fold each blocking escalate's resolution
        # (answer / timeout) in by question, so CEO synthesis knows which were already
        # settled with the user and must not be re-asked (设计 §4.5/§4.7).
        escalations = escalations_from_transcript(messages)
        for esc in escalations:
            settled = resolutions.get(esc.get("question", ""))
            if settled is not None:
                esc["status"] = settled["status"]
                esc["answer"] = settled["answer"]
        # Merge Escalation Gate scheme-layer signals (dedupe by question).
        seen_questions = {e.get("question", "") for e in escalations}
        for gate_esc in gate_escalations:
            q = gate_esc.get("question", "")
            if q and q not in seen_questions:
                escalations.append(gate_esc)
                seen_questions.add(q)
        # 完工交接简报: harvest the worker's structured brief from its ``handoff`` tool call
        # (best-effort; None when it finished without one) so downstream dep injection / CEO
        # synthesis read the author's own 结论 + 建议下一步 instead of re-deriving them from
        # prose. Carried on BOTH terminal states (a worker that failed its contract can still
        # have submitted a useful brief before failing). Nodes with downstream dependents
        # that still lack a minimum-quality brief get an engine-synthesized degraded debrief.
        debrief = debrief_from_transcript(messages)
        touched = files_touched_from_transcript(messages)
        author_brief = debrief
        if node_has_dependents(env.plan, spec.run_id) and not debrief_meets_minimum(debrief):
            debrief = synthesize_debrief(content, touched)
            logger.info(
                "handoff.degraded_synth",
                run_id=spec.run_id,
                had_author_brief=author_brief is not None,
            )
        # Soft web-quality (anti-slop): at most one rework (already spent in the loop).
        # Remaining soft-only hits demote to warnings — never hard-fail the run.
        # P1c visual critic: remaining visual_failures after max reworks → partial.
        if (verdict.soft_failures or verdict.visual_failures) and not verdict.failures:
            if verdict.soft_failures:
                logger.info(
                    "contract.web_quality_soft_accept",
                    run_id=spec.run_id,
                    soft_failures=verdict.soft_failures,
                )
            if verdict.visual_failures:
                logger.info(
                    "contract.visual_critic_partial",
                    run_id=spec.run_id,
                    visual_failures=verdict.visual_failures,
                    rework_used=visual_rework_used,
                )
            verdict = ContractVerdict(
                ok=True,
                failures=[],
                warnings=[
                    *verdict.warnings,
                    *verdict.soft_failures,
                    *verdict.visual_failures,
                ],
                soft_failures=[],
                visual_failures=[],
            )
        if not verdict.ok and _is_hard_failure(content, deliverable):
            reason = "；".join(verdict.failures)
            logger.info("contract.failed", run_id=spec.run_id, failures=verdict.failures)
            # A contract miss still produced a deliverable + (often) a 交接简报: surface it so
            # the run-detail shows the author's wrap-up beside the failure (the infra-failure
            # except path below has no reliable content, so it carries none).
            env.sink.emit(run_failed(spec.run_id, agent_id, reason, debrief=debrief))
            # Contract retries already exhausted inside this executor; mark
            # non-retryable so WaveScheduler's on_failure=retry does not cold-
            # start the whole node (same tokens, same empty/short product).
            return RunState(
                phase=RunPhase.FAILED,
                content=content,
                reasoning=reasoning,
                error=reason,
                error_retryable=False,
                escalations=escalations,
                debrief=debrief,
                citations=worker_citations,
                model=priced_model,
                duration_ms=duration_ms,
                rounds=run_rounds,
                tool_failures=list(tool_failures),
                usage=usage,
                cost=cost,
                transcript=messages,
                received_context=received_blocks,
            )
        # Soft-accept / clean complete: still surface an interrupted LLM finish so CEO
        # synthesis sees the gap (files may be on disk but handoff missing/thin).
        warnings = [] if verdict.ok else [
            *verdict.failures,
            *verdict.soft_failures,
            *verdict.visual_failures,
        ]
        if verdict.ok and verdict.warnings:
            # Soft-accept demotion / placeholder soft notes already on the verdict.
            warnings = list(verdict.warnings)
        elif verdict.warnings:
            warnings = [*warnings, *verdict.warnings]
        warnings, debrief = _apply_finish_interrupt(
            finish_override,
            warnings=warnings,
            debrief=debrief,
            content=content,
            files_touched=touched,
            run_id=spec.run_id,
        )
        warnings = _apply_cutoff_reasons(cutoff_reasons, warnings=warnings)
        delivery_gaps = _delivery_gaps_from_warnings(warnings, debrief)
        # 成篇质量：有下游 + 空正文且无落盘 → 失败，避免写作节点吃空壳上游。
        from agentcore.runtime.runs.research_quality import MIN_UPSTREAM_BODY_CHARS

        if (
            node_has_dependents(env.plan, spec.run_id)
            and len((content or "").strip()) < MIN_UPSTREAM_BODY_CHARS
            and not touched
        ):
            reason = (
                f"空交付不得进入下游：正文不足 {MIN_UPSTREAM_BODY_CHARS} 字且无落盘文件"
            )
            logger.info(
                "handoff.empty_body_blocked",
                run_id=spec.run_id,
                body_chars=len((content or "").strip()),
            )
            env.sink.emit(run_failed(spec.run_id, agent_id, reason, debrief=debrief))
            return RunState(
                phase=RunPhase.FAILED,
                content=content,
                reasoning=reasoning,
                error=reason,
                error_retryable=False,
                escalations=escalations,
                debrief=debrief,
                citations=worker_citations,
                model=priced_model,
                duration_ms=duration_ms,
                rounds=run_rounds,
                tool_failures=list(tool_failures),
                usage=usage,
                cost=cost,
                transcript=messages,
                received_context=received_blocks,
            )
        # Wave3 C: strict deliverables with hard gaps / degraded_handoff must not
        # silently COMPLETE — fail so CEO takes continue_from / replan (not wrap-up).
        hard_gap_reason = _hard_gap_blocks_completion(
            delivery_gaps, debrief, deliverable
        )
        if hard_gap_reason:
            logger.info(
                "contract.hard_gap_blocked_completion",
                run_id=spec.run_id,
                reason=hard_gap_reason,
                gaps=delivery_gaps,
            )
            env.sink.emit(
                run_failed(spec.run_id, agent_id, hard_gap_reason, debrief=debrief)
            )
            return RunState(
                phase=RunPhase.FAILED,
                content=content,
                reasoning=reasoning,
                error=hard_gap_reason,
                error_retryable=False,
                warnings=warnings,
                delivery_gaps=delivery_gaps,
                escalations=escalations,
                debrief=debrief,
                citations=worker_citations,
                model=priced_model,
                duration_ms=duration_ms,
                rounds=run_rounds,
                files_touched=touched,
                tool_failures=list(tool_failures),
                usage=usage,
                cost=cost,
                transcript=messages,
                received_context=received_blocks,
            )
        # The worker's terminal RunState is journaled at the ``execute`` choke point
        # below (run_final_fact — covers COMPLETED *and* FAILED in one place), so resume
        # re-seeds it from facts not the旁路 frame (执行级事件溯源 Phase 2 ⑥).
        env.sink.emit(
            run_completed(
                spec.run_id,
                agent_id,
                # 交接简报单一源: the summary IS the worker's authored 结论 (best-effort "" when
                # it wrote none — the full deliverable is persisted + shown either way), never a
                # truncation; the structured debrief rides alongside for the run-detail card.
                output_summary=(debrief or {}).get("summary", ""),
                duration_ms=duration_ms,
                # 阶段1 scheduled runs are all delegated workers → member row;
                # the already-priced usage/cost light up the payroll live.
                role="member",
                model=priced_model,
                usage=usage,
                cost=cost,
                debrief=debrief,
                output_files=touched or None,
                gaps=delivery_gaps or None,
            )
        )
        return RunState(
            phase=RunPhase.COMPLETED,
            content=content,
            reasoning=reasoning,
            warnings=warnings,
            delivery_gaps=delivery_gaps,
            escalations=escalations,
            debrief=debrief,
            citations=worker_citations,
            model=priced_model,
            duration_ms=duration_ms,
            rounds=run_rounds,
            files_touched=touched,
            tool_failures=list(tool_failures),
            usage=usage,
            cost=cost,
            transcript=messages,
            received_context=received_blocks,
        )
    except asyncio.CancelledError as e:
        # Dual cancel semantics: redirect = salvage + return CANCELLED (wave absorbs);
        # stop (整轮) = emit run_cancelled then re-raise so the turn abort propagates.
        cancel_reason = (
            "redirect"
            if e.args and str(e.args[0]) == "redirect"
            else "stop"
        )
        env.sink.emit(
            run_cancelled(spec.run_id, agent_id, reason=cancel_reason)
        )
        if cancel_reason == "redirect":
            # Fold live streamed draft into messages when the ReAct pass was cut
            # before the final assistant turn was appended (用户已看见的一半产出).
            draft = "".join(streamed_content).strip()
            salvage_msgs = list(messages)
            if draft and not any(m.role in ("assistant", "tool") for m in salvage_msgs):
                salvage_msgs.append(LLMMessage(role="assistant", content=draft))
            session = try_salvage_session(spec=spec, messages=salvage_msgs)
            logger.info(
                "run.redirect_cancelled",
                run_id=spec.run_id,
                salvage=session is not None,
                transcript_len=len(session.transcript) if session else 0,
                streamed_chars=len(draft),
            )
            return cancelled_state_from_salvage(session, error="redirected")
        raise
    except Exception as e:  # noqa: BLE001 — surface any run failure to UI/state
        duration_ms = int((time.monotonic() - start) * 1000)
        # Bill the rounds that completed before the failure: finished attempts are
        # already in run_usage; an in-flight pass that raised left its spend in
        # ``inflight`` (B-deep 失败计费).
        if inflight:
            run_usage = run_usage + inflight[0]
        # 确定性失败区分 (BL-6): a non-retryable upstream error (prompt 超长 / 400 /
        # 鉴权 / 余额 — AgentCoreError.retryable=False) will re-fail identically, so
        # carry that verdict onto the state and let the scheduler skip its infra retry.
        # Closed httpx client (turn teardown race) is also deterministic — retrying
        # the same closed client just multiplies llm.call_failed / run.failed.
        # A plain crash / unknown exception has no ``retryable`` attr → defaults True
        # (retry as before), so only KNOWN-deterministic failures opt out.
        from agentcore.core.errors import LLMClientClosedError, is_llm_client_closed_error

        if is_llm_client_closed_error(e) and not isinstance(e, LLMClientClosedError):
            e = LLMClientClosedError(str(e))
        retryable = bool(getattr(e, "retryable", True))
        logger.error(
            "run.failed",
            run_id=spec.run_id,
            error=str(e),
            retryable=retryable,
            exc_info=True,
        )
        env.sink.emit(run_failed(spec.run_id, agent_id, str(e)))
        return _priced_failure(
            str(e),
            model=priced_model,
            usage=run_usage,
            rounds=run_rounds,
            duration_ms=duration_ms,
            retryable=retryable,
        )
    finally:
        # 堵漏账: if this lead opened a sub-plan at a 波边界 but its react loop ended
        # without a final replan (answered directly / hit MAX_ROUNDS / raised), the held
        # sub-team spend still sits in the child delegate's _supervised. Fold it in now —
        # BEFORE the parent drive's absorb_children merges this child's ledger — so no
        # sub-team usage is stranded unbilled. No-op when nothing is paused; best-effort,
        # and in a finally so it runs on the success, MAX_ROUNDS, and exception paths alike.
        if lead_subteam is not None:
            await lead_subteam.dispose()

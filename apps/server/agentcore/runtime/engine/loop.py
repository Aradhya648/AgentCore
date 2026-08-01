"""ReAct main loop: turn control, LLM rounds, tool execution, governance."""

import time
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agentcore.core.error_codes import ErrorCode
from agentcore.core.logging import get_logger
from agentcore.llm.profiles import ProfileParams, get_profile
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    content_delta,
    content_reset,
    reasoning_delta,
    tool_use_end,
    tool_use_start,
)
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.loop_controller import LoopController
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry

from .ceiling import ceiling_finalize
from .directive import LoopDirective
from .directive_apply import apply_loop_directive
from .governance import (
    classify_investigation_tools,
    coordination_injection_has_all_completed,
    create_loop_controller,
    decide_llm_failure,
    maybe_inject_audit_gate,
    maybe_inject_availability_status_nudge,
    maybe_inject_debate_gate,
    maybe_inject_turn_token_budget_gate,
    resolve_openai_tool_defs,
)
from .outcome import RoundOutcome
from .round import (
    LlmRoundFailure,
    decide_no_tool_round,
    record_round_start,
    run_llm_round,
)
from .segments import join_segments
from .soft_gates import maybe_soft_gate_no_tool_return
from .tool_protocol_sanitize import sanitize_protocol_text
from .tool_round import handle_tool_calls_round

logger = get_logger(__name__)


@dataclass
class CaptainLoopMirror:
    """Live captain-loop mirror for suspension capture (G4 turn_paused).

    Published only while ``react_loop(..., role="captain")`` is running. Holds a
    reference to the run's :class:`LoopController` plus the two content
    accumulators a suspending face needs (ask_user → ``content_before_round``;
    delegate / team_preview / plan_review → ``final_content``).
    """

    controller: LoopController
    content_before_round: str = ""
    final_content: str = ""


current_captain_loop: ContextVar[CaptainLoopMirror | None] = ContextVar(
    "current_captain_loop", default=None
)


def sync_captain_loop_mirror(
    *,
    content_before_round: str | None = None,
    final_content: str | None = None,
) -> None:
    """Update the published captain mirror in place (no-op when unset / non-captain)."""
    mirror = current_captain_loop.get()
    if mirror is None:
        return
    if content_before_round is not None:
        mirror.content_before_round = content_before_round
    if final_content is not None:
        mirror.final_content = final_content


async def react_loop(
    *,
    messages: list[LLMMessage],
    llm: OpenAICompatibleProvider,
    tools: ToolRegistry,
    sink: EventSink,
    tool_context: ToolContext,
    profile: ProfileParams | None = None,
    turn_model: str | None = None,
    allowed_tool_names: list[str] | None = None,
    on_content: Callable[[str], None] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
    on_tool_progress: Callable[[str, int], None] | None = None,
    on_reset: Callable[[str], None] | None = None,
    on_round_begin: Callable[[], list[LLMMessage]] | None = None,
    round_sink: list[int] | None = None,
    raise_on_error: bool = False,
    citation_sink: list[dict[str, Any]] | None = None,
    annotate_citations: bool = True,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
    ledger_registrant: str = "",
    approval_gate: ApprovalGate | None = None,
    usage_sink: list[TokenUsage] | None = None,
    finish_override_sink: list[FinishReason] | None = None,
    run_id: str = "",
    agent_id: str = "",
    role: str = "",
    deliverable_only: bool = False,
    supports_tools: bool | None = None,
    gate_escalation_sink: list[dict[str, Any]] | None = None,
    token_budget: int = 0,
    cutoff_reason_sink: list[str] | None = None,
    controller_seed: Mapping[str, Any] | None = None,
    tool_failure_sink: list[dict[str, Any]] | None = None,
    files_expected: bool = False,
    short_write_posture: bool = False,
    tighten_verify_exec_thrash: bool = False,
    form_prose: bool = False,
    product_landing_artifacts: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, str, TokenUsage, int]:
    """Run the ReAct loop.

    Returns ``(final_content, final_reasoning, usage, rounds)`` where ``usage`` is
    the turn's :class:`TokenUsage` summed across every round (carrying the
    cache_hit/cache_miss split so cost stays honest on multi-turn chats — a single
    object instead of loose ints). ``final_reasoning`` is the concatenated
    thinking text across all rounds (empty when thinking is disabled), mirroring
    what was streamed via ``reasoning_delta`` so it can be persisted for replay.

    The ``profile`` drives both the model params and the round budget
    (``profile.max_rounds``); it defaults to the chat profile. By
    default content/reasoning deltas are emitted as conversation events
    (single-agent path). A caller running a multi-agent run passes ``on_content``
    /``on_reasoning`` to redirect text into ``run_output_delta`` instead, and
    ``on_tool_progress`` to surface a worker's tool-call ARGUMENT streaming
    (``(tool_name, cumulative_chars)``, throttled) — the only live signal during a
    long file write, which is neither content nor reasoning.
    ``on_reset`` mirrors that redirection for every draft-discard reset: the
    default clears the CEO bubble (``content_reset``); a worker passes ``on_reset``
    to clear its run card (``run_output_reset``) instead — so the rewrite replaces
    the discarded draft cleanly on whichever surface streamed it (统一底线). It takes
    the ``ResetReason`` (finish_guard / retry / soft_gate / narration / ask_user) —
    each emit site states WHY, and folds render the rework chip only for finish_guard.
    ``on_round_begin`` (when provided) is called at the top of every round AFTER the
    first; the messages it returns are appended to the window before that round's LLM
    call. A generic「inject context that accrued while the run was working」hook — a
    delegated worker wires it to pull teammates' freshly-posted 便签 (§2.2 通·便签墙)
    so the team builds on each other's evolving work; ``None`` (CEO / solo / tests) is a
    no-op. The engine only appends what it returns — the caller owns the semantics.
    ``allowed_tool_names`` filters which tools the model may call and execute
    (schema offer + ``execute_tools`` enforce; ``None`` = all,
    ``[]`` = none). Tool execution events always go to the sink. When
    ``citation_sink`` is provided, web sources consulted by research tools are
    aggregated into it (de-duped, capped) for the caller to surface/persist.
    ``turn_evidence_ledger`` (调研路径) registers hits into the turn-shared ledger
    and annotates tool output with stable ``#rN=url`` for CEO and workers alike
    (引用即出处 P1). ``annotate_citations`` gates finish_guard's legacy ``[n]`` check
    (CEO True / worker False)；``#rN`` id 存在闸在台账接通且正文出现约定标记时启用
    （Q5；worker 回炉 1 次 / CEO 跟配置）。without a ledger the old ``[n]=url``
    annotate path still applies. Debate speakers omit the turn ledger (场级 ``#e``).
    ``approval_gate`` (CEO chat path only; ``None`` for delegated workers) pauses
    GRANTABLE tool calls until the user authorizes them — a denial is fed back to
    the model as a tool result so it can adapt.
    ``usage_sink`` (when provided) mirrors the running ``total_usage`` after each
    completed round, so a caller that catches an exception can still bill the
    tokens consumed before the failure (B-deep 失败计费): on ``raise_on_error`` the
    accumulated usage is otherwise lost inside this frame when a mid-loop round
    raises. It is cleared on entry and only ever holds the latest cumulative total
    (a single-element list); on a normal return the caller uses the returned usage
    instead.
    ``finish_override_sink`` (when provided, CEO captain path) is an out-param
    mirroring the ``usage_sink`` idiom: it carries a single :class:`FinishReason`
    the caller should stamp on the turn instead of the rounds-derived default
    (``end_turn`` / ``max_rounds``). The loop sets it to ``DEGRADED`` when the model
    keeps returning empty responses past the threshold, or ``UNPRODUCTIVE``
    when it early-stops a run of all-tools-failed-no-content rounds (B2). Cleared on
    entry; left empty on a normal finish (one channel, since a run takes at most one
    such terminal path).

    ``run_id`` / ``role`` scope the execution-level facts (§8.3) this loop records
    into the turn's ambient :data:`~agentcore.runtime.facts.current_fact_log`
    (round_boundary / llm_call / note) — captain vs worker, so a multi-agent turn's
    facts split per run. They default to empty (a standalone loop / test records
    facts with no scope, or none at all when no log is bound).

    ``deliverable_only`` makes the RETURNED ``final_content`` the 交付正文 only — the
    prose a round streams BEFORE a *non-terminal* tool call is treated as PROCESS
    narration ("我先查一下" / an acknowledgement of an injected ``[系统提示]`` steer)
    and rolled back off the accumulator (mirroring the finish_guard ``Rework``
    rollback), so it never accrues into the persisted product / next-turn history /
    CEO synthesis input — **unless every tool in that round failed**, in which case
    the prose is kept (already streamed to the user; not a successful lead-in).
    It is always journaled per round (llm_call fact → 旁白入 journal). Two display
    disciplines by channel架构:

    - CEO captain (``on_reset`` is None → default ``content_delta`` / ``content_reset``):
      the narration STAYS streamed + visible in the SEPARATE process timeline
      (透明可见); only ``messages.content`` (旁路 conformance) is trimmed. No reset.
    - worker / debater / revision (``on_reset`` routes ``run_output_reset``, and the
      card replays from the ``message_final`` fact — a SINGLE display+data channel):
      the narration rollback ALSO emits ``run_output_reset`` to clear the streamed
      draft off the card, so 直播 == the rolled-back deliverable == 重载 (synthesized
      from ``message_final``) — the conformance invariant.

    Terminal rounds (handoff / suspend checkpoints other than blocking ``ask_user``)
    KEEP their pre-tool text — that IS the deliverable at that boundary. Blocking
    ``ask_user`` absorbs same-round prose into the card instead (see
    ``ask_user_absorb``). Default ``False`` leaves the
    accumulation byte-identical to before (standalone loops / tests).

    ``gate_escalation_sink`` (Worker routing Phase 1): when provided, each tool round
    runs the Escalation Gate after ``execute_tools``; scheme-layer signals are appended
    here and emitted as ``run_escalation_gate``. CEO / solo leave it ``None`` (gate inert).

    ``token_budget`` (Worker hard ceiling · loose backstop): a cumulative
    input+output token cap for the whole run, checked at the TOP of each round. Once
    ``total_usage.total_tokens`` reaches it the loop stops and force-finalizes — the
    backstop against a worker blowing past the configured unified ceiling. The
    terminal finalize (this AND ``max_rounds`` exhaustion) is gate-routed by run
    health (``controller.is_thrashing()``): an on-track run delivers normally; a
    thrashing worker finishes DEGRADED and emits an observable ``escalation_raised``
    signal (no auto re-decompose — the CEO may voluntarily replan). ``0`` (CEO /
    solo / tests / ceiling disabled) disables the backstop, leaving the run bounded
    only by ``profile.max_rounds``.

    ``controller_seed`` (resume path): optional JSON-safe latch snapshot from a prior
    ``turn_paused.controller``; omitted on a fresh turn (behaviour unchanged).

    ``tool_failure_sink``: when given, replaced at every terminal exit with this run's
    tool-failure fact dicts (same tally as the circuit breaker — for RunState / CEO).
    """
    profile = profile or get_profile("chat")
    if usage_sink is not None:
        usage_sink.clear()
    if finish_override_sink is not None:
        finish_override_sink.clear()
    if cutoff_reason_sink is not None:
        cutoff_reason_sink.clear()

    disabled_tools: set[str] = set()
    # Re-apply run-scoped read_url retirement from a prior pass (stream-stall →
    # Wave retry, or contract write_pass/retry) so the tool is not re-offered.
    if run_id:
        from agentcore.tools.builtin.web._net import is_read_url_retired

        if is_read_url_retired(run_id):
            disabled_tools.add("read_url")
    # B·收尾窗口：预算软顶 / 超时预警后收窄到落盘+handoff（不改硬顶语义）。
    wind_down_active = False
    wind_down_reason = ""
    wind_down_effective_allowed: list[str] | None = None
    wind_down_whitelist: frozenset[str] | None = None
    wind_down_breach_count = 0
    wind_down_breach_pending_nudge = False
    wind_down_breach_nudge_text = ""
    # 检索预算临界（剩 ≤2）一次性 reflection，缓解同轮 fan-out 超订。
    retrieval_critical_warned = False
    # Mutable allowlist: files_expected催写路径可并入最小写盘集（prose registry 无写 → no-op）。
    live_allowed: list[str] | None = (
        list(allowed_tool_names) if allowed_tool_names is not None else None
    )
    persist_write_granted = False

    def _effective_allowed() -> list[str] | None:
        if wind_down_effective_allowed is not None:
            return wind_down_effective_allowed
        return live_allowed

    def _grant_persist_writes(reason: str) -> None:
        """files_expected催写：显式名单缺写盘时并入最小写盘集。"""
        nonlocal live_allowed, tool_defs, persist_write_granted
        if persist_write_granted or form_prose or not files_expected:
            return
        from agentcore.runtime.runs.worker_budget import merge_persist_write_tools

        prior = list(live_allowed) if live_allowed is not None else None
        merged = merge_persist_write_tools(
            live_allowed, registry_names=set(tools.names)
        )
        persist_write_granted = True
        if merged is not None and merged != live_allowed:
            live_allowed = merged
            tool_defs = resolve_openai_tool_defs(tools, live_allowed, disabled_tools)
            logger.info(
                "engine.persist_write_grant",
                reason=reason,
                run_id=run_id,
                added=[n for n in merged if prior is None or n not in prior],
            )

    controller: LoopController | None = None

    def _resolve_tool_defs() -> list[dict[str, Any]] | None:
        return resolve_openai_tool_defs(tools, _effective_allowed(), disabled_tools)

    tool_defs = _resolve_tool_defs()

    emit_content = on_content or (lambda delta: sink.emit(content_delta(delta)))
    emit_reasoning = on_reasoning or (lambda delta: sink.emit(reasoning_delta(delta)))
    emit_reset = on_reset or (lambda reason: sink.emit(content_reset(reason)))

    total_usage = TokenUsage()
    final_content = ""
    final_reasoning = ""

    profile = profile or get_profile("chat")
    base_model = turn_model
    if base_model is None:
        from agentcore.config import settings

        logger.warning(
            "react_loop.missing_turn_model",
            fallback=settings.platform_model,
        )
        base_model = settings.platform_model

    investigation_tools = classify_investigation_tools(tools, allowed_tool_names)
    controller = create_loop_controller(
        investigation_tools,
        seed=controller_seed,
        files_expected=files_expected,
        short_write_posture=short_write_posture,
        tighten_verify_exec_thrash=tighten_verify_exec_thrash,
        max_rounds=profile.max_rounds,
        form_prose=form_prose,
        product_landing_artifacts=product_landing_artifacts,
    )
    # 跑/修·打开验证·贴码写回：引擎不再扫用户文硬分叉；选型/验收靠提示词 + 结构字段。
    if role == "captain":
        maybe_inject_availability_status_nudge(
            messages=messages,
            run_id=run_id or "",
            role=role,
        )
    active_model: str | None = base_model
    finish_guard_reworks = 0
    ceiling_reason = "max_rounds"
    round_idx = 0

    def _export_tool_failures() -> None:
        if tool_failure_sink is None:
            return
        tool_failure_sink.clear()
        tool_failure_sink.extend(f.to_dict() for f in controller.tool_failure_facts())

    def _exit(
        content: str, reasoning: str, usage: TokenUsage, rounds: int
    ) -> tuple[str, str, TokenUsage, int]:
        """Unified content exit: strip residual vendor tool-protocol markers.

        Every react_loop return (CEO / worker / forced finalize) funnels through
        here so the RETURNED deliverable — the text that is persisted and replayed
        on reload — is clean of stray ``<longcat_tool_call>`` / ``</arg_key>`` tags
        some providers leak into prose. Live ``content_delta`` was already streamed
        (接受活体流短暂脏、reload 后干净); we clean only the final value and never
        buffer at the SSE-delta level.
        """
        return sanitize_protocol_text(content), reasoning, usage, rounds

    # G4: publish captain live mirror only when role=="captain" — NOT via
    # deliverable_only (workers / debaters also set that flag and nest under the
    # captain Task; gating on it would clobber the captain mirror).
    captain_token = None
    if role == "captain":
        captain_token = current_captain_loop.set(CaptainLoopMirror(controller=controller))

    def _enter_wind_down(reason: str, instruction: str) -> None:
        nonlocal wind_down_active, wind_down_reason, wind_down_effective_allowed
        nonlocal wind_down_whitelist, tool_defs
        if wind_down_active or role != "worker":
            return
        from agentcore.runtime.runs.cutoff import (
            narrow_tools_for_wind_down,
            wind_down_allowed_tools,
            worker_keeps_file_read_in_wind_down,
        )

        wind_down_active = True
        wind_down_reason = reason
        available = set(tools.names)
        # 收尾也是催写路径：files_expected 且名单缺写盘时先并入再收窄。
        _grant_persist_writes(f"wind_down:{reason}")
        keep_file_read = worker_keeps_file_read_in_wind_down(
            available=available, allowed=live_allowed
        )
        wind_down_whitelist = wind_down_allowed_tools(keep_file_read=keep_file_read)
        narrowed = narrow_tools_for_wind_down(
            available,
            allowed=live_allowed,
            keep_file_read=keep_file_read,
        )
        wind_down_effective_allowed = narrowed
        tool_defs = _resolve_tool_defs()
        messages.append(LLMMessage(role="user", content=instruction))
        from agentcore.runtime.tool_failures import sync_tool_failure_constraint_in_system

        sync_tool_failure_constraint_in_system(
            messages, controller.outstanding_tool_failures()
        )
        from agentcore.config import settings as _settings

        logger.info(
            "engine.wind_down_enter",
            reason=reason,
            run_id=run_id,
            role=role,
            tokens=total_usage.total_tokens,
            token_budget=token_budget,
            wind_down_reserve=(
                int(_settings.engine_worker_token_wind_down_reserve or 0)
                if reason == "token_budget"
                else None
            ),
            allowed_tools=narrowed,
            keep_file_read=keep_file_read,
        )
        from agentcore.runtime.runs.run_phase_emit import emit_run_phase

        emit_run_phase(sink, run_id, agent_id, "winding_down")

    def _consume_timeout_wind_down_pending() -> bool:
        """Consume timeout wind-down from hard-timeout guard and/or coordination session.

        Independent of token wind-down: a timeout pending must not be swallowed
        when the token soft-top already narrowed tools.
        """
        if role != "worker" or not run_id:
            return False
        from agentcore.runtime.runs.timeout_hard import get_hard_timeout

        guard = get_hard_timeout(run_id)
        if guard is not None and guard.consume_wind_down():
            # Keep coordination session mirrors in sync when present.
            from agentcore.runtime.coordination.session import active_coordination

            session = active_coordination()
            if session is not None:
                session._timeout_wind_down_pending.discard(run_id)
                session._timeout_wind_down_entered.add(run_id)
            return True
        from agentcore.runtime.coordination.session import active_coordination

        session = active_coordination()
        return bool(session is not None and session.consume_timeout_wind_down(run_id))

    def _maybe_arm_wind_down() -> None:
        """Budget soft-top or timeout warn → wind-down (handoff/persist).

        Token and timeout reasons are independent: timeout pending is consumed
        even when token wind-down is already active (marks entered for stamp).
        """
        if role != "worker":
            return
        from agentcore.config import settings
        from agentcore.runtime.runs.cutoff import (
            WIND_DOWN_INSTRUCTION_TIMEOUT,
            WIND_DOWN_INSTRUCTION_TOKEN,
            should_enter_token_wind_down,
        )

        reserve = int(settings.engine_worker_token_wind_down_reserve or 0)
        if not wind_down_active and should_enter_token_wind_down(
            total_usage.total_tokens, token_budget, reserve
        ):
            _enter_wind_down("token_budget", WIND_DOWN_INSTRUCTION_TOKEN)
        timeout_pending = _consume_timeout_wind_down_pending()
        if timeout_pending and not wind_down_active:
            _enter_wind_down("worker_timeout", WIND_DOWN_INSTRUCTION_TIMEOUT)

    def _enforce_hard_timeout_entry() -> str | None:
        """Round-boundary hard-timeout gate. Returns break reason or None.

        TIMEOUT → grant one grace wind-down round; after grace → force cancel
        (reuse cancel channel). No mid-stream preemption.
        """
        if role != "worker" or not run_id:
            return None
        from agentcore.runtime.runs.timeout_hard import (
            HardTimeoutPhase,
            get_hard_timeout,
        )

        guard = get_hard_timeout(run_id)
        if guard is None:
            return None
        if guard.allows_grace_round():
            guard.begin_grace_round()
            from agentcore.runtime.runs.cutoff import WIND_DOWN_INSTRUCTION_TIMEOUT

            if not wind_down_active:
                _enter_wind_down("worker_timeout", WIND_DOWN_INSTRUCTION_TIMEOUT)
            return None
        if guard.blocks_new_work():
            guard.request_force_cancel(reason="post_grace")
            logger.warning(
                "engine.timeout_force_cancel",
                run_id=run_id,
                phase=guard.phase.value,
            )
            return "worker_timeout"
        if guard.phase is HardTimeoutPhase.GRACE:
            # About to run the granted grace round — ensure tools are narrowed.
            from agentcore.runtime.runs.cutoff import WIND_DOWN_INSTRUCTION_TIMEOUT

            if not wind_down_active:
                _enter_wind_down("worker_timeout", WIND_DOWN_INSTRUCTION_TIMEOUT)
        return None

    try:
        for round_idx in range(profile.max_rounds):
            # Hard-timeout entry check BEFORE arming wind-down / LLM: after TIMEOUT
            # grant one grace round; after grace force-cancel (no new LLM/tool).
            hard_break = _enforce_hard_timeout_entry()
            if hard_break is not None:
                ceiling_reason = hard_break
                import asyncio

                raise asyncio.CancelledError("redirect")
            # B·收尾窗口必须先于硬顶：单轮 token 从软顶下方直接越过硬顶时，若先判硬顶
            # break，会整轮跳过 wind_down，随后 force_finalize 禁写 → worker 把
            # file_write 糊成正文 DSML。先武装收尾窗；若本轮刚进入，即使已过硬顶也
            # 先跑这一轮落盘/handoff，下一轮再撞硬顶 finalize。
            already_winding = wind_down_active
            _maybe_arm_wind_down()
            just_armed_wind_down = wind_down_active and not already_winding
            # Loose token backstop (Worker 硬顶): stop BEFORE starting a round once the run's
            # cumulative input+output tokens reach the ceiling, so a runaway overshoots by at
            # most one round instead of grinding on (根因: 之前没人比对这个累计数). ``total_usage``
            # is updated at each round's end, so this reflects rounds 0..round_idx-1. 0 =
            # disabled (CEO / solo / tests → bounded only by max_rounds).
            if (
                token_budget > 0
                and total_usage.total_tokens >= token_budget
                and not just_armed_wind_down
            ):
                ceiling_reason = "token_budget"
                logger.warning(
                    "engine.token_budget_exhausted",
                    run_id=run_id,
                    role=role,
                    tokens=total_usage.total_tokens,
                    token_budget=token_budget,
                    round=round_idx,
                )
                break
            if round_sink is not None:
                round_sink[:] = [round_idx + 1]
            logger.debug("react.round_start", round=round_idx, messages=len(messages))
            record_round_start(round_idx=round_idx, run_id=run_id, role=role)
            content_before_round = final_content
            # Update point 1/3: round start (content_before_round + current final_content).
            # Gated on role — nested worker loops must not mutate the captain mirror.
            if role == "captain":
                sync_captain_loop_mirror(
                    content_before_round=content_before_round,
                    final_content=final_content,
                )
            # 团队便签墙 推增量 (§2.2 通): before each step AFTER the first, inject context that
            # accrued WHILE this run was working — e.g. teammates' freshly-posted notes — so the
            # team builds on each other's evolving work instead of each guessing in isolation.
            # The opening round already carries the run's assembled context, so the hook starts at
            # round 1 (which also avoids two back-to-back user messages on the very first request).
            # Generic by design: the engine only appends what the hook returns; the caller owns the
            # semantics (引擎纯化), mirroring on_content / on_reasoning.
            if round_idx and on_round_begin is not None:
                messages.extend(on_round_begin())

            # CEO 协调模式 Phase 2: only the captain consumes team events (workers share
            # the ContextVar but must not block on the coordination queue).
            if role == "captain":
                from agentcore.runtime.coordination.wait import await_coordination_injection

                coord_t0 = time.perf_counter()
                coord_msgs = await await_coordination_injection(messages)
                coord_ms = int((time.perf_counter() - coord_t0) * 1000)
                if coord_ms >= 50 or coord_msgs:
                    logger.info(
                        "engine.coord_inject",
                        round=round_idx,
                        waited_ms=coord_ms,
                        injected=len(coord_msgs),
                    )
                if coord_msgs:
                    messages.extend(coord_msgs)
                    # Soft gates (all_completed): remind before synthesis / wrap-up
                    # while CEO is still in coordination — not only on no-tool Return.
                    # Debate-commitment before audit (same order as soft_gates.py).
                    # Turn-token wrap-up first: when ceiling is hit, audit/debate gates
                    # are suppressed (cannot dispatch) — steer CEO to close on output.
                    maybe_inject_turn_token_budget_gate(
                        controller,
                        messages=messages,
                        run_id=run_id,
                        round_idx=round_idx,
                        role=role,
                    )
                    if coordination_injection_has_all_completed(coord_msgs):
                        maybe_inject_debate_gate(
                            controller,
                            messages=messages,
                            run_id=run_id,
                            round_idx=round_idx,
                            role=role,
                        )
                        maybe_inject_audit_gate(
                            controller,
                            messages=messages,
                            run_id=run_id,
                            round_idx=round_idx,
                            role=role,
                        )
                else:
                    # No coordination wake this round — still steer if ceiling already hit
                    # (e.g. reject path / resume seed over ceiling before next think).
                    maybe_inject_turn_token_budget_gate(
                        controller,
                        messages=messages,
                        run_id=run_id,
                        round_idx=round_idx,
                        role=role,
                    )

            # Coordination idle-patrol: stamp worker LLM/tool busy so a quiet
            # event queue does not wake the CEO while teammates are still working.
            if role != "captain" and run_id:
                from agentcore.runtime.coordination.session import note_coord_worker_busy

                note_coord_worker_busy(run_id, "llm")
                from agentcore.runtime.runs.run_phase_emit import emit_run_phase

                emit_run_phase(sink, run_id, agent_id, "thinking")
            # 协调已活 → 进入本轮 LLM 前装好 wait 等闸内工具（与 mid-turn promote 对齐）。
            if role == "captain":
                from agentcore.runtime.resolve.ceo_surface import (
                    ensure_coordination_surface_before_llm,
                )

                if ensure_coordination_surface_before_llm(tools):
                    tool_defs = _resolve_tool_defs()
            try:
                round_result = await run_llm_round(
                    llm=llm,
                    profile=profile,
                    messages=messages,
                    investigation_tools=investigation_tools,
                    tool_defs=tool_defs,
                    active_model=active_model,
                    emit_content=emit_content,
                    emit_reasoning=emit_reasoning,
                    on_tool_progress=on_tool_progress,
                    round_idx=round_idx,
                    run_id=run_id,
                    raise_on_error=raise_on_error,
                    on_reset=emit_reset,
                )
            finally:
                if role != "captain" and run_id:
                    from agentcore.runtime.coordination.session import (
                        clear_coord_worker_busy,
                    )

                    clear_coord_worker_busy(run_id)

            if isinstance(round_result, LlmRoundFailure):
                # Hard LLM failure (non-raising path): the provider already exhausted its
                # network retries. End on ERROR/DEGRADED (error surfaced in the Return arm).
                outcome = RoundOutcome(
                    content="",
                    reasoning="",
                    usage=None,
                    llm_failed=True,
                    error_code=round_result.error_code,
                    error_message=round_result.error_message,
                    error_context=round_result.error_context,
                )
                directive: LoopDirective = decide_llm_failure(final_content=final_content)
            elif round_result.aborted:
                # Post-commit disconnect / stall: keep the partial prose and finish
                # DEGRADED (resume entry stays available via existing infrastructure).
                usage = round_result.usage
                if usage:
                    total_usage = total_usage + usage
                if usage_sink is not None:
                    usage_sink[:] = [total_usage]
                if round_result.content:
                    final_content = join_segments(final_content, round_result.content)
                    # Update point 2/3: prose join.
                    if role == "captain":
                        sync_captain_loop_mirror(final_content=final_content)
                if round_result.reasoning:
                    final_reasoning += round_result.reasoning
                outcome = RoundOutcome(
                    content=round_result.content,
                    reasoning=round_result.reasoning,
                    usage=usage,
                    llm_failed=True,
                    error_code=ErrorCode.LLM_ERROR,
                    error_message="模型响应中断，已保留已生成内容，可继续。",
                )
                directive = decide_llm_failure(final_content=final_content)
            else:
                usage = round_result.usage
                if usage:
                    total_usage = total_usage + usage
                if usage_sink is not None:
                    usage_sink[:] = [total_usage]

                if round_result.content:
                    final_content = join_segments(final_content, round_result.content)
                    # Update point 2/3: prose join.
                    if role == "captain":
                        sync_captain_loop_mirror(final_content=final_content)
                if round_result.reasoning:
                    final_reasoning += round_result.reasoning

                outcome = RoundOutcome(
                    content=round_result.content,
                    reasoning=round_result.reasoning,
                    usage=usage,
                    tool_calls=round_result.tool_calls,
                    empty_diagnosis=round_result.empty_diagnosis,
                    empty_raw_preview=round_result.empty_raw_preview,
                )
                # 协调监听豁免：captain 在活跃协调中对纯进展事件保持静默（无正文、无工具）
                # 是被指引的合法行为，不进 B2 空响应梯子；ALL_COMPLETED 注入即关闭 session，
                # 终稿阶段的空响应仍按原梯子降级收口。
                counts_as_empty = outcome.is_empty
                if counts_as_empty and role == "captain":
                    from agentcore.runtime.coordination.session import active_coordination

                    coord_session = active_coordination()
                    if coord_session is not None and coord_session.active:
                        counts_as_empty = False
                        logger.info(
                            "engine.coordination_listen",
                            round=round_idx,
                            execution_id=coord_session.execution_id,
                        )
                controller.note_empty_round(counts_as_empty)

                if not outcome.has_tool_calls:
                    directive = decide_no_tool_round(
                        outcome,
                        final_content=final_content,
                        controller=controller,
                        annotate_citations=annotate_citations,
                        citation_sink=citation_sink,
                        finish_guard_reworks=finish_guard_reworks,
                        tools_offered=tool_defs is not None,
                        supports_tools=supports_tools,
                        turn_evidence_ledger=turn_evidence_ledger,
                    )
                    # Soft debate-commitment / audit-gate: captain wrap-up —
                    # discard the draft, inject nudge, continue (one-shot each).
                    directive, rolled = maybe_soft_gate_no_tool_return(
                        directive=directive,
                        outcome=outcome,
                        controller=controller,
                        messages=messages,
                        role=role,
                        round_idx=round_idx,
                        run_id=run_id,
                        content_before_round=content_before_round,
                        emit_reset=emit_reset,
                    )
                    if rolled is not None:
                        final_content = rolled
                else:
                    # Wind-down breach: non-whitelist tool → nudge+handoff-only, or
                    # local synth close (2nd breach / already at hard ceiling).
                    skip_tool_exec = False
                    wind_down_breach_pending_nudge = False
                    wind_down_breach_nudge_text = ""
                    if wind_down_active and role == "worker":
                        from agentcore.runtime.engine.directive import Continue, Return
                        from agentcore.runtime.runs.cutoff import (
                            WIND_DOWN_ALLOWED_TOOLS,
                            WIND_DOWN_BREACH_NUDGE,
                            WIND_DOWN_BREACH_NUDGE_KEEP_LANDING,
                            narrow_tools_for_wind_down_breach,
                            should_force_local_after_wind_down_breach,
                            wind_down_breach_tool_names,
                            worker_keeps_file_read_in_wind_down,
                        )

                        effective_whitelist = wind_down_whitelist or WIND_DOWN_ALLOWED_TOOLS
                        breached = wind_down_breach_tool_names(
                            [
                                (tc.function.name or "")
                                for tc in (outcome.tool_calls or [])
                            ],
                            allowed=effective_whitelist,
                        )
                        if breached:
                            force_local = should_force_local_after_wind_down_breach(
                                prior_breaches=wind_down_breach_count,
                                tokens=total_usage.total_tokens,
                                token_budget=token_budget,
                                wind_down_reason=wind_down_reason,
                            )
                            # Pending landing obligation → keep write tools; only strip retrieval.
                            keep_landing = (
                                files_expected
                                and controller is not None
                                and not controller.landing_succeeded
                            )
                            keep_file_read = keep_landing and worker_keeps_file_read_in_wind_down(
                                available=set(tools.names),
                                allowed=list(effective_whitelist),
                            )
                            logger.warning(
                                "engine.wind_down_breach",
                                run_id=run_id,
                                breached_tools=breached,
                                prior_breaches=wind_down_breach_count,
                                force_local=force_local,
                                keep_landing=keep_landing,
                                tokens=total_usage.total_tokens,
                                token_budget=token_budget,
                            )
                            wind_down_breach_count += 1

                            def _journal_wind_down_deny(
                                tc: Any,
                                name: str,
                                *,
                                _keep_landing: bool = keep_landing,
                            ) -> None:
                                """Emit durable tool_use_start/end so wind_down 拒执行
                                is journal-queryable."""
                                import json as _json

                                raw_args = ""
                                try:
                                    raw_args = tc.function.arguments or ""
                                except Exception:  # noqa: BLE001
                                    raw_args = ""
                                try:
                                    args = _json.loads(raw_args) if raw_args else {}
                                    if not isinstance(args, dict):
                                        args = {}
                                except Exception:  # noqa: BLE001
                                    args = {}
                                deny = (
                                    f"工具 '{name}' 不在收尾窗口白名单，未执行。"
                                    + (
                                        "请落盘后调用 handoff 交卷。"
                                        if _keep_landing
                                        else "请立即调用 handoff 交卷。"
                                    )
                                )
                                sink.emit(
                                    tool_use_start(
                                        tc.id, name, args, run_id=run_id or ""
                                    )
                                )
                                sink.emit(
                                    tool_use_end(
                                        tc.id,
                                        name,
                                        success=False,
                                        output=deny,
                                        run_id=run_id or "",
                                    )
                                )

                            if force_local:
                                # Still journal denied calls before local-synth close.
                                for tc in outcome.tool_calls or []:
                                    name = tc.function.name or ""
                                    if name and name not in effective_whitelist:
                                        _journal_wind_down_deny(tc, name)
                                directive = Return()
                                outcome = RoundOutcome(
                                    content=outcome.content,
                                    reasoning=outcome.reasoning,
                                    usage=outcome.usage,
                                )
                                skip_tool_exec = True
                            else:
                                kept = [
                                    tc
                                    for tc in (outcome.tool_calls or [])
                                    if (tc.function.name or "") in effective_whitelist
                                ]
                                denied = [
                                    tc
                                    for tc in (outcome.tool_calls or [])
                                    if (tc.function.name or "") not in effective_whitelist
                                ]
                                for tc in denied:
                                    _journal_wind_down_deny(tc, tc.function.name or "")
                                wind_down_effective_allowed = (
                                    narrow_tools_for_wind_down_breach(
                                        set(tools.names),
                                        keep_landing=keep_landing,
                                        keep_file_read=keep_file_read,
                                        allowed=list(effective_whitelist),
                                    )
                                )
                                breach_nudge = (
                                    WIND_DOWN_BREACH_NUDGE_KEEP_LANDING
                                    if keep_landing
                                    else WIND_DOWN_BREACH_NUDGE
                                )
                                tool_defs = _resolve_tool_defs()
                                if not kept:
                                    messages.append(
                                        LLMMessage(
                                            role="assistant",
                                            content=outcome.content or None,
                                            tool_calls=outcome.tool_calls or None,
                                            reasoning_content=outcome.reasoning
                                            or None,
                                        )
                                    )
                                    for tc in outcome.tool_calls or []:
                                        name = tc.function.name or ""
                                        deny = (
                                            f"工具 '{name}' 不在收尾窗口白名单，未执行。"
                                            + (
                                                "请落盘后调用 handoff 交卷。"
                                                if keep_landing
                                                else "请立即调用 handoff 交卷。"
                                            )
                                        )
                                        messages.append(
                                            LLMMessage(
                                                role="tool",
                                                content=deny,
                                                tool_call_id=tc.id,
                                            )
                                        )
                                    messages.append(
                                        LLMMessage(
                                            role="user", content=breach_nudge
                                        )
                                    )
                                    outcome = RoundOutcome(
                                        content=outcome.content,
                                        reasoning=outcome.reasoning,
                                        usage=outcome.usage,
                                    )
                                    directive = Continue()
                                    skip_tool_exec = True
                                else:
                                    outcome = RoundOutcome(
                                        content=outcome.content,
                                        reasoning=outcome.reasoning,
                                        usage=outcome.usage,
                                        tool_calls=kept,
                                    )
                                    # Nudge after tools if the round continues (below).
                                    skip_tool_exec = False
                                    # Mark so post-tool path can inject nudge once.
                                    wind_down_breach_pending_nudge = True
                                    # Stash nudge text for the post-tool inject path.
                                    wind_down_breach_nudge_text = breach_nudge

                    if not skip_tool_exec:
                        if role != "captain" and run_id:
                            from agentcore.runtime.coordination.session import (
                                note_coord_worker_busy,
                            )

                            note_coord_worker_busy(run_id, "tool")
                        try:
                            tool_round = await handle_tool_calls_round(
                                outcome=outcome,
                                messages=messages,
                                tools=tools,
                                tool_context=tool_context,
                                sink=sink,
                                approval_gate=approval_gate,
                                citation_sink=citation_sink,
                                annotate_citations=annotate_citations,
                                turn_evidence_ledger=turn_evidence_ledger,
                                ledger_registrant=ledger_registrant,
                                run_id=run_id,
                                role=role,
                                gate_escalation_sink=gate_escalation_sink,
                                deliverable_only=deliverable_only,
                                on_reset=on_reset,
                                emit_reset=emit_reset,
                                content_before_round=content_before_round,
                                final_content=final_content,
                                round_result_content=round_result.content,
                                total_usage=total_usage,
                                controller=controller,
                                allowed_tool_names=_effective_allowed(),
                                disabled_tools=disabled_tools,
                                round_idx=round_idx,
                            )
                        finally:
                            if role != "captain" and run_id:
                                from agentcore.runtime.coordination.session import (
                                    clear_coord_worker_busy,
                                )

                                clear_coord_worker_busy(run_id)
                        outcome = tool_round.outcome
                        directive = tool_round.directive
                        final_content = tool_round.final_content
                        total_usage = tool_round.total_usage
                        if tool_round.tool_defs_changed:
                            tool_defs = tool_round.tool_defs
                        if wind_down_breach_pending_nudge:
                            from agentcore.runtime.engine.directive import Continue
                            from agentcore.runtime.runs.cutoff import (
                                WIND_DOWN_BREACH_NUDGE,
                            )

                            if isinstance(directive, Continue):
                                messages.append(
                                    LLMMessage(
                                        role="user",
                                        content=(
                                            wind_down_breach_nudge_text
                                            or WIND_DOWN_BREACH_NUDGE
                                        ),
                                    )
                                )
                            wind_down_breach_pending_nudge = False
                            wind_down_breach_nudge_text = ""

            applied = await apply_loop_directive(
                directive=directive,
                outcome=outcome,
                messages=messages,
                llm=llm,
                tools=tools,
                tool_context=tool_context,
                sink=sink,
                profile=profile,
                active_model=active_model,
                base_model=base_model,
                allowed_tool_names=_effective_allowed(),
                disabled_tools=disabled_tools,
                emit_content=emit_content,
                emit_reasoning=emit_reasoning,
                emit_reset=emit_reset,
                final_content=final_content,
                final_reasoning=final_reasoning,
                total_usage=total_usage,
                round_idx=round_idx,
                run_id=run_id,
                role=role,
                finish_override_sink=finish_override_sink,
                approval_gate=approval_gate,
                citation_sink=citation_sink,
                annotate_citations=annotate_citations,
                turn_evidence_ledger=turn_evidence_ledger,
                ledger_registrant=ledger_registrant,
                gate_escalation_sink=gate_escalation_sink,
                controller=controller,
                content_before_round=content_before_round,
                finish_guard_reworks=finish_guard_reworks,
                files_expected=files_expected,
                form_prose=form_prose,
            )
            if applied.action == "return":
                _export_tool_failures()
                return _exit(
                    applied.content,
                    applied.reasoning,
                    applied.usage or total_usage,
                    applied.rounds,
                )
            final_content = applied.final_content
            final_reasoning = applied.final_reasoning
            if applied.total_usage is not None:
                total_usage = applied.total_usage
            finish_guard_reworks = applied.finish_guard_reworks
            if applied.tool_defs_changed:
                tool_defs = applied.tool_defs
            # Close the post-TIMEOUT grace round so the next entry force-cancels.
            if role == "worker" and run_id:
                from agentcore.runtime.runs.timeout_hard import (
                    HardTimeoutPhase,
                    get_hard_timeout,
                )

                _guard = get_hard_timeout(run_id)
                if _guard is not None and _guard.phase is HardTimeoutPhase.GRACE:
                    _guard.end_grace_round()
            # Retrieval budget exhausted → enter wind-down early (don't wait for
            # wall-clock TIMEOUT while the worker can no longer search).
            # Critical (remaining ≤2, still open) → one-shot reflection so the next
            # think round does not fan-out more calls than slots left.
            rb = getattr(tool_context, "retrieval_budget", None)
            if (
                role == "worker"
                and not wind_down_active
                and rb is not None
                and rb.limit > 0
                and rb.remaining <= 0
            ):
                _enter_wind_down(
                    "retrieval_budget",
                    "[系统提示] 检索预算已用尽。本轮起进入收尾窗口：仅允许落盘与 "
                    "handoff，请基于已有证据交卷；禁止继续 web_search / read_url。",
                )
                logger.info(
                    "engine.retrieval_budget_wind_down",
                    run_id=run_id,
                    limit=rb.limit,
                    used=rb.used,
                )
            elif (
                role == "worker"
                and rb is not None
                and not retrieval_critical_warned
            ):
                from agentcore.runtime.runs.retrieval_budget import (
                    format_retrieval_budget_critical_prompt,
                    is_retrieval_budget_critical,
                )

                if is_retrieval_budget_critical(rb.remaining, limit=rb.limit):
                    retrieval_critical_warned = True
                    critical_msg = format_retrieval_budget_critical_prompt(
                        remaining=rb.remaining, limit=rb.limit
                    )
                    messages.append(LLMMessage(role="user", content=critical_msg))
                    logger.info(
                        "engine.retrieval_budget_critical",
                        run_id=run_id,
                        remaining=rb.remaining,
                        limit=rb.limit,
                        used=rb.used,
                    )
            continue

        result = await ceiling_finalize(
            messages=messages,
            llm=llm,
            profile=profile,
            active_model=active_model,
            base_model=base_model,
            tools=tools,
            allowed_tool_names=_effective_allowed(),
            disabled_tools=disabled_tools,
            emit_content=emit_content,
            emit_reasoning=emit_reasoning,
            emit_reset=emit_reset,
            final_content=final_content,
            final_reasoning=final_reasoning,
            total_usage=total_usage,
            ceiling_reason=ceiling_reason,
            round_idx=round_idx,
            role=role,
            run_id=run_id,
            token_budget=token_budget,
            controller=controller,
            tool_context=tool_context,
            sink=sink,
            finish_override_sink=finish_override_sink,
            gate_escalation_sink=gate_escalation_sink,
            cutoff_reason_sink=cutoff_reason_sink,
            files_expected=files_expected,
            form_prose=form_prose,
        )
        _export_tool_failures()
        return _exit(*result)
    finally:
        if captain_token is not None:
            current_captain_loop.reset(captain_token)

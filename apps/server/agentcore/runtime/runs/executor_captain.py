"""Split from executor.py — see executor.py module docstring."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace

from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.llm.pricing import calculate_cost
from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import LLMMessage, LLMProvider, TokenUsage
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.engine import react_loop
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    run_completed,
    run_context,
    run_failed,
    run_started,
    tool_progress,
)
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import MessageFinalFact, record_turn_fact
from agentcore.runtime.runs.executor_context import (
    _build_captain_context_blocks,
    _context_block_payloads,
)
from agentcore.runtime.runs.executor_shared import _priced_failure, resolve_finish_override
from agentcore.runtime.runs.types import ContextBlock, RunPhase, RunSpec, RunState
from agentcore.runtime.suspension import captain_transcript
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry

logger = get_logger(__name__)


def build_captain_executor(
    *,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    base_tool_context: ToolContext,
    chat_system_prompt: str,
    history: list[dict],
    user_message: str,
    profile: ProfileParams,
    turn_model: str,
    citation_sink: list[dict],
    approval_gate: ApprovalGate | None = None,
    supports_tools: bool | None = None,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
) -> Callable[[RunSpec], Awaitable[RunState]]:
    """Build the executor for the turn's CAPTAIN root run — the CEO chat loop.

    The captain is the turn's root Run node: unlike a delegated worker it owns the
    conversation voice (its content/reasoning stream to the chat bubble via the
    engine's default ``content_delta`` / ``reasoning_delta``, NOT run-scoped), runs
    the ``chat`` profile, holds the read/retrieval tools + ``delegate``, and writes
    the user-facing reply (possibly after delegating). It shares the one
    ``react_loop`` assembly with workers; only the message build + output routing +
    cost role differ. It runs directly (not via the WaveScheduler — it is the root
    that *calls* delegate, which schedules the children), so it takes no
    ``completed`` deps map.

    The captain's run lifecycle (``run_started`` / ``run_completed`` role=captain)
    is emitted so the graph has a real root 汇聚点 (declared in the delegate batch's
    ``run_plan``); a non-delegating turn emits them too but, lacking a ``run_plan``,
    they are dropped client-side and never journaled into a graph. Priced once here
    (``state.cost``) so the captain payroll row shows real cost; the pipeline reads
    that into the captain ledger row (no re-price).
    """

    async def execute(spec: RunSpec) -> RunState:
        tool_ctx = replace(
            base_tool_context, run_id=spec.run_id, agent_id=spec.agent_id or spec.run_id
        )
        messages = [LLMMessage(role="system", content=chat_system_prompt)]
        for msg in history:
            messages.append(LLMMessage(role=msg["role"], content=msg["content"]))
        messages.append(LLMMessage(role="user", content=user_message))
        return await _drive_captain_loop(
            spec=spec,
            messages=messages,
            received_blocks=_build_captain_context_blocks(
                chat_system_prompt, history, user_message
            ),
            llm=llm,
            tools=tools,
            sink=sink,
            tool_ctx=tool_ctx,
            profile=profile,
            turn_model=turn_model,
            citation_sink=citation_sink,
            approval_gate=approval_gate,
            supports_tools=supports_tools,
            turn_evidence_ledger=turn_evidence_ledger,
        )

    return execute


def build_captain_resumer(
    *,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    base_tool_context: ToolContext,
    profile: ProfileParams,
    turn_model: str,
    citation_sink: list[dict],
    approval_gate: ApprovalGate | None = None,
    supports_tools: bool | None = None,
    controller_seed: dict | None = None,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
) -> Callable[[RunSpec, list[LLMMessage]], Awaitable[RunState]]:
    """Build the captain executor for a RESUMED turn (结构化挂起 2b).

    Same loop as :func:`build_captain_executor`, but the CEO transcript is REBUILT by
    the caller (the stored pre-pause messages + the resumed ``delegate`` tool result)
    and handed in, instead of assembled from system/history/user. The CEO continues
    from exactly where it suspended — reading the workers' product as the delegate
    tool result and writing its overview (or delegating again). Emits the captain
    ``run_*`` lifecycle so the resumed turn's graph has its root 汇聚点 like a normal
    turn; the client dedupes the captain node by id across the original + resumed
    journal segments.

    ``controller_seed`` restores the five cross-suspension LoopController latches from
    a prior ``turn_paused.controller`` snapshot (G5); omit / ``None`` keeps fresh-turn
    behaviour.
    """

    async def execute(spec: RunSpec, messages: list[LLMMessage]) -> RunState:
        tool_ctx = replace(
            base_tool_context, run_id=spec.run_id, agent_id=spec.agent_id or spec.run_id
        )
        return await _drive_captain_loop(
            spec=spec,
            messages=messages,
            llm=llm,
            tools=tools,
            sink=sink,
            tool_ctx=tool_ctx,
            profile=profile,
            turn_model=turn_model,
            citation_sink=citation_sink,
            approval_gate=approval_gate,
            supports_tools=supports_tools,
            controller_seed=controller_seed,
            turn_evidence_ledger=turn_evidence_ledger,
        )

    return execute


async def _drive_captain_loop(
    *,
    spec: RunSpec,
    messages: list[LLMMessage],
    received_blocks: list[ContextBlock] | None = None,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    tool_ctx: ToolContext,
    profile: ProfileParams,
    turn_model: str,
    citation_sink: list[dict],
    approval_gate: ApprovalGate | None,
    supports_tools: bool | None = None,
    controller_seed: dict | None = None,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
) -> RunState:
    """Run the CEO captain ReAct loop over ``messages`` and fold it into a RunState.

    Shared by the first-time captain executor and the resume captain executor: emits
    the captain ``run_started`` / ``run_completed`` (role=captain), prices the run
    once, and PUBLISHES the live ``messages`` list on :data:`captain_transcript` for
    the duration of the loop — so the ``delegate`` checkpoint hook, running deep inside
    this same task, can snapshot the CEO transcript when it captures a durable
    suspension frame (结构化挂起 2b). The contextvar is task-local and reset on exit,
    so concurrent turns never see each other's transcript.
    """
    agent_id = spec.agent_id or spec.run_id
    sink.emit(run_started(spec.run_id, agent_id, parent_run_id=None, kind=spec.kind))
    # 上下文传递可视化 (CEO 侧 通道①): ship the captain's opening context right after its
    # run_started so the chat bubble's「收到的上下文」lights up — every fold routes a
    # captain run_context turn-level (kind=captain → captainContext), never onto a graph
    # node. The resume path passes None: the opening already rode the pre-pause segment,
    # and reading the workers' product back (通道⑤) is a separate ratchet.
    if received_blocks is not None:
        sink.emit(run_context(spec.run_id, agent_id, _context_block_payloads(received_blocks)))
    start = time.monotonic()
    token = captain_transcript.set(messages)
    # Mirrors the loop's cumulative spend so a hard captain failure still bills the
    # rounds that completed (B-deep 失败计费). NB: the captain runs raise_on_error=False,
    # so an LLM error RETURNS partial usage (priced on the COMPLETED path below); this
    # except only catches non-LLM crashes, where the mirror is the only record left.
    inflight: list[TokenUsage] = []
    # B2: react_loop appends FinishReason stamps here when the captain loop ends on a
    # non-default terminal path (DEGRADED / UNPRODUCTIVE / PAUSED, …). Chronological:
    # later stamps supersede earlier ones (e.g. unproductive early-stop then
    # force-finalize ask_user → PAUSED). resolve_finish_override takes the last.
    finish_override: list[FinishReason] = []
    try:
        with log_context(
            run_id=spec.run_id,
            agent_id=agent_id,
            cost_role="captain",
            persona="CEO",
        ):
            content, reasoning, usage, rounds = await react_loop(
                messages=messages,
                llm=llm,
                tools=tools,
                sink=sink,
                tool_context=tool_ctx,
                profile=profile,
                turn_model=turn_model,
                # The captain's content/reasoning stream to the bubble (engine defaults);
                # its tool-call ARGUMENT assembly (the big delegate 任务书, composed before
                # run_plan exists) rides a bubble-scoped tool_progress so it isn't invisible.
                on_tool_progress=lambda tool, chars: sink.emit(tool_progress(tool, chars)),
                citation_sink=citation_sink,
                annotate_citations=True,
                turn_evidence_ledger=turn_evidence_ledger,
                ledger_registrant="ceo",
                approval_gate=approval_gate,
                usage_sink=inflight,
                finish_override_sink=finish_override,
                run_id=spec.run_id,
                role="captain",
                # 交付正文只留最终交付、旁白入 journal (Fork-B): the CEO bubble's persisted
                # content (→ messages.content + MessageFinalFact + next-turn history) drops
                # the prose written before a non-terminal tool call (process narration /
                # steer acknowledgements). Captain-only: its content is NOT reload-synthesized
                # from message_final (unlike workers), so this stays conformance-neutral —
                # the live content_delta stream the folds/oracle read is untouched.
                deliverable_only=True,
                supports_tools=supports_tools,
                controller_seed=controller_seed,
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        usage_dict = usage.as_dict()
        cost = asdict(calculate_cost(turn_model, usage))
        # 执行级事件溯源 (§8.3): the captain's FULL reply (vs the run_completed
        # summary) so the turn's reply is reconstructable from the journal alone.
        record_turn_fact(
            MessageFinalFact(run_id=spec.run_id, content=content, reasoning=reasoning).to_fact()
        )
        sink.emit(
            run_completed(
                spec.run_id,
                agent_id,
                # The captain IS the chat bubble: its full reply is streamed live + persisted
                # (MessageFinalFact above) and rendered in full, so its run_completed carries no
                # display summary — no truncation, no debrief (the CEO authors no 交接简报).
                output_summary="",
                duration_ms=duration_ms,
                role="captain",
                model=turn_model,
                usage=usage_dict,
                cost=cost,
            )
        )
        return RunState(
            phase=RunPhase.COMPLETED,
            content=content,
            reasoning=reasoning,
            model=turn_model,
            duration_ms=duration_ms,
            rounds=rounds,
            usage=usage_dict,
            cost=cost,
            finish_override=resolve_finish_override(finish_override),
            received_context=received_blocks or [],
        )
    except Exception as e:  # noqa: BLE001 — surface any captain failure to UI/state
        duration_ms = int((time.monotonic() - start) * 1000)
        partial = inflight[0] if inflight else TokenUsage()
        logger.error("run.captain_failed", run_id=spec.run_id, error=str(e), exc_info=True)
        sink.emit(run_failed(spec.run_id, agent_id, str(e)))
        return _priced_failure(
            str(e),
            model=turn_model,
            usage=partial,
            rounds=0,
            duration_ms=duration_ms,
        )
    finally:
        captain_transcript.reset(token)

"""Split from executor.py — see executor.py module docstring."""

from __future__ import annotations

import time
from dataclasses import asdict, replace

from agentcore.config import settings
from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.llm.pricing import calculate_cost
from agentcore.llm.profiles import TurnProfiles as ProfileSet
from agentcore.llm.profiles import default_turn_profiles as default_profile_set
from agentcore.llm.provider.protocol import LLMMessage, LLMProvider, TokenUsage
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.debate.speech_pipeline import (
    research_continuation_message,
    research_then_draft,
)
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    run_completed,
    run_context,
    run_failed,
    run_started,
)
from agentcore.runtime.facts import MessageFinalFact, RunHeadFact, record_turn_fact
from agentcore.runtime.runs.contract import check_contract, needs_file_contents
from agentcore.runtime.runs.executor_context import (
    _context_block_payloads,
    _load_artifact_contents,
    _safe_index_files,
    ensure_design_md_for_web_quality,
    load_web_seam_scope_contents,
)
from agentcore.runtime.runs.executor_shared import (
    _apply_cutoff_reasons,
    _apply_finish_interrupt,
    _continuation_message,
    _priced_failure,
    _react_and_capture,
)
from agentcore.runtime.runs.serialize import debrief_from_transcript, files_touched_from_transcript
from agentcore.runtime.runs.session import RunSession
from agentcore.runtime.runs.types import ContextBlock, RunPhase, RunState
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry

logger = get_logger(__name__)


def _strip_historical_reasoning(transcript: list[LLMMessage]) -> list[LLMMessage]:
    """Drop prior-beat ``reasoning_content`` before continue_run replays transcript.

    DeepSeek ignores historical reasoning across turns; keeping it only wastes input
    tokens. Copies via ``replace`` so the stored session transcript is untouched until
    the continuation result is committed. Within this beat, ``react_loop`` still
    records reasoning on new tool-call turns; ``openai_compatible`` echoes those (or
    pads ``""`` when omitted) — historical tool-call turns with ``None`` after strip
    get the same empty-string pad at payload time.
    """
    out: list[LLMMessage] = []
    for m in transcript:
        if m.role == "assistant" and m.reasoning_content is not None:
            out.append(replace(m, reasoning_content=None))
        else:
            out.append(m)
    return out


def _record_continuation_run_head(
    run_id: str,
    messages: list[LLMMessage],
    *,
    from_context_blocks: bool,
) -> None:
    """Journal this continuation beat's window head (system + just-appended user).

    Diagnostic ``window_from_journal(run_id=…)`` uses this instead of the turn-level
    CEO ``turn_started``. When the beat's user was assembled from structured
    ``context_blocks``, tag ``user_origin=context_blocks`` so the UI can substitute
    those segments for the concatenated body.
    """
    system_prompt = ""
    for msg in messages:
        if msg.role == "system":
            system_prompt = msg.content or ""
            break
    user_message = ""
    for msg in reversed(messages):
        if msg.role == "user":
            user_message = msg.content or ""
            break
    record_turn_fact(
        RunHeadFact(
            run_id=run_id,
            system_prompt=system_prompt,
            user_message=user_message,
            user_origin="context_blocks" if from_context_blocks else "",
        ).to_fact()
    )


async def continue_run(
    *,
    session: RunSession,
    feedback: str,
    continuation_run_id: str,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    base_tool_context: ToolContext,
    execution_id: str,
    profile_set: ProfileSet | None = None,
    approval_gate: ApprovalGate | None = None,
    round_no: int = 0,
    side_key: str | None = None,
    context_blocks: list[ContextBlock] | None = None,
    parent_run_id: str | None = None,
    draft_brief: str | None = None,
    draft_system: str | None = None,
    allow_research: bool | None = None,
    evidence_ledger: object | None = None,
    check_evidence_ledger: bool = False,
    allowed_ledger_ids: frozenset[str] | None = None,
    cost_role: str = "member",
) -> RunState:
    """续写 a saved worker session under the continuation's log scope.

    ``continues_run_id`` on the wire is always the session root (``session.run_id``);
    ``parent_run_id`` is the true delegation parent (captain / moderator), not the
    continued run. ``round_no`` / ``side_key`` (辩论逐轮) ride ``run_started`` so
    every fold reads 第几轮/哪一方 from the wire (no run_id regex).

    ``context_blocks`` surface on ``run_context`` (用户看到的 == 结构化展示)；LLM 侧
    吃的是 ``feedback`` 经统一续干模板追加进 transcript 的内容。

    辩手两阶段：当 ``session.spec.research_then_draft`` 且提供 ``draft_brief`` 时走
    检索→成稿；``allow_research=False``（结辩）退化为单次成稿。
    成稿证据台账 id 闸（见 speech_pipeline）：``check_evidence_ledger`` + ``evidence_ledger``
    在立论续写 / 质询 / 结辩全 beat 启用；结辩经 ``allowed_ledger_ids`` 传入本方历轮已引用并集。
    辩论检索 token 顶取统一 ``engine_worker_token_ceiling``（≤0 关闭；显式
    ``spec.token_ceiling`` 优先）。

    ``cost_role`` defaults to ``member`` (组队 revise / 续派); debate callers pass
    ``arena`` so sidecar proxy + model fallback keep the turn main model.
    """
    with log_context(
        run_id=continuation_run_id,
        agent_id=continuation_run_id,
        depth=session.spec.depth,
        cost_role=cost_role,
        persona=(session.spec.role or "").strip() or None,
        parent_run_id=(
            parent_run_id
            if parent_run_id is not None
            else (session.spec.parent_run_id or None)
        ),
    ):
        return await _continue_run_scoped(
            session=session,
            feedback=feedback,
            continuation_run_id=continuation_run_id,
            llm=llm,
            tools=tools,
            sink=sink,
            base_tool_context=base_tool_context,
            execution_id=execution_id,
            profile_set=profile_set,
            approval_gate=approval_gate,
            round_no=round_no,
            side_key=side_key,
            context_blocks=context_blocks,
            parent_run_id=parent_run_id,
            draft_brief=draft_brief,
            draft_system=draft_system,
            allow_research=allow_research,
            evidence_ledger=evidence_ledger,
            check_evidence_ledger=check_evidence_ledger,
            allowed_ledger_ids=allowed_ledger_ids,
            cost_role=cost_role,
        )


async def _continue_run_scoped(
    *,
    session: RunSession,
    feedback: str,
    continuation_run_id: str,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    base_tool_context: ToolContext,
    execution_id: str,
    profile_set: ProfileSet | None = None,
    approval_gate: ApprovalGate | None = None,
    round_no: int = 0,
    side_key: str | None = None,
    context_blocks: list[ContextBlock] | None = None,
    parent_run_id: str | None = None,
    draft_brief: str | None = None,
    draft_system: str | None = None,
    allow_research: bool | None = None,
    evidence_ledger: object | None = None,
    check_evidence_ledger: bool = False,
    allowed_ledger_ids: frozenset[str] | None = None,
    cost_role: str = "member",
) -> RunState:
    """续写 a saved worker session: same author, extended transcript, new run id."""
    profiles = profile_set or default_profile_set()
    spec = session.spec
    agent_id = continuation_run_id
    wire_parent = (
        parent_run_id if parent_run_id is not None else session.spec.parent_run_id
    )
    # 星型：continues_run_id 恒指现场根（RunSession 键）。
    sink.emit(
        run_started(
            continuation_run_id,
            agent_id,
            parent_run_id=wire_parent,
            kind=spec.kind,
            continues_run_id=session.run_id,
            stance=spec.stance or None,
            group=spec.group or None,
            round_no=round_no,
            side_key=side_key,
        )
    )
    if context_blocks:
        sink.emit(
            run_context(continuation_run_id, agent_id, _context_block_payloads(context_blocks))
        )
    start = time.monotonic()
    inflight: list[TokenUsage] = []
    priced_model: str | None = None
    try:
        profile = profiles.agent()
        from agentcore.runtime.costing import resolve_run_models

        priced_model, request_model = resolve_run_models(
            profiles, spec.model, cost_role=cost_role
        )
        from agentcore.runtime.runs.retrieval_budget import RETRIEVAL_TOOL_NAMES
        from agentcore.tools.protocol import RetrievalBudgetState

        tool_ctx = replace(
            base_tool_context,
            run_id=continuation_run_id,
            agent_id=agent_id,
            execution_id=execution_id,
            retrieval_budget=(
                RetrievalBudgetState(limit=spec.retrieval_budget)
                if spec.retrieval_budget is not None
                else None
            ),
        )
        # C3: continuations must consult the same ownership ledger as cold workers.
        # Treat the continued session root as an ancestor so write-time handoff matches
        # dispatch-time transfer (continue_from → new run_id).
        from agentcore.workspace.write_claims import resolve_write_coordinator

        coord = resolve_write_coordinator(
            execution_id=execution_id,
            fallback=getattr(base_tool_context, "write_coordinator", None),
        )
        prior_anc: frozenset[str] = frozenset(
            getattr(base_tool_context, "write_ancestors", frozenset()) or ()
        )
        tool_ctx = replace(
            tool_ctx,
            write_coordinator=coord,
            write_ancestors=frozenset(set(prior_anc) | {session.run_id}),
        )
        messages = _strip_historical_reasoning(session.transcript)
        citations: list[dict] = []
        worker_tools = tools
        allowed_tools = spec.tools
        if spec.deliverable is not None and spec.deliverable.form == "prose":
            from agentcore.runtime.runs.executor_identities import (
                PROSE_WITHHELD_WRITE_TOOLS,
            )
            from agentcore.runtime.runs.executor_shared import _registry_without

            worker_tools = _registry_without(tools, *PROSE_WITHHELD_WRITE_TOOLS)
            if allowed_tools is not None:
                withheld = set(PROSE_WITHHELD_WRITE_TOOLS)
                allowed_tools = [t for t in allowed_tools if t not in withheld]
            tool_ctx = replace(tool_ctx, withheld_write_tools="prose")
        if spec.retrieval_budget == 0:
            from agentcore.runtime.runs.executor_shared import _registry_without

            worker_tools = _registry_without(worker_tools, *RETRIEVAL_TOOL_NAMES)
            if allowed_tools is not None:
                allowed_tools = [t for t in allowed_tools if t not in RETRIEVAL_TOOL_NAMES]
        finish_override: list[FinishReason] = []
        cutoff_reasons: list[str] = []
        tool_failures: list[dict] = []
        from agentcore.runtime.suspension import turn_evidence_ledger as _turn_ledger_var

        use_two_phase = bool(
            spec.research_then_draft and (draft_brief or "").strip()
        )
        if use_two_phase:
            do_research = True if allow_research is None else bool(allow_research)
            if do_research:
                messages.append(research_continuation_message(feedback))
            else:
                # 结辩等无检索 beat：transcript 仍记任务，成稿走干净上下文。
                messages.append(LLMMessage(role="user", content=feedback))
            _record_continuation_run_head(
                continuation_run_id, messages, from_context_blocks=bool(context_blocks)
            )
            if settings.engine_worker_token_ceiling <= 0:
                debate_budget = 0
            elif spec.token_ceiling is not None and spec.token_ceiling > 0:
                debate_budget = spec.token_ceiling
            else:
                debate_budget = settings.engine_worker_token_ceiling
            content, reasoning, round_usage, round_rounds = await research_then_draft(
                messages,
                llm=llm,
                tools=worker_tools,
                sink=sink,
                tool_ctx=tool_ctx,
                profile=profile,
                turn_model=request_model,
                allowed_tools=allowed_tools if do_research else [],
                run_id=continuation_run_id,
                agent_id=agent_id,
                citation_sink=citations,
                approval_gate=approval_gate,
                draft_system=(
                    (draft_system or "").strip()
                    or (spec.draft_system or "").strip()
                    or (spec.system_prompt_supplement or "")
                ),
                draft_brief=(draft_brief or "").strip(),
                allow_research=do_research,
                usage_sink=inflight,
                finish_override_sink=finish_override,
                cutoff_reason_sink=cutoff_reasons,
                evidence_ledger=evidence_ledger,  # type: ignore[arg-type]
                side_key=side_key or "",
                check_evidence_ledger=check_evidence_ledger,
                allowed_ledger_ids=allowed_ledger_ids,
                token_budget=debate_budget if do_research else 0,
            )
        else:
            messages.append(_continuation_message(feedback))
            _record_continuation_run_head(
                continuation_run_id, messages, from_context_blocks=bool(context_blocks)
            )
            content, reasoning, round_usage, round_rounds = await _react_and_capture(
                messages,
                llm=llm,
                tools=worker_tools,
                sink=sink,
                tool_ctx=tool_ctx,
                profile=profile,
                turn_model=request_model,
                allowed_tools=allowed_tools,
                run_id=continuation_run_id,
                agent_id=agent_id,
                citation_sink=citations,
                approval_gate=approval_gate,
                usage_sink=inflight,
                finish_override_sink=finish_override,
                cutoff_reason_sink=cutoff_reasons,
                tool_failure_sink=tool_failures,
                turn_evidence_ledger=_turn_ledger_var.get(),
                ledger_registrant=f"worker:{agent_id}",
                form_prose=(
                    spec.deliverable is not None and spec.deliverable.form == "prose"
                ),
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        usage = round_usage.as_dict()
        cost = asdict(calculate_cost(priced_model, round_usage))
        touched_for_gate = files_touched_from_transcript(messages)
        deliverable = spec.deliverable
        artifact_contents = None
        workspace_paths = list(touched_for_gate)
        # 交付形态对齐: a continuation of a FILE deliverable re-checks the contract against
        # the landed files too (same semantics as the cold executor), so a file-form draft
        # the author corrects on disk is not re-failed for「缺章节 / 太短」on empty prose.
        load_contents = needs_file_contents(
            deliverable,
            landed_paths=touched_for_gate,
        )
        if deliverable and deliverable.artifacts:
            live_index = await _safe_index_files(tool_ctx.backend)
            workspace_paths = list(dict.fromkeys([*live_index, *touched_for_gate]))
            if load_contents:
                patterns = list(
                    dict.fromkeys([*deliverable.artifacts, *touched_for_gate])
                )
                artifact_contents = await _load_artifact_contents(
                    tool_ctx.backend,
                    patterns,
                    workspace_paths,
                )
        elif touched_for_gate and load_contents:
            artifact_contents = await _load_artifact_contents(
                tool_ctx.backend,
                touched_for_gate,
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
        turn_ledger = _turn_ledger_var.get()
        verdict = check_contract(
            content,
            deliverable,
            files_written=len(touched_for_gate),
            debrief=debrief_from_transcript(messages),
            workspace_paths=workspace_paths,
            artifact_contents=artifact_contents,
            ledger_entries=(
                turn_ledger.all_entries() if turn_ledger is not None else None
            ),
            citable_ids=(
                turn_ledger.draft_citable_ids() if turn_ledger is not None else None
            ),
        )
        record_turn_fact(
            MessageFinalFact(
                run_id=continuation_run_id, content=content, reasoning=reasoning
            ).to_fact()
        )
        debrief = debrief_from_transcript(messages)
        touched = files_touched_from_transcript(messages)
        warnings = [] if verdict.ok else list(verdict.failures)
        warnings, debrief = _apply_finish_interrupt(
            finish_override,
            warnings=warnings,
            debrief=debrief,
            content=content,
            files_touched=touched,
            run_id=continuation_run_id,
        )
        warnings = _apply_cutoff_reasons(cutoff_reasons, warnings=warnings)
        sink.emit(
            run_completed(
                continuation_run_id,
                agent_id,
                output_summary=(debrief or {}).get("summary", ""),
                duration_ms=duration_ms,
                role="member",
                model=priced_model,
                usage=usage,
                cost=cost,
                debrief=debrief,
                output_files=touched or None,
            )
        )
        return RunState(
            phase=RunPhase.COMPLETED,
            content=content,
            reasoning=reasoning,
            warnings=warnings,
            citations=citations,
            model=priced_model,
            duration_ms=duration_ms,
            rounds=round_rounds,
            files_touched=touched,
            tool_failures=list(tool_failures),
            debrief=debrief,
            usage=usage,
            cost=cost,
            transcript=messages,
        )
    except Exception as e:  # noqa: BLE001 — surface any continuation failure to UI/state
        duration_ms = int((time.monotonic() - start) * 1000)
        partial = inflight[0] if inflight else TokenUsage()
        logger.error(
            "run.continuation_failed", run_id=continuation_run_id, error=str(e), exc_info=True
        )
        sink.emit(run_failed(continuation_run_id, agent_id, str(e)))
        return _priced_failure(
            str(e),
            model=priced_model,
            usage=partial,
            rounds=0,
            duration_ms=duration_ms,
        )
    finally:
        # Browser B: same run-bind release as executor_node (continuation uses a new run id).
        try:
            from agentcore.runtime.browser.registry import default_browser_session_registry

            default_browser_session_registry().unbind_run(continuation_run_id)
        except Exception:  # noqa: BLE001 - teardown must not fail the continuation path
            logger.warning("browser.unbind_run_failed", run_id=continuation_run_id)

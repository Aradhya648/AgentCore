"""ReAct loop convergence governance: investigation classification, circuit breaker, nudges."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.llm.provider.protocol import LLMMessage, ToolCall
from agentcore.runtime.events import FinishReason
from agentcore.runtime.facts import NoteFact, record_turn_fact
from agentcore.runtime.loop_controller import (
    Intervention,
    LoopController,
    ToolAttempt,
    progress_review_prompt,
)
from agentcore.tools.registry import ToolRegistry

from .constants import FINALIZE_COORDINATION_TOOLS, FINALIZE_PERSIST_TOOLS
from .directive import Continue, Finalize, LoopDirective, Return
from .outcome import RoundOutcome

logger = get_logger(__name__)

# Team-gate (协作优先): investigation-only, captain-only, one shot per run.
# ≥ TEAM_GATE_INVESTIGATION_THRESHOLD **探路轮** → always hard-stop
# (strip investigation tools). 按轮不计同轮并行工具次数——一轮里 git×2+file_list
# 只计 1 轮，避免并行烧尽额度。No soft nudge.
# **不扫用户原文猜意图**分叉闸门（禁成篇/改文件/摸底正则路径）；统一文案：
# delegate 或短答+自报归类；闸后长文由 soft_gates 丢稿再催一次。
# 成篇形状 / 修码选型靠提示词与结构验收（playbook、冷启动拒单 worker 等），不靠分类器。
TEAM_GATE_INVESTIGATION_THRESHOLD = 5
# 本地摸仓计数仍由 LoopController 维护（观测 / probe）；不再用于分阈硬闸。
LOCAL_RECON_TOOLS = frozenset({"file_list", "file_read", "grep"})


def team_gate_hard_stop_prompt() -> str:
    """Hard gate: investigation tools stripped; delegate or short classified answer."""
    n = TEAM_GATE_INVESTIGATION_THRESHOLD
    return (
        f"[系统提示] 探路已达硬上限（{n} 轮）：调查类工具已收回。"
        "请立即 delegate（成规模摸底 / 成篇调研须 ≥2 角并行，禁止一人包办）；"
        "若坚持直答，仅限短答并写明归类理由（闲聊/单点事实/追问）；"
        "禁止长文直答交差；禁止再搜 / 再读。"
    )


# 闸后长文再催：字符阈值；短答放行（归类由提示约束，引擎不扫正文做意图分类）。
TEAM_GATE_DIRECT_REJECT_MIN_CHARS = 400


def team_gate_direct_reject_prompt() -> str:
    """One-shot reject after team_gate when wrap-up prose is too long."""
    return (
        "[系统提示] 探路硬闸后禁止长文直答：刚才的长文草稿已丢弃。"
        "请立即 delegate，或短答并写明归类（闲聊/单点事实/追问）；禁止再搜 / 再读。"
    )


def should_team_gate_direct_reject(
    controller: LoopController,
    *,
    role: str,
    content: str,
) -> bool:
    """Whether to discard a post-gate long wrap-up and re-nudge once."""
    if role != "captain" or not controller.team_gate_fired:
        return False
    if controller.team_gate_direct_reject_fired or controller.has_delegated:
        return False
    return len((content or "").strip()) >= TEAM_GATE_DIRECT_REJECT_MIN_CHARS


def maybe_inject_team_gate_direct_reject(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
    content: str,
) -> bool:
    """Inject one-shot direct-answer reject after team_gate. Returns True if injected."""
    if not should_team_gate_direct_reject(controller, role=role, content=content):
        return False
    controller.mark_team_gate_direct_reject_fired()
    nudge = team_gate_direct_reject_prompt()
    logger.info(
        "engine.team_gate_nudge",
        trigger="direct_reject",
        round=round_idx,
        hard_stop=False,
        direct_reject=True,
        content_chars=len((content or "").strip()),
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="team_gate", run_id=run_id).to_fact()
    )
    return True


def _user_intent_chunks(messages: list[LLMMessage]) -> list[str]:
    """Real user turns only (skip system nudges / short affirmations)."""
    from agentcore.runtime.kickoff import is_short_affirmation

    chunks: list[str] = []
    for msg in messages:
        if msg.role != "user" or not msg.content:
            continue
        text = msg.content.strip()
        if not text or text.startswith("[系统提示]"):
            continue
        if is_short_affirmation(text):
            continue
        chunks.append(text)
    return chunks


def maybe_inject_availability_status_nudge(
    *,
    messages: list[LLMMessage],
    run_id: str,
    role: str = "",
) -> bool:
    """可用性诚实性 · 甲：偏窄短问 → 注入「主答=卡」纪律（一次，船长路径）。

    Reinject of the delivery card happens earlier in assemble; this nudge steers the
    CEO prose to stay commentary-only. Returns True when injected.
    """
    if role != "captain":
        return False
    chunks = _user_intent_chunks(messages)
    if not chunks:
        return False
    from agentcore.runtime.delegate.delivery_status import (
        availability_status_nudge_prompt,
        is_availability_status_question,
    )

    if not is_availability_status_question(chunks[-1]):
        return False
    nudge = availability_status_nudge_prompt()
    logger.info("engine.availability_status_nudge", run_id=run_id or None)
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(
            role="user", content=nudge, reason="availability_status", run_id=run_id
        ).to_fact()
    )
    return True


def maybe_inject_team_gate(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
    trigger: Literal["investigation"] = "investigation",
    disabled_tools: set[str] | None = None,
    investigation_tools: frozenset[str] | None = None,
) -> bool:
    """Inject the team-gate once for the CEO captain. Returns True if injected.

    After :data:`TEAM_GATE_INVESTIGATION_THRESHOLD` **探路轮**
    (``investigation_rounds``; 同轮并行多工具只计 1), strip investigation tools and
    inject one hard-stop copy: delegate or short classified answer. Does **not**
    branch on user-text intent classifiers.
    """
    if role != "captain" or controller.team_gate_fired or controller.has_delegated:
        return False

    if controller.investigation_rounds < TEAM_GATE_INVESTIGATION_THRESHOLD:
        return False

    controller.mark_team_gate_fired()
    if disabled_tools is not None and investigation_tools:
        disabled_tools.update(investigation_tools)
    nudge = team_gate_hard_stop_prompt()
    logger.info(
        "engine.team_gate_nudge",
        trigger=trigger,
        round=round_idx,
        investigation_calls=controller.investigation_calls,
        investigation_rounds=controller.investigation_rounds,
        hard_stop=True,
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="team_gate", run_id=run_id).to_fact()
    )
    return True


def audit_gate_nudge_prompt() -> str:
    """One-shot soft audit gate: independent review then default close to user."""
    return (
        "[系统提示] 收尾前审计复核：本回合为成文专线/结构长文，须经独立审计"
        "（审计者≠作者）。默认派 1 名审计员读落盘成稿；重要材料可用 2-3 透镜分工。"
        "独立审计完成后，默认向用户收口汇报结论与成稿状态——"
        "同轮用 continue_from_run_id 唤回原作者修订不是默认路径"
        "（仅当用户明示要改，或审计暴露硬缺口且收口会交残稿时才再派修订）。"
        "禁止把「审完默认修订≤2 轮」当流程。"
        "系统只提示、绝不代派；此后不再打扰。"
    )


def audit_gate_hard_prompt() -> str:
    """Hard audit gate for research_report / structured long-form deliverables."""
    return (
        "[系统提示] 成篇审计硬门：本回合含成文专线 playbook=research_report "
        "或 deliverable 结构成篇信号（如 min_length≥3000），"
        "收尾前【必须】派独立审计员（审计者≠作者）审校落盘成稿，"
        "或用 playbook=research_report（内含审校）完成路径。"
        "对齐推进 playbook=parallel_brief / 普通多角摸底不进本门（软闸亦同）。"
        "禁止在仅收到软提示后直接 end_turn 把半残稿当完结。"
        "审后默认向用户收口；continue_from_run_id 修订非默认路径。"
        "若本批已含审校节点或你已另派审计，请继续交付；"
        "否则请先 delegate 审计员。"
        "系统不代派，但本门未满足前不会放行收尾。"
    )


def should_audit_gate(controller: LoopController, *, role: str) -> bool:
    """Whether the soft audit gate should fire (wrap-up or all_completed path).

    Soft nudge aligns with the hard gate: only research_report / structured
    long-form (``audit_hard_required``). ``parallel_brief`` / ordinary multi-angle
    scouting never enter the soft gate.
    """
    if role != "captain" or controller.audit_gate_fired:
        return False
    if not controller.audit_hard_required:
        return False
    # Turn ceiling hit → new audit dispatch is rejected; don't push CEO to re-delegate.
    from agentcore.runtime.turn_token_budget import is_turn_token_ceiling_hit

    if is_turn_token_ceiling_hit():
        return False
    return controller.delegate_count == 1 and controller.first_batch_substantial


def should_audit_hard_block(controller: LoopController, *, role: str) -> bool:
    """True when hard audit gate must block end_turn after the soft nudge."""
    if role != "captain":
        return False
    if not controller.audit_hard_required:
        return False
    if controller.audit_includes_review:
        return False
    # Soft nudge must have fired first (one Continue cycle), then hard-block.
    if not controller.audit_gate_fired:
        return False
    from agentcore.runtime.turn_token_budget import is_turn_token_ceiling_hit

    if is_turn_token_ceiling_hit():
        return False
    # Still only one batch and no review wave → block.
    return controller.delegate_count < 2


def coordination_injection_has_all_completed(messages: list[LLMMessage]) -> bool:
    """True when a coordination inject batch includes the all_completed event."""
    return any(
        m.role == "user" and m.content and "all_completed" in m.content for m in messages
    )


def maybe_inject_audit_gate(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
) -> bool:
    """Inject the soft audit-gate nudge once for the CEO captain. Returns True if injected."""
    if not should_audit_gate(controller, role=role):
        return False

    controller.mark_audit_gate_fired()
    # research_report 自带审校 → 软提示后即视为审校满足，不进入硬门死循环。
    if controller.audit_includes_review:
        nudge = audit_gate_nudge_prompt()
    elif controller.audit_hard_required:
        nudge = audit_gate_hard_prompt()
    else:
        nudge = audit_gate_nudge_prompt()
    logger.info(
        "engine.audit_gate_nudge",
        round=round_idx,
        delegate_count=controller.delegate_count,
        first_batch_substantial=controller.first_batch_substantial,
        audit_hard=controller.audit_hard_required,
        includes_review=controller.audit_includes_review,
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="audit_gate", run_id=run_id).to_fact()
    )
    return True


def maybe_inject_audit_hard_block(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
) -> bool:
    """Block end_turn when hard audit is still unsatisfied after soft nudge."""
    if not should_audit_hard_block(controller, role=role):
        return False
    nudge = audit_gate_hard_prompt()
    logger.info(
        "engine.audit_gate_hard_block",
        round=round_idx,
        delegate_count=controller.delegate_count,
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(
            role="user", content=nudge, reason="audit_gate_hard", run_id=run_id
        ).to_fact()
    )
    return True


def should_debate_gate(
    controller: LoopController,
    *,
    role: str,
    messages: list[LLMMessage],
) -> bool:
    """Whether the soft debate-commitment gate should fire (wrap-up path)."""
    if role != "captain" or controller.debate_gate_fired or controller.debate_executed:
        return False
    from agentcore.runtime.turn_token_budget import is_turn_token_ceiling_hit

    if is_turn_token_ceiling_hit():
        return False
    from agentcore.runtime.engine.debate_commitment import user_selected_debate_form

    return user_selected_debate_form(messages)


def maybe_inject_debate_gate(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
) -> bool:
    """Inject the soft debate-commitment nudge once for the CEO captain."""
    if not should_debate_gate(controller, role=role, messages=messages):
        return False

    from agentcore.runtime.engine.debate_commitment import debate_gate_nudge_prompt

    controller.mark_debate_gate_fired()
    nudge = debate_gate_nudge_prompt()
    logger.info("engine.debate_gate_nudge", round=round_idx)
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="debate_gate", run_id=run_id).to_fact()
    )
    return True


def should_turn_token_budget_gate(controller: LoopController, *, role: str) -> bool:
    """Whether the turn-token wrap-up steer should fire (ceiling hit, captain, one-shot)."""
    if role != "captain" or controller.turn_token_budget_gate_fired:
        return False
    from agentcore.runtime.turn_token_budget import is_turn_token_ceiling_hit

    return is_turn_token_ceiling_hit()


def maybe_inject_turn_token_budget_gate(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
) -> bool:
    """Inject the turn-token wrap-up steer once for the CEO captain. Returns True if injected.

    Soft only: tools stay (delegate/debate already reject at execute). Does not
    force_finalize — reject copy + this one-shot steer is enough to push wrap-up.
    """
    if not should_turn_token_budget_gate(controller, role=role):
        return False

    from agentcore.runtime.turn_token_budget import (
        current_turn_tokens,
        resolve_turn_token_ceiling,
        turn_token_budget_wrap_prompt,
    )

    controller.mark_turn_token_budget_gate_fired()
    nudge = turn_token_budget_wrap_prompt()
    logger.info(
        "engine.turn_token_budget_nudge",
        round=round_idx,
        spent=current_turn_tokens(),
        ceiling=resolve_turn_token_ceiling(),
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(
            role="user", content=nudge, reason="turn_token_budget", run_id=run_id
        ).to_fact()
    )
    return True


# Successful returns that enter post-delegate synthesis mode (G5: live/resume symmetric).
_POST_DELEGATE_TOOLS = frozenset({"delegate", "debate"})


def note_delegate_batches(
    controller: LoopController,
    tool_calls: list[ToolCall],
    attempts: list[ToolAttempt],
) -> None:
    """Inform the controller of each successful delegate/debate batch's shape (post-return)."""
    for tc, attempt in zip(tool_calls, attempts, strict=False):
        if attempt.tool_name not in _POST_DELEGATE_TOOLS or not attempt.success:
            continue
        if attempt.tool_name == "debate":
            controller.mark_debate_executed()
        nodes = int(attempt.meta.get("batch_nodes") or 0)
        has_deps = bool(attempt.meta.get("batch_has_deps"))
        if nodes == 0:
            args = ""
            if tc is not None and getattr(tc, "function", None) is not None:
                args = tc.function.arguments or ""
            from agentcore.runtime.delegate.batch_shape import (
                batch_shape_from_arguments,
            )

            nodes, has_deps = batch_shape_from_arguments(args)
        controller.mark_post_delegate(
            node_count=nodes,
            has_deps=has_deps,
            audit_hard=bool(attempt.meta.get("audit_hard")),
            includes_review=bool(attempt.meta.get("batch_includes_review")),
        )


def classify_investigation_tools(
    tools: ToolRegistry,
    allowed_tool_names: list[str] | None,
) -> frozenset[str]:
    """Classify read-only info-gathering tools for over-investigation backstop."""
    available_names = (
        set(allowed_tool_names) if allowed_tool_names is not None else set(tools.names)
    )
    schema_by_name = {schema.name: schema for schema in tools.list_all()}
    investigation_tools: set[str] = set()
    for name in available_names:
        schema = schema_by_name.get(name)
        if schema is None:
            continue
        if schema.approval is ToolApproval.NEVER and schema.category in (
            ToolCategory.FILESYSTEM,
            ToolCategory.SEARCH,
            ToolCategory.RESEARCH,
        ):
            investigation_tools.add(name)
    return frozenset(investigation_tools)


def create_loop_controller(
    investigation_tools: frozenset[str],
    *,
    seed: Mapping[str, Any] | None = None,
    files_expected: bool = False,
    short_write_posture: bool = False,
    tighten_verify_exec_thrash: bool = False,
    max_rounds: int | None = None,
    form_prose: bool = False,
    product_landing_artifacts: list[str] | tuple[str, ...] | None = None,
) -> LoopController:
    """Build per-run convergence controller from engine settings.

    ``seed`` restores cross-suspension latches (gates + validation path-stop /
    thrash; see :meth:`LoopController.apply_seed`); omit on a fresh turn.

    Zero-write / prose_idle mid-loop warn→FINALIZE is **retired** (always off).
    Delivery pressure stays on round/token hard ceilings + convergence spin;
    write_pass still grants persist tools when ``files_expected`` (seam B).

    Short ``max_rounds`` also pulls ``reflection_start_round`` earlier so the
    progress-review inject is not collinear with the hard ceiling.

    ``tighten_verify_exec_thrash`` (repair verify short posture): lower
    unproductive + tool-failure disable thresholds so same-fail / no-output
    ``code_execute`` ladders reach nudge→finalize sooner — still the same
    LoopController paths, not a parallel fuse.
    """
    _ = files_expected  # call-site seam; write_pass grant is outside this factory

    tool_failure_warn = settings.engine_tool_failure_warn
    tool_failure_disable = settings.engine_tool_failure_disable
    unproductive_threshold = settings.engine_unproductive_threshold
    if tighten_verify_exec_thrash:
        # Same ladders, earlier trip for verify-only short posture.
        tool_failure_disable = min(int(tool_failure_disable), 2)
        unproductive_threshold = min(int(unproductive_threshold), 2)

    reflection_start = int(settings.engine_reflection_start_round)
    if short_write_posture and max_rounds is not None and max_rounds > 0:
        # Leave ≥1 react round after inject before hard ceiling (max_rounds=4 → start 2).
        reflection_start = min(reflection_start, max(1, max_rounds - 2))

    controller = LoopController(
        empty_threshold=settings.engine_empty_response_threshold,
        tool_failure_warn=tool_failure_warn,
        tool_failure_disable=tool_failure_disable,
        unproductive_threshold=unproductive_threshold,
        reflection_start_round=reflection_start,
        reflection_interval=settings.engine_reflection_interval,
        convergence_finalize_rounds=settings.engine_convergence_finalize_rounds,
        convergence_spin_rounds=settings.engine_convergence_spin_rounds,
        # 零写 / prose_idle 整条已退役 — 不开计数与中途 FINALIZE。
        zero_write_finalize_rounds=0,
        prose_idle=False,
        form_prose=form_prose,
        investigation_tools=investigation_tools,
        product_landing_artifacts=product_landing_artifacts,
    )
    if seed:
        controller.apply_seed(seed)
    return controller


def resolve_openai_tool_defs(
    tools: ToolRegistry,
    allowed_tool_names: list[str] | None,
    disabled_tools: set[str],
) -> list[dict[str, Any]] | None:
    """Resolve OpenAI tool definitions minus circuit-broken tools."""
    if allowed_tool_names is None:
        candidates = tools.names if tools.count > 0 else []
    else:
        candidates = list(allowed_tool_names)
    candidates = [name for name in candidates if name not in disabled_tools]
    if not candidates:
        return None
    return tools.get_openai_definitions(candidates) or None


def finalize_allows_persist(
    tools: ToolRegistry,
    allowed_tool_names: list[str] | None,
    *,
    files_expected: bool = False,
    form_prose: bool = False,
) -> bool:
    """True when finalize should keep file_write+handoff (files-form / wind_down).

    Prose withhold (``form_prose`` or writes absent from registry) → coordination
    only. ``files_expected``催写/finalize grants persist when ``file_write`` is
    registered even if the explicit allowlist omitted it (least-privilege seam).
    """
    if form_prose or "file_write" not in tools.names:
        return False
    if files_expected:
        return True
    if allowed_tool_names is not None:
        return "file_write" in allowed_tool_names
    return True


def finalize_tool_allowlist(*, persist: bool) -> frozenset[str]:
    """Names offered on a forced-finalize round."""
    if persist:
        return FINALIZE_COORDINATION_TOOLS | FINALIZE_PERSIST_TOOLS
    return FINALIZE_COORDINATION_TOOLS


def resolve_finalize_coordination_tools(
    tools: ToolRegistry,
    allowed_tool_names: list[str] | None,
    disabled_tools: set[str],
    *,
    files_expected: bool = False,
    form_prose: bool = False,
) -> list[dict[str, Any]] | None:
    """OpenAI tool defs for a forced-finalize round.

    Default = coordination only. When the worker surface still offers ``file_write``
    (requires_files / form=files / wind_down), also keep ``file_write`` + ``handoff``
    so landing is possible — never strip persist tools then demand a final answer.
    """
    if allowed_tool_names is None:
        candidates = list(tools.names) if tools.count > 0 else []
    else:
        candidates = list(allowed_tool_names)
    persist = finalize_allows_persist(
        tools,
        allowed_tool_names,
        files_expected=files_expected,
        form_prose=form_prose,
    )
    allow = finalize_tool_allowlist(persist=persist)
    # ``allow`` is the sole gate: when persist is on it re-includes file_write.
    selected = [
        name for name in candidates if name in allow and name not in disabled_tools
    ]
    if persist:
        # Guarantee landing tools when registered (mirrors narrow_tools_for_wind_down
        # always keeping handoff even if the caller allow-list omitted it).
        for name in sorted(FINALIZE_PERSIST_TOOLS):
            if (
                name not in selected
                and name not in disabled_tools
                and name in tools.names
            ):
                selected.append(name)
    if not selected:
        return None
    return tools.get_openai_definitions(selected) or None


@dataclass(frozen=True)
class CircuitBreakerOutcome:
    """Result of applying the B2 tool-failure circuit breaker after a tool round."""

    message: str | None
    refresh_tool_defs: bool


def apply_circuit_breaker(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    disabled_tools: set[str],
) -> CircuitBreakerOutcome:
    """Retire wedged tools and inject a steer when the breaker trips."""
    from agentcore.runtime.loop_controller import FORCE_SEGMENTED_NARROW_TOOLS

    breaker = controller.tool_circuit_breaker()
    refresh = bool(breaker.disabled)
    if breaker.disabled:
        disabled_tools.update(breaker.disabled)
        from agentcore.runtime.audit.hooks import on_tool_disabled

        for tool_name in breaker.disabled:
            on_tool_disabled(
                tool_name=tool_name,
                run_id=run_id,
                failure_count=controller.tool_failure_count(tool_name),
            )
            # Persist read_url disable across react_loop restart (stream-stall →
            # Wave retry / contract write_pass). Same process + run_id.
            if tool_name == "read_url":
                from agentcore.tools.builtin.web._net import (
                    READ_URL_RETIRE_STEER,
                    mark_read_url_retired,
                )

                mark_read_url_retired(run_id, message=READ_URL_RETIRE_STEER)
    # force_segmented keeps the pen but narrows dangerous append thrashing
    # (file_append out; file_write / str_replace stay — not a full write lockout).
    if breaker.force_segmented:
        before = len(disabled_tools)
        disabled_tools.update(FORCE_SEGMENTED_NARROW_TOOLS)
        if len(disabled_tools) > before:
            refresh = True
    breaker_message = breaker.message()
    if breaker_message is not None:
        logger.info(
            "engine.tool_circuit_breaker",
            warned=list(breaker.warned),
            disabled=list(breaker.disabled),
            force_segmented=sorted(breaker.force_segmented),
            round=round_idx,
        )
        messages.append(LLMMessage(role="user", content=breaker_message))
        record_turn_fact(
            NoteFact(
                role="user",
                content=breaker_message,
                reason="circuit_breaker",
                run_id=run_id,
            ).to_fact()
        )
    return CircuitBreakerOutcome(message=breaker_message, refresh_tool_defs=refresh)


def decide_llm_failure(*, final_content: str) -> LoopDirective:
    reason = FinishReason.DEGRADED if final_content else FinishReason.ERROR
    logger.warning(
        "engine.llm_failed_terminal", reason=reason.value, has_content=bool(final_content)
    )
    return Return(finish_reason=reason)


def govern_after_tools(
    outcome: RoundOutcome,
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    round_idx: int,
    run_id: str,
    breaker_message: str | None,
    role: str = "",
    disabled_tools: set[str] | None = None,
    investigation_tools: frozenset[str] | None = None,
) -> LoopDirective:
    """Run post-tool convergence governance and return the next directive.

    Steers that keep the loop going (a stuck-loop nudge, a periodic reflection)
    are injected here as side effects on ``messages`` and resolve to ``Continue``;
    a hard stop resolves to ``Finalize`` (the caller forces one tool-free round).
    ``UNPRODUCTIVE`` is stamped via the Finalize directive's ``finish_reason``.
    Convergence and reflection are suppressed when the circuit breaker already
    steered this round (``breaker_message is not None``) so steers don't stack.
    """
    # Post-delegate investigation check (优化六: 委派后工具降级)
    if outcome.has_tool_calls:
        called_tool_names = {a.tool_name for a in outcome.attempts if a.tool_name}
        post_delegate_msg = controller.post_delegate_check(called_tool_names)
        if post_delegate_msg is not None:
            messages.append(LLMMessage(role="user", content=post_delegate_msg))
            record_turn_fact(
                NoteFact(
                    role="user", content=post_delegate_msg, reason="post_delegate", run_id=run_id
                ).to_fact()
            )

    controller.note_round_productivity(
        had_tool_calls=outcome.has_tool_calls,
        all_failed=outcome.all_tools_failed,
        had_content=bool(outcome.content),
        all_parse_failures=(
            bool(outcome.attempts)
            and all(not a.success for a in outcome.attempts)
            and all(a.parse_failure for a in outcome.attempts)
        ),
    )

    if controller.take_validation_hard_stop():
        # Same-fingerprint validation re-hit after path-stop steer — hard stop
        # before nudge/convergence so the run does not burn max_rounds.
        logger.warning(
            "engine.validation_thrash_stop",
            round=round_idx,
            attempts=len(outcome.attempts),
        )
        return Finalize(
            reason="validation_thrash", finish_reason=FinishReason.UNPRODUCTIVE
        )

    signal = controller.detect()
    action = controller.decide(signal)
    if signal is not None and action is Intervention.NUDGE:
        logger.info(
            "engine.loop_nudge",
            reason=signal.reason.value,
            tool=signal.tool_name,
            count=signal.count,
            round=round_idx,
        )
        reflection = signal.reflection_message()
        messages.append(LLMMessage(role="user", content=reflection))
        record_turn_fact(
            NoteFact(role="user", content=reflection, reason="nudge", run_id=run_id).to_fact()
        )
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id=run_id,
            round_idx=round_idx,
            role=role,
            trigger="investigation",
            disabled_tools=disabled_tools,
            investigation_tools=investigation_tools,
        )
        maybe_inject_turn_token_budget_gate(
            controller,
            messages=messages,
            run_id=run_id,
            round_idx=round_idx,
            role=role,
        )
        return Continue()

    if signal is not None and action is Intervention.FINALIZE:
        logger.warning(
            "engine.loop_finalize",
            reason=signal.reason.value,
            tool=signal.tool_name,
            count=signal.count,
            round=round_idx,
        )
        return Finalize(reason=signal.reason.value)

    if controller.unproductive_early_stop():
        logger.warning(
            "engine.unproductive_stop", round=round_idx, attempts=len(outcome.attempts)
        )
        return Finalize(reason="unproductive", finish_reason=FinishReason.UNPRODUCTIVE)

    if breaker_message is None and controller.convergence_action() is Intervention.FINALIZE:
        # Zero-write mid-loop DEGRADED is retired; spin / absolute-cap FINALIZE
        # stays plain convergence (hard-ceiling thrashing still stamps DEGRADED).
        logger.warning(
            "engine.convergence_finalize",
            round=round_idx,
            investigation_rounds=controller.investigation_rounds,
            investigation_calls=controller.investigation_calls,
        )
        return Finalize(reason="convergence")

    if breaker_message is None and controller.reflection_due(round_idx):
        review = progress_review_prompt(
            round_idx + 1, role=role, form_prose=controller.form_prose
        )
        logger.info("engine.reflection_inject", round=round_idx, role=role or "")
        messages.append(LLMMessage(role="user", content=review))
        record_turn_fact(
            NoteFact(role="user", content=review, reason="reflection", run_id=run_id).to_fact()
        )
        controller.mark_reflection_injected()

    maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
        trigger="investigation",
        disabled_tools=disabled_tools,
        investigation_tools=investigation_tools,
    )
    maybe_inject_turn_token_budget_gate(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
    )
    return Continue()

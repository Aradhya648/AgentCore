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
# ≥ TEAM_GATE_INVESTIGATION_THRESHOLD investigation tools → always hard-stop
# (strip investigation tools). No soft nudge. long_content 事后丢稿闸门已撤：
# 改由 CEO 提示词「路由·第一拍」在展开前显式表态（见 prompt._CEO_CORE_HINT）。
TEAM_GATE_INVESTIGATION_THRESHOLD = 3
# 本地改文件：允许多摸 1～2 次 file_list/file_read/grep，再硬催派（与网页独搜分阈）。
TEAM_GATE_LOCAL_EDIT_THRESHOLD = 2
LOCAL_RECON_TOOLS = frozenset({"file_list", "file_read", "grep"})


# 闸后形状（B）：成篇调研意图命中时追加——治「立刻 delegate」塌成 none+单人。
_TEAM_GATE_RESEARCH_SHAPE = (
    "【成篇调研形状】用户要落盘的中篇实务/研究报告且可多角取证 → "
    "下一拍 delegate【宜】`playbook=\"research_report\"`（`playbook_args`：topic + angles）"
    "或手写同构（≥2 角并行调研/讨论笔记 → 提纲 → 撰稿；各角与主笔均 "
    "`form=files`+`artifacts`）；"
    "【禁止】`playbook=none` 单 task 一人包办自搜+成文；"
    "【禁止】「角 prose、仅主笔落盘」。"
    "材料已齐仅扩写 / 短文落盘不适用本条。"
)


def team_gate_hard_stop_prompt(*, research_shape: bool = False) -> str:
    """Hard gate: investigation tools stripped; delegate or answer, no more recon."""
    n = TEAM_GATE_INVESTIGATION_THRESHOLD
    text = (
        f"[系统提示] 探路已达硬上限（{n} 次）：调查类工具已收回。"
        "请立即 delegate；若坚持直答，直接作答并给出归类理由"
        "（闲聊/单点事实/追问），禁止再搜 / 再读。"
    )
    if research_shape:
        text += _TEAM_GATE_RESEARCH_SHAPE
    return text


def team_gate_local_edit_prompt() -> str:
    """Hard gate for local file-edit recon: strip tools after a short peek."""
    n = TEAM_GATE_LOCAL_EDIT_THRESHOLD
    return (
        f"[系统提示] 本地改文件探路已够（已摸仓 ≥{n} 次）：调查类工具已收回。"
        "请立即 delegate：本地 runtime / 缺 export 等修码用 "
        "`complexity_hint=light`（可带 requires_files）或 "
        '`playbook="repair_code"`；禁止 none+满轮巡读、禁止继续 '
        "file_list / file_read / grep 空转。"
    )


def _research_shape_from_messages(messages: list[LLMMessage]) -> bool:
    """True when any real user turn asks for a research / practical long-form write-up.

    Must not key off the *latest* user line alone — kickoff settle ("认可" / continue)
    would otherwise erase the original research-report intent after ask_user.
    """
    from agentcore.runtime.kickoff import is_short_affirmation
    from agentcore.runtime.runs.research_quality import is_research_report_intent

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
    return is_research_report_intent(*chunks)


def _local_edit_from_messages(messages: list[LLMMessage]) -> bool:
    """True when any real user turn asks to tweak an existing workspace file."""
    from agentcore.runtime.kickoff import is_short_affirmation
    from agentcore.runtime.runs.research_quality import is_local_file_edit_intent

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
    return is_local_file_edit_intent(*chunks)


def _local_recon_call_count(controller: LoopController) -> int:
    """Run-scoped local peek count (file_list / file_read / grep)."""
    return int(controller.local_recon_calls)


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


def exec_verify_ask_prompt() -> str:
    """Hard gate: missing exec/browser/local_open or unclear artifact → ask_user only."""
    return (
        "[系统提示] 能力策略：用户要跑/修或打开验证，"
        "当前缺执行/浏览器/本机打开能力或可验产物路径不清。"
        "探路与委派工具已收回。请立即 ask_user（绑定/授权/请用户指路径或附文件）；"
        "禁止委派/翻目录冒充。"
    )


def exec_verify_ask_text_exit_prompt() -> str:
    """Ask terminal but no ask_user tool: force prose close (no card, no tool spin)."""
    return (
        "[系统提示] 能力策略：用户要跑/修或打开验证，当前缺执行/浏览器/本机打开能力，"
        "且本回合未装配 ask_user（无法开卡）。探路与委派工具已收回，工具面已清空。"
        "请用正文说明能力限制并立即结束；禁止再调工具、禁止委派/翻目录冒充。"
    )


def exec_verify_delegate_prompt() -> str:
    """Hard gate: has capability → delegate + code_verified only."""
    return (
        "[系统提示] 能力策略：用户要跑/修或打开验证，且本回合已装配对应执行能力。"
        "探路工具已收回。请立即 delegate，并显式 completion_criteria=code_verified；"
        "本地 runtime 错 / 单文件修码优先 `complexity_hint=light` 或 "
        '`playbook="repair_code"`（diagnose→patch→verify），'
        "禁止直答、翻目录收口或 none+满轮巡读。"
    )


def paste_writeback_delegate_prompt() -> str:
    """Hard gate: pasted code + write-back → delegate to disk (no verbal fix)."""
    return (
        "[系统提示] 能力策略：消息已贴代码且要求写回文件。"
        "探路工具已收回。请立即 delegate 落盘；禁止口述修复当直答。"
    )


def maybe_inject_exec_verify_gate(
    controller: LoopController,
    *,
    messages: list[LLMMessage],
    run_id: str,
    round_idx: int,
    role: str,
    code_execute: bool,
    browser: bool,
    local_open: bool = False,
    disabled_tools: set[str] | None = None,
    investigation_tools: frozenset[str] | None = None,
    ask_user_available: bool = True,
) -> bool:
    """Inject run/open/paste-writeback capability strategy once. Returns True if injected.

    Fires immediately on narrow intent (no recon threshold): strips investigation
    tools and steers terminal to ``ask_user`` or ``delegate`` (+code_verified when run/open).
    When terminal is ``ask_user`` but the live tool surface has no ``ask_user``,
    latches ``exec_verify_text_exit`` so the loop clears tools and forces prose close.
    """
    if (
        role != "captain"
        or controller.exec_verify_gate_fired
        or controller.has_delegated
        or controller.team_gate_fired
    ):
        return False

    chunks = _user_intent_chunks(messages)
    if not chunks:
        return False

    from agentcore.runtime.runs.exec_verify import (
        has_clear_verifiable_artifact_path,
        is_open_browser_verify_intent,
        is_open_local_app_intent,
        is_paste_writeback_intent,
        is_run_fix_script_intent,
        resolve_exec_verify_terminal,
    )

    run_fix = is_run_fix_script_intent(*chunks)
    open_verify = is_open_browser_verify_intent(*chunks)
    open_app = is_open_local_app_intent(*chunks)
    paste_writeback = is_paste_writeback_intent(*chunks)
    clear_path = has_clear_verifiable_artifact_path(*chunks)
    terminal = resolve_exec_verify_terminal(
        run_fix=run_fix,
        open_verify=open_verify,
        open_app=open_app,
        paste_writeback=paste_writeback,
        code_execute=code_execute,
        browser=browser,
        local_open=local_open,
        clear_artifact_path=clear_path,
    )
    if terminal is None:
        return False

    controller.mark_exec_verify_gate_fired()
    text_exit = terminal == "ask_user" and not ask_user_available
    if text_exit:
        controller.mark_exec_verify_text_exit()
    if disabled_tools is not None:
        if investigation_tools:
            disabled_tools.update(investigation_tools)
        # ask 终向：收回探路后仍可 delegate/debate 绕开（如派重建冒充打开）
        if terminal == "ask_user":
            disabled_tools.update(("delegate", "debate"))
    if paste_writeback and terminal == "delegate":
        nudge = paste_writeback_delegate_prompt()
    elif terminal == "delegate":
        nudge = exec_verify_delegate_prompt()
    elif text_exit:
        nudge = exec_verify_ask_text_exit_prompt()
    else:
        nudge = exec_verify_ask_prompt()
    logger.info(
        "engine.exec_verify_gate_nudge",
        round=round_idx,
        terminal=terminal,
        run_fix=run_fix,
        open_verify=open_verify,
        open_app=open_app,
        paste_writeback=paste_writeback,
        code_execute=code_execute,
        browser=browser,
        local_open=local_open,
        clear_artifact_path=clear_path,
        ask_user_available=ask_user_available,
        text_exit=text_exit,
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="exec_verify_gate", run_id=run_id).to_fact()
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

    Investigation path: after :data:`TEAM_GATE_INVESTIGATION_THRESHOLD` investigation
    tool calls, always strip investigation tools and inject hard-stop copy
    (delegate or 直答+归类理由; no more recon). ``research_shape`` only controls
    whether the research-report shape sentence is appended.

    Local file-edit intent is a separate light hard path: after
    :data:`TEAM_GATE_LOCAL_EDIT_THRESHOLD` local peeks, strip tools and催派 — not the
    web-solo-search knife.
    """
    if role != "captain" or controller.team_gate_fired or controller.has_delegated:
        return False

    research_shape = _research_shape_from_messages(messages)
    local_edit = (not research_shape) and _local_edit_from_messages(messages)
    local_calls = _local_recon_call_count(controller)

    if local_edit:
        if local_calls < TEAM_GATE_LOCAL_EDIT_THRESHOLD:
            return False
        controller.mark_team_gate_fired()
        if disabled_tools is not None and investigation_tools:
            disabled_tools.update(investigation_tools)
        nudge = team_gate_local_edit_prompt()
        logger.info(
            "engine.team_gate_nudge",
            trigger=trigger,
            round=round_idx,
            investigation_calls=controller.investigation_calls,
            local_recon_calls=local_calls,
            hard_stop=True,
            research_shape=False,
            local_edit=True,
        )
        messages.append(LLMMessage(role="user", content=nudge))
        record_turn_fact(
            NoteFact(role="user", content=nudge, reason="team_gate", run_id=run_id).to_fact()
        )
        return True

    if controller.investigation_calls < TEAM_GATE_INVESTIGATION_THRESHOLD:
        return False

    controller.mark_team_gate_fired()
    if disabled_tools is not None and investigation_tools:
        disabled_tools.update(investigation_tools)
    nudge = team_gate_hard_stop_prompt(research_shape=research_shape)
    logger.info(
        "engine.team_gate_nudge",
        trigger=trigger,
        round=round_idx,
        investigation_calls=controller.investigation_calls,
        hard_stop=True,
        research_shape=research_shape,
        local_edit=False,
    )
    messages.append(LLMMessage(role="user", content=nudge))
    record_turn_fact(
        NoteFact(role="user", content=nudge, reason="team_gate", run_id=run_id).to_fact()
    )
    return True


def audit_gate_nudge_prompt() -> str:
    """One-shot soft audit gate: remind about independent review; never auto-dispatch."""
    return (
        "[系统提示] 收尾前审计复核：请先自我归类——"
        "成篇/构建/审查类质量敏感成品须经独立审计（审计者≠作者）。"
        "默认派 1 名审计员；重要材料可用 2-3 透镜分工。"
        "成品以落盘文件交给审计员阅读；若发现问题，用 continue_from_run_id "
        "唤回原作者修订，再由审计员复核，≤2 轮。"
        "若确实不需要审计，给出归类理由后即可交付。"
        "系统只提示、绝不代派——派不派、派几个由你自主决定；此后不再打扰。"
    )


def audit_gate_hard_prompt() -> str:
    """Hard audit gate for research_report / word-count commitments."""
    return (
        "[系统提示] 成篇审计硬门：本回合含调研成篇 / 明确字数承诺，"
        "收尾前【必须】派独立审计员（审计者≠作者）审校落盘成稿，"
        "或用 playbook=research_report（内含审校）完成路径。"
        "禁止在仅收到软提示后直接 end_turn 把半残稿当完结。"
        "若本批已含审校节点或你已另派审计，请继续交付；"
        "否则请先 delegate 审计员。"
        "系统不代派，但本门未满足前不会放行收尾。"
    )


def should_audit_gate(controller: LoopController, *, role: str) -> bool:
    """Whether the soft audit gate should fire (wrap-up or all_completed path)."""
    if role != "captain" or controller.audit_gate_fired:
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
) -> LoopController:
    """Build per-run convergence controller from engine settings.

    ``seed`` restores the five cross-suspension latches (see
    :meth:`LoopController.apply_seed`); omit on a fresh turn.
    Zero-write thrashing enables only when ``files_expected`` **and**
    ``short_write_posture`` (light / repair / stamped short ``max_rounds``).
    Standard files workers keep it off — still bounded by convergence_spin /
    max_rounds / contract.
    """
    from agentcore.runtime.runs.worker_budget import should_enable_zero_write

    zero_write = (
        int(settings.engine_zero_write_finalize_rounds)
        if should_enable_zero_write(
            files_expected=files_expected,
            short_write_posture=short_write_posture,
        )
        else 0
    )
    controller = LoopController(
        empty_threshold=settings.engine_empty_response_threshold,
        tool_failure_warn=settings.engine_tool_failure_warn,
        tool_failure_disable=settings.engine_tool_failure_disable,
        unproductive_threshold=settings.engine_unproductive_threshold,
        reflection_start_round=settings.engine_reflection_start_round,
        reflection_interval=settings.engine_reflection_interval,
        convergence_finalize_rounds=settings.engine_convergence_finalize_rounds,
        convergence_spin_rounds=settings.engine_convergence_spin_rounds,
        zero_write_finalize_rounds=zero_write,
        investigation_tools=investigation_tools,
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
) -> bool:
    """True when finalize should keep file_write+handoff (files-form / wind_down).

    Inferred from the live tool surface: prose workers withhold ``file_write``, so
    they stay coordination-only; requires_files / form=files / wind_down keep it.
    """
    if allowed_tool_names is not None:
        return "file_write" in allowed_tool_names
    return "file_write" in tools.names


def finalize_tool_allowlist(*, persist: bool) -> frozenset[str]:
    """Names offered on a forced-finalize round."""
    if persist:
        return FINALIZE_COORDINATION_TOOLS | FINALIZE_PERSIST_TOOLS
    return FINALIZE_COORDINATION_TOOLS


def resolve_finalize_coordination_tools(
    tools: ToolRegistry,
    allowed_tool_names: list[str] | None,
    disabled_tools: set[str],
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
    persist = finalize_allows_persist(tools, allowed_tool_names)
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
    breaker_message = breaker.message()
    if breaker_message is not None:
        logger.info(
            "engine.tool_circuit_breaker",
            warned=list(breaker.warned),
            disabled=list(breaker.disabled),
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
    code_execute: bool = False,
    browser: bool = False,
    local_open: bool = False,
    ask_user_available: bool = True,
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
        maybe_inject_exec_verify_gate(
            controller,
            messages=messages,
            run_id=run_id,
            round_idx=round_idx,
            role=role,
            code_execute=code_execute,
            browser=browser,
            local_open=local_open,
            disabled_tools=disabled_tools,
            investigation_tools=investigation_tools,
            ask_user_available=ask_user_available,
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

    if breaker_message is None and controller.zero_write_warn_due():
        from agentcore.runtime.loop_controller import zero_write_warn_prompt

        warn = zero_write_warn_prompt(rounds=controller.zero_write_investigation_rounds)
        controller.mark_zero_write_warned()
        logger.info(
            "engine.zero_write_warn",
            round=round_idx,
            zero_write_rounds=controller.zero_write_investigation_rounds,
        )
        messages.append(LLMMessage(role="user", content=warn))
        record_turn_fact(
            NoteFact(role="user", content=warn, reason="zero_write_warn", run_id=run_id).to_fact()
        )

    if breaker_message is None and controller.convergence_action() is Intervention.FINALIZE:
        zero_write_cut = (
            not controller.landing_succeeded
            and controller.zero_write_finalize_rounds > 0
            and controller.zero_write_investigation_rounds
            >= controller.zero_write_finalize_rounds
        )
        if zero_write_cut:
            from agentcore.runtime.loop_controller import zero_write_finalize_prompt

            fin = zero_write_finalize_prompt(
                rounds=controller.zero_write_investigation_rounds
            )
            messages.append(LLMMessage(role="user", content=fin))
            record_turn_fact(
                NoteFact(
                    role="user", content=fin, reason="zero_write_finalize", run_id=run_id
                ).to_fact()
            )
        logger.warning(
            "engine.convergence_finalize",
            round=round_idx,
            investigation_rounds=controller.investigation_rounds,
            investigation_calls=controller.investigation_calls,
            zero_write_rounds=controller.zero_write_investigation_rounds,
            zero_write_cut=zero_write_cut,
        )
        # Mid-loop zero_write FINALIZE aligns with ceiling: DEGRADED + same source.
        if zero_write_cut:
            return Finalize(
                reason="convergence",
                finish_reason=FinishReason.DEGRADED,
            )
        return Finalize(reason="convergence")

    if breaker_message is None and controller.reflection_due(round_idx):
        review = progress_review_prompt(round_idx + 1, role=role)
        logger.info("engine.reflection_inject", round=round_idx, role=role or "")
        messages.append(LLMMessage(role="user", content=review))
        record_turn_fact(
            NoteFact(role="user", content=review, reason="reflection", run_id=run_id).to_fact()
        )

    maybe_inject_exec_verify_gate(
        controller,
        messages=messages,
        run_id=run_id,
        round_idx=round_idx,
        role=role,
        code_execute=code_execute,
        browser=browser,
        local_open=local_open,
        disabled_tools=disabled_tools,
        investigation_tools=investigation_tools,
        ask_user_available=ask_user_available,
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

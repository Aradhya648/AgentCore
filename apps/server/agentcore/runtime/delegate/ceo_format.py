"""CEO-facing synthesis input formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.runtime.delegate.plan_events import emit_captain_readback
from agentcore.runtime.events import content_delta
from agentcore.runtime.runs.constants import DELEGATE_OUTPUT_LIMIT
from agentcore.tools.protocol import ToolResult

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunState

DelegateTool = Any

logger = get_logger(__name__)


def _audit_off_with_token_budget_gap(
    plan: Any,
    gaps_by_worker: list[tuple[str, list[dict[str, str]]]] | list[tuple[str, list[str]]],
) -> bool:
    """True when any node has ``policy.audit=False`` and a token_budget delivery gap."""
    if not gaps_by_worker:
        return False
    has_token_budget = False
    for _label, gaps in gaps_by_worker:
        for gap in gaps:
            reason = ""
            if isinstance(gap, dict):
                reason = str(gap.get("reason") or "").strip()
            if reason == "token_budget":
                has_token_budget = True
                break
        if has_token_budget:
            break
    if not has_token_budget:
        return False
    for node in getattr(plan, "nodes", []) or []:
        policy = getattr(node, "policy", None)
        if policy is not None and not bool(getattr(policy, "audit", False)):
            return True
    return False


def _format_motion_card_block(role: str, card: dict[str, Any], *, run_id: str = "") -> str:
    """One worker's 命题卡 as a structured CEO-facing block."""
    form = str(card.get("form") or "debate")
    motion = str(card.get("motion") or "").strip()
    rationale = str(card.get("rationale") or "").strip()
    sides = card.get("sides") if isinstance(card.get("sides"), list) else []
    side_lines: list[str] = []
    for s in sides:
        if not isinstance(s, dict):
            continue
        key = str(s.get("key") or "").strip()
        name = str(s.get("name") or "").strip()
        stance = str(s.get("stance") or "").strip()
        if not (key and name and stance):
            continue
        side_lines.append(f"  - `{key}`（{name}）：{stance}")
    pointers = card.get("fact_pointers") if isinstance(card.get("fact_pointers"), list) else []
    ptr_text = "、".join(str(p).strip() for p in pointers if str(p).strip()) or "（无）"
    head = f"#### {role}"
    if run_id:
        head += f" · run_id: `{run_id}`"
    return "\n".join(
        [
            head,
            f"- **命题**：{motion}",
            f"- **形态**：{form}",
            "- **各方**：",
            *(side_lines or ["  - （无有效参与方）"]),
            f"- **事实指针**：{ptr_text}",
            f"- **为何必须对抗**：{rationale}",
        ]
    )


def _motion_card_guidance(*, auto_adopt: bool) -> str:
    """Consumption guidance for the「建议开辩」section (prompt-layer fork)."""
    if auto_adopt:
        return (
            "【消费指引·深度研究自治】可直接调 debate 开赛："
            "motion 原样或磨锋利；sides 薄立场直传；"
            "background 由你据 fact_pointers 与四路产物汇编客观事实——不得装观点。"
            "同回合协调态/批收口后再调 debate 是合法路径。多张卡时择优开一场。"
        )
    return (
        "【消费指引·默认模式】在收尾正文向用户呈报命题 + 各方薄立场 + 为何必须对抗；"
        "系统已/将登记阶段推进卡，【勿口头征求开辩同意】。"
        "本回合【不要】直接调用 debate——是否开辩由用户点推进卡定夺。"
        "多张卡时全部列出，由你择优呈报。"
    )


def motion_cards_block(
    products: list[dict[str, Any]], *, auto_adopt: bool = False
) -> str:
    """CEO-facing「建议开辩」section, or "" when no worker submitted a motion_card."""
    cards = [
        (wp["role"], wp["run_id"], wp["motion_card"])
        for wp in products
        if isinstance(wp.get("motion_card"), dict)
    ]
    if not cards:
        return ""
    body = "\n\n".join(
        _format_motion_card_block(role, card, run_id=rid) for role, rid, card in cards
    )
    return (
        "\n### 建议开辩（队员提交的命题卡）\n"
        "以下是队员在完工交接中提交的结构化命题卡（发现【必须对抗交锋】的核心争议时才会出现）。"
        f"{_motion_card_guidance(auto_adopt=auto_adopt)}\n\n"
        + body
    )


def direct_result(tool: DelegateTool, state: RunState) -> ToolResult:
    """提案2a：把单个成功 worker 的产出直接作为本回合最终答复（HANDOFF 终态）。"""
    # 完工交接简报: the brief is structured (``state.debrief``, submitted via the worker's handoff
    # tool — never mixed into the prose), so the deliverable IS the clean answer as-is. If the
    # author suggested a 建议下一步, re-attach it as a readable footer (there is no CEO synthesis
    # pass here to relay it). Same for an optional motion_card.
    text = state.content
    debrief = state.debrief if isinstance(state.debrief, dict) else None
    next_steps = (debrief or {}).get("next_steps", "") if debrief else ""
    if next_steps:
        text = f"{text}\n\n---\n**建议下一步**：{next_steps}"
    card = (debrief or {}).get("motion_card") if debrief else None
    if isinstance(card, dict):
        from agentcore.runtime.deep_research_auto import tool_may_auto_debate

        if tool_may_auto_debate(tool):
            footer = (
                "**建议开辩**（深度研究自治：可直接调 debate 开赛；"
                "background 据 fact_pointers 与产物汇编客观事实，不得装观点）\n"
            )
        else:
            footer = (
                "**建议开辩**（系统登记阶段推进卡；【勿口头征求开辩同意】；"
                "本回合勿直接开辩）\n"
            )
        text = f"{text}\n\n---\n{footer}" + _format_motion_card_block("队员", card)
    tool._sink.emit(content_delta(text))
    return ToolResult(
        tool_call_id="",
        success=True,
        output=text,
        output_limit=DELEGATE_OUTPUT_LIMIT,
        effect=ToolEffect.HANDOFF,
        final_text=text,
    )


def escalation_block(tool: DelegateTool, plan: RunPlan, results: dict) -> str:
    """The CEO-facing「队员升级」section, or "" when no worker escalated."""
    pending: list[tuple[bool, str]] = []
    answered: list[str] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if not state or not state.escalations:
            continue
        label = node.role or node.run_id
        for e in state.escalations:
            question = str(e.get("question") or "").strip()
            if not question:
                continue
            if str(e.get("status") or "raised") == "resolved":
                answer = str(e.get("answer") or "").strip()
                answered.append(f"- {label}：{question} → 用户已答：{answer}")
                continue
            blocking = bool(e.get("blocking"))
            # 卡在缺输入·依赖缺口 (§2.4 变·worker 的「拉」): if this run got here (synthesis) rather
            # than being settled at the reactive wave boundary, mark it so the CEO补 a producer.
            is_dep = e.get("kind") == "dep"
            mark = "【关键阻塞】" if blocking else ("【缺输入·依赖缺口】" if is_dep else "")
            line = f"- {mark}{label}：{question}"
            assumption = str(e.get("assumption") or "").strip()
            if assumption:
                line += f"（其暂用假设：{assumption}）"
            pending.append((blocking, line))
    if not pending and not answered:
        return ""
    out = ""
    if pending:
        pending.sort(key=lambda it: not it[0])
        out += (
            "\n### ⚠️ 队员升级了待决问题（请先处理再收尾）\n"
            "以下是队员无法独自拍板、需要你定夺的关键岔路 / 缺失信息。它们已按各自的暂定假设"
            "继续交付，但你应先处理这些问题：能自己答的就在概览里给出并据此判断相关产物是否需"
            "返工；确需用户拍板的就用 ask_user 问（可把问题 near-verbatim 转给用户）；需要原"
            "作者据答案重做的就用 delegate 设 continue_from_run_id 带现场续派；标【缺输入·依赖缺口】的是队员卡在缺一个还不存在"
            "的输入——用 delegate 补一个产出它的步骤，再设 continue_from_run_id 把结果交回原作者据此续写。\n"
            + "\n".join(line for _, line in pending)
        )
    if answered:
        out += (
            "\n### ✅ 已当场答复的升级（用户在执行中已拍板，无需再问）\n"
            "以下升级队员已直接问到用户、拿到答复并据此续跑；把这些结论纳入你的收尾叙事即可，"
            "不要再用 ask_user 重复问同样的问题。\n" + "\n".join(answered)
        )
    return out


def worker_products(tool: DelegateTool, plan: RunPlan, results: dict) -> list[dict[str, Any]]:
    """Each worker's product folded back to the CEO — SINGLE SOURCE for synthesis + run_context."""
    from agentcore.runtime.runs.constants import CEO_SYNTHESIS_BUDGET, DEP_POINTER_SUMMARY_CHARS
    from agentcore.runtime.runs.fidelity import allocate, truncate_head_tail
    from agentcore.runtime.runs.types import RunPhase

    # Hot-redirect revisions (``{run_id}_revN``) are not plan nodes; map original → revision
    # so a CANCELLED+redirected worker surfaces its continued product, not「无输出」.
    hot_by_original: dict[str, tuple[str, Any]] = {}
    plan_ids = {n.run_id for n in plan.nodes}
    for rid, st in results.items():
        if rid in plan_ids or st is None:
            continue
        if st.phase is not RunPhase.COMPLETED or not (st.content or "").strip():
            continue
        # Naming: continue_run / redirect use ``{target}_rev{n}``
        if "_rev" in rid:
            orig = rid.rsplit("_rev", 1)[0]
            if orig in plan_ids:
                hot_by_original[orig] = (rid, st)

    # 完工交接简报: the content is already the pure deliverable (each worker's brief rides its
    # structured ``debrief`` from the handoff tool — never appended to the prose), so the body
    # sizes on the deliverable alone, the author's own 结论 LEADS the body, and 建议下一步 is
    # surfaced separately (format_for_ceo) for the CEO to relay to the user.
    cleaned: dict[str, tuple[str, dict[str, Any] | None]] = {}
    for node in plan.nodes:
        st = results.get(node.run_id)
        if node.run_id in hot_by_original:
            _rid, hot_st = hot_by_original[node.run_id]
            cleaned[node.run_id] = (hot_st.content, hot_st.debrief)
        else:
            cleaned[node.run_id] = (st.content, st.debrief) if st and st.content else ("", None)

    def _mode(node) -> str:
        if node.run_id in hot_by_original:
            _rid, hot_st = hot_by_original[node.run_id]
            if hot_st.files_touched:
                return "pointer"
            return "pass_through" if hot_st.content else "none"
        st = results.get(node.run_id)
        # Only COMPLETED products are pass_through / pointer. FAILED nodes often
        # still carry a body (contract miss after retries) — that must surface as
        #「失败：…」via the error branch below, never as a fake delivered product.
        if not st or st.phase is not RunPhase.COMPLETED or not st.content:
            return "none"
        if st.files_touched:
            return "pointer"
        return "pass_through"

    modes = {node.run_id: _mode(node) for node in plan.nodes}
    allowances = iter(
        allocate(
            [
                len(cleaned[node.run_id][0])
                for node in plan.nodes
                if modes[node.run_id] == "pass_through"
            ],
            CEO_SYNTHESIS_BUDGET,
        )
    )
    # Cold handoff: a CANCELLED original that a ``_redir`` (replaces_run_id) took over
    # must not surface as「失败/被跳过」— the handoff node is the product.
    replaced_ids = {n.replaces_run_id for n in plan.nodes if n.replaces_run_id}

    products: list[dict[str, Any]] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if (
            state is not None
            and state.phase is RunPhase.CANCELLED
            and node.run_id in replaced_ids
            and node.run_id not in hot_by_original
        ):
            continue
        hot = hot_by_original.get(node.run_id)
        if hot is not None:
            status = "completed"
            state = hot[1]
        else:
            status = state.phase.value if state else "unknown"
        label = node.role or node.run_id
        mode = modes[node.run_id]
        clean, debrief = cleaned[node.run_id]
        author_summary = (debrief or {}).get("summary", "") if debrief else ""
        next_steps = (debrief or {}).get("next_steps", "") if debrief else ""
        motion_card = (debrief or {}).get("motion_card") if debrief else None
        if not isinstance(motion_card, dict):
            motion_card = None
        fidelity = ""
        truncated = False
        if mode == "pointer":
            # HEAD+TAIL digest (not head-only): the full product is on disk (pointer), and the
            # digest keeps the deliverable's opening AND its tail so 收尾 / 关键取舍 aren't dropped.
            body = truncate_head_tail(clean, DEP_POINTER_SUMMARY_CHARS)
            fidelity, truncated = "pointer", True
        elif mode == "pass_through":
            allowance = next(allowances)
            body = truncate_head_tail(clean, allowance)
            fidelity = "pass_through"
            truncated = len(clean) > allowance
        elif state and state.error:
            body = f"（失败：{state.error}）"
        else:
            body = "（无输出）"
        if node.replaces_run_id:
            body = (
                f"【接替】本节点 replaces_run_id=`{node.replaces_run_id}`"
                f"（接手原失败/取消队员）\n\n{body}"
            )
        # Lead the CEO's per-worker view with the author's own 结论 (cheapest, trim-proof).
        if author_summary and mode in ("pointer", "pass_through"):
            body = f"交接结论：{author_summary}\n\n{body}"
        if state and state.warnings:
            warns = "；".join(state.warnings)
            body += f"\n\n> 质检提醒（未完全达标，请判断是否需要返工）：{warns}"
        if state and state.escalations:
            body += (
                f"\n\n> 已升级 {len(state.escalations)} 项待决问题（见顶部「队员升级了"
                "待决问题」，请先处理再据此判断本产物是否需返工）"
            )
        files = list(state.files_touched) if state and state.files_touched else []
        if files:
            produced = "、".join(f"`{p}`" for p in files)
            body += f"\n\n> 文件产出（已写入工作区）：{produced}"
        tool_failures = (
            [dict(row) for row in state.tool_failures if isinstance(row, dict)]
            if state and state.tool_failures
            else []
        )
        products.append(
            {
                "role": label,
                "run_id": hot[0] if hot else node.run_id,
                "status": status,
                "body": body,
                "fidelity": fidelity,
                "truncated": truncated,
                "files": files,
                "next_steps": next_steps,
                "motion_card": motion_card,
                "replaces_run_id": node.replaces_run_id,
                "tool_failures": tool_failures,
            }
        )
    return products


def team_notes_block(tool: DelegateTool) -> str:
    """The CEO-facing【团队便签】section feeding 合·对账 (§2.3), or "" when the wall is empty / absent.

    The batch's NoteWall (owned by ``drive``, stashed on the tool) holds the 决定 / 认领 / 提醒 the
    team broadcast while working — its outstanding ACTIVE notes are the ready-made input to the
    semantic-boundary reconciliation in the closing instruction (便签墙本身又是对账的现成输入).
    Absent (a CEO that never delegated) or empty (nothing posted / all retracted) ⇒ "" so nothing
    is added — 零行为变化 for a team that didn't use the wall."""
    wall = tool._note_wall
    if wall is None:
        return ""
    notes = wall.active_notes()
    if not notes:
        return ""
    from agentcore.runtime.runs.notewall import format_notes_for_synthesis

    return "\n" + format_notes_for_synthesis(notes)


def _roster_block(plan: RunPlan, results: dict, products: list[dict[str, Any]]) -> str:
    """Deterministic per-run roster so CEO synthesis cannot invent「全部交付」."""
    from agentcore.runtime.runs.types import RunPhase

    replaced_ids = {n.replaces_run_id for n in plan.nodes if n.replaces_run_id}
    replace_by: dict[str, str] = {
        n.replaces_run_id: (n.role or n.run_id)
        for n in plan.nodes
        if n.replaces_run_id
    }
    completed = failed = skipped = cancelled = other = 0
    failed_lines: list[str] = []
    replaced_lines: list[str] = []
    cancel_cascade_lines: list[str] = []
    budget_skip_lines: list[str] = []
    for node in plan.nodes:
        st = results.get(node.run_id)
        label = node.role or node.run_id
        phase = st.phase if st is not None else None
        if node.replaces_run_id:
            replaced_lines.append(
                f"- {label}（`{node.run_id}`）接替失败/取消节点 `{node.replaces_run_id}`"
            )
        if phase is RunPhase.COMPLETED:
            completed += 1
        elif phase is RunPhase.FAILED:
            failed += 1
            err = (st.error or "").strip() if st else ""
            successor = replace_by.get(node.run_id)
            note = f"；已被 {successor} 接替" if successor else ""
            failed_lines.append(
                f"- {label}（`{node.run_id}`）失败{('：' + err) if err else ''}{note}"
            )
        elif phase is RunPhase.SKIPPED:
            skipped += 1
            budget_skip = False
            if st is not None:
                for gap in st.delivery_gaps or []:
                    if isinstance(gap, dict) and gap.get("reason") == "turn_token_budget":
                        budget_skip = True
                        break
            if budget_skip:
                budget_skip_lines.append(
                    f"- {label}（`{node.run_id}`）因回合/子团队额度未跑；"
                    "下一回合请 append 同图或 replan/点名续派该角色，"
                    "禁止本回合假装已全部完成"
                )
            # Cancel / hard-absence skips under strict require_upstream, or
            # lenient zero-success: tip CEO to replan or loosen fan-in.
            upstream_cancel = any(
                (results.get(d) is not None and results[d].phase is RunPhase.CANCELLED)
                for d in (node.depends_on or [])
            )
            if upstream_cancel and not budget_skip:
                cancel_cascade_lines.append(
                    f"- {label}（`{node.run_id}`）因上游取消未跑；"
                    "默认可在其它上游已交付时继续（require_upstream=false）；"
                    "若需全量成功才跑请设 require_upstream=true；"
                    "零上游成功仍要放行可 force_continue=true 或 replaces_run_id 重派"
                )
        elif phase is RunPhase.CANCELLED:
            # Cold handoff originals that a replaces_run_id took over stay cancelled —
            # count them as replaced, not as open cancellations.
            if node.run_id in replaced_ids:
                continue
            cancelled += 1
        else:
            other += 1
    # Surface product-level status (hot-redirect may mark completed even if original cancelled).
    product_failed = sum(1 for p in products if p.get("status") not in ("completed",))
    lines = [
        "\n### 队员终态名册（地面真相——写终稿必须对照，禁止编造「全部交付」）\n"
        f"计划节点：完成 {completed} · 失败 {failed} · 跳过 {skipped} · 取消 {cancelled}"
        + (f" · 其他 {other}" if other else "")
        + f"；综述可见产物 {len(products)} 条"
        + (f"（其中非完成 {product_failed}）" if product_failed else "")
        + "。"
    ]
    if failed_lines:
        lines.append("失败节点：\n" + "\n".join(failed_lines))
    if budget_skip_lines:
        lines.append(
            "因额度跳过、从未开跑（下一回合可续）：\n" + "\n".join(budget_skip_lines)
        )
    if cancel_cascade_lines:
        lines.append(
            "上游取消导致下游未跑（仅严格 require_upstream 或零成功时）：\n"
            + "\n".join(cancel_cascade_lines)
        )
    if replaced_lines:
        lines.append("接替关系（replaces_run_id）：\n" + "\n".join(replaced_lines))
    if failed or skipped or product_failed or replaced_lines or cancel_cascade_lines:
        lines.append(
            "【叙事铁律】终稿必须如实写清部分失败与接替：点名失败角色/run、是否已被谁接替、"
            "用户可见影响；禁止「N 位队员全部交付 / 全部完成 / 全员成功」类措辞——"
            "协作图上的失败节点与此名册不一致时，以名册为准。"
            + (
                "额度跳过节点须写明「未跑、可下一回合续」，禁止装成已交付。"
                if budget_skip_lines
                else ""
            )
        )
    return "\n".join(lines)


def format_for_ceo(
    tool: DelegateTool, plan: RunPlan, results: dict, *, call_idx: int | None = None
) -> str:
    """Render the workers' products as the CEO's overview input."""
    lines = ["## 团队执行结果（据此写一段简短概览交给用户；完整详情用户自行查看）"]
    escalation = escalation_block(tool, plan, results)
    if escalation:
        lines.append(escalation)

    from agentcore.runtime.delegate.completion import (
        collect_worker_gaps,
        format_worker_gaps_block,
    )

    gaps = collect_worker_gaps(plan, results)
    audit_off_token = _audit_off_with_token_budget_gap(plan, gaps)
    gaps_block = format_worker_gaps_block(
        gaps, audit_off_with_token_budget=audit_off_token
    )
    if gaps_block:
        lines.append(gaps_block)

    products = worker_products(tool, plan, results)
    from agentcore.runtime.tool_failures import format_team_tool_failures_block

    tool_failures_block = format_team_tool_failures_block(products)
    if tool_failures_block:
        lines.append(tool_failures_block)
    lines.append(_roster_block(plan, results, products))
    emit_captain_readback(tool, products)
    # 命题卡 → 建议开辩：显著专节；自治生效且未超限时指引可直接调 debate。
    from agentcore.runtime.deep_research_auto import tool_may_auto_debate

    auto_adopt = tool_may_auto_debate(tool)
    cards_block = motion_cards_block(products, auto_adopt=auto_adopt)
    if cards_block:
        lines.append(cards_block)
    # 完工交接简报: surface each worker's 建议下一步 (proactive, non-blocking — distinct from the
    # escalation block's 待决问题) as ONE advisory section so the CEO can relay the worthwhile
    # ones to the user. Empty when nobody suggested anything.
    suggestions = [(wp["role"], wp["next_steps"]) for wp in products if wp.get("next_steps")]
    if suggestions:
        lines.append(
            "\n### 队员建议的下一步（供参考，由你与用户定夺，非必须执行）\n"
            "以下是各队员完工时顺带提的后续方向（非阻塞、不是待决问题）。择其有价值者，在你给"
            "用户的概览里自然带出『团队建议接下来可以…』即可；无价值的忽略，不要逐条复述。\n"
            + "\n".join(f"- {role}：{ns}" for role, ns in suggestions)
        )
    # 团队便签 → 合·对账 (§2.3): surface the team's outstanding broadcast 决定 / 认领 so the CEO
    # reconciles the assembled result against them in the closing instruction (the wall is 对账 的
    # 现成输入). Empty wall / a CEO that never delegated ⇒ "" → nothing added.
    notes_block = team_notes_block(tool)
    if notes_block:
        lines.append(notes_block)
    for wp in products:
        lines.append(
            f"\n### {wp['role']}（{wp['status']}） · run_id: `{wp['run_id']}`\n{wp['body']}"
        )
    lines.append(
        "\n---\n以上为团队产出。各成员的「文件产出（已写入工作区）」行是落盘的地面真相。\n"
        "⚠️ 防幻觉铁律：worker 是否真写了文件，只看「文件产出」行——正文声称写了却无此行 = 未真正"
        "落盘，判为【未达成】，用 delegate 设 continue_from_run_id 带现场续派落盘或重新冷委派。纯文本产出的 worker（调研 / 分析等）"
        "无文件产出属正常。\n"
        "多路并行且相互依赖时，做一步【语义边界对账】：查冲突（双方对同一接口假设不一致）、"
        "缺口（掉在缝里没人做）、重复（两人做了同一件事）；上方若有【团队便签】一并对照。"
        "对出问题用 continue_from_run_id 续派 / replan 修，别糊过去。独立并行（各干各的）跳过此步。\n"
        "收尾前对照用户原始请求做【完工核验】：每件事是否实质达成？未达成就补（delegate / replan / "
        "continue_from_run_id），已达成就自信收口、不无谓空转。然后用你自己的声音写一段简短概览，串起各人结论，"
        "指引用户看细节，不逐字复述。如有队员建议的下一步，择有价值者带给用户。"
        + (
            "上方若有【建议开辩】命题卡：择优后可直接调 debate 开赛"
            "（motion/sides 直传或磨锋利；background 汇编客观事实，不得装观点）；"
            "同回合协调态/批收口后再开辩合法。\n"
            if auto_adopt
            else (
                "上方若有【建议开辩】命题卡：在概览里呈报命题 + 各方 + 理由；"
                "系统已/将登记阶段推进卡，【勿口头征求开辩同意】；"
                "本回合不要直接调用 debate。\n"
            )
        )
        + "【终稿纪律】终稿只写给用户的交付，不是工作日志：交付物（结论 / 产物指引 / 缺口与后续动作）"
        "写在最前；过程叙述（谁做了什么、中途发生了什么）压缩成【至多一段】简述；"
        "禁止把上方 escalation 原文、系统提示、协调事件、进度卡叙事或中间合成草稿整段粘进终稿"
        "——升级与缺口只保留【结论与影响】一句话。若有未交付的承诺产物，用一小节显式列出"
        "「未交付 / 需你操作」，不得混在长文里含糊带过。"
        "对照上方【队员终态名册】：有失败 / 跳过 / 接替时必须写入终稿，"
        "禁止编造「全部交付 / 全部完成」。"
    )
    output = "\n".join(lines)
    if any(wp["status"] != "completed" for wp in products) or any(
        n.replaces_run_id for n in plan.nodes
    ):
        output += (
            "\n---\n**有队员失败/被跳过/被接替。** 终稿须点名说明，不得写成全员成功。"
            "如需补跑，请用 `replan(add=[...])` 在同一计划中追加替换节点"
            "（设 `replaces_run_id`；可引用本批已完成节点的 run_id 作为 depends_on），"
            "而非重新调用 delegate。若无需补跑，直接如实回复用户即可。"
        )
    raw_chars = sum(len(s.content) for s in results.values() if s and s.content)
    logger.info(
        "delegate.synthesis",
        call=call_idx if call_idx is not None else tool._calls,
        workers=len(plan.nodes),
        pointers=sum(1 for p in products if p["fidelity"] == "pointer"),
        prose=sum(1 for p in products if p["fidelity"] == "pass_through"),
        raw_chars=raw_chars,
        final_chars=len(output),
        ratio=round(len(output) / raw_chars, 2) if raw_chars else 1.0,
        capped=len(output) > DELEGATE_OUTPUT_LIMIT,
    )
    return output

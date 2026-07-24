"""交付状态结构化（能力闸门与交付诚实性）：delegate 批次收尾的确定性交付对账。

把收尾侧引擎已有的信号——worker ``files_touched``、契约 / 交接缺口
(:func:`~agentcore.runtime.delegate.completion.collect_worker_gaps`，含 degraded 交接与
artifacts 对账残差)、``completion_criteria`` 未满足、失败 / 未执行节点——汇成一条面向
用户的 ``delivery_status`` 事件（已交付文件 / 缺口 / 待用户操作），模板拼接、不调 LLM。

挂在 drive 的各收尾路径旁路（正常终态 / 验收未满足 / 部分失败 stash / replan(stop)），
永不抛错；纯 prose 成功批次（无落盘文件、无缺口）保持无声，不发事件。
折叠语义：同 ``execution_id`` 保最新——反映最近一批委派的对账（多批场景下 FileArtifactsCard
仍是全量文件清单，本事件承载「诚实对账」而非全量枚举）。
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunState
from agentcore.runtime.turn_token_budget import REASON_QA_DEFERRED, REASON_TURN_TOKEN_BUDGET

_MAX_FILES = 24
_MAX_GAPS = 12

# build_website task books embed ``站点【…】`` — reuse for verify-action prompt.
_SITE_BRACKET_RE = re.compile(r"站点【([^】]+)】")


def _infer_website_site(plan: RunPlan) -> str:
    """Best-effort site label from plan task text (empty when unknown)."""
    for node in plan.nodes:
        task = getattr(node, "task", None)
        if not isinstance(task, str) or not task:
            continue
        match = _SITE_BRACKET_RE.search(task)
        if match:
            site = match.group(1).strip()
            if site:
                return site
    return ""


def _continue_writing_action() -> dict[str, str]:
    """CTA when long-form writing stopped partial (章边界 / 预算) — no auto rewrite."""
    return {
        "kind": "continue_writing",
        "description": (
            "成篇未写完——点此续写（从已完成章节继续；勿删稿重写整篇）"
        ),
        "prompt": (
            "请续写上一篇未完成的报告：先 file_read 已有草稿，"
            "从上一完整章之后用 file_append 按章续写；"
            "禁止 file_delete 后整篇重写。预算不够时仍停在章边界并诚实标 partial。"
        ),
    }


def _continue_skipped_runs_action(roles: list[str]) -> dict[str, str]:
    """CTA when nodes were SKIPPED for turn/nested token budget — not 成篇续写."""
    named = "、".join(roles[:6]) if roles else "未跑节点"
    extra = f"等 {len(roles)} 个角色" if len(roles) > 6 else named
    return {
        "kind": "continue_skipped_runs",
        "description": (
            f"因额度未跑（{extra}）——点此下一回合续跑未执行节点，"
            "禁止假装本回合已全部完成"
        ),
        "prompt": (
            "请续跑上一回合因 token 额度跳过、从未开跑的节点："
            f"点名补跑 {named}"
            "；优先 append 同一协作图或 replan/点名角色，"
            "不要另开无关大派，不要把部分完成说成全部交付。"
        ),
    }


def _website_verify_action(site: str) -> dict[str, str]:
    """Structured second-act CTA when whole-page QA deferred for budget."""
    site_arg = f'site="{site}"' if site else 'site="<站点简述>"'
    prompt = (
        "请对本站做第二段整页验收：delegate 时用 playbook=build_website_verify，"
        f"playbook_args 填 {site_arg}。"
        "工作区已有 site/ 产物，只跑整页/视觉 QA，勿重做文案、骨架或分区。"
    )
    return {
        "kind": "website_verify",
        "description": (
            "整页验收因预算推迟——点此续派页面 QA（不重建站，只用 build_website_verify）"
        ),
        "prompt": prompt,
    }


def _delivered_files(results: dict[str, RunState]) -> list[str]:
    """Ordered, deduped workspace paths COMPLETED workers wrote (含热修修订 run)."""
    seen: set[str] = set()
    out: list[str] = []
    for state in results.values():
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        for path in state.files_touched or []:
            if path and path not in seen:
                seen.add(path)
                out.append(path)
    return out[:_MAX_FILES]


def _has_completed_revision(run_id: str, results: dict[str, RunState]) -> bool:
    """True when a hot-redirect revision (``{run_id}_rev*``) finished for this node."""
    prefix = f"{run_id}_rev"
    return any(
        rid.startswith(prefix) and st is not None and st.phase is RunPhase.COMPLETED
        for rid, st in results.items()
    )


def _node_gaps(plan: RunPlan, results: dict[str, RunState]) -> list[dict[str, str]]:
    """Terminal-but-undelivered plan nodes → gap rows (failed / skipped / cancelled)."""
    gaps: list[dict[str, str]] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if state is None:
            continue
        role = node.role or node.agent_name or node.run_id
        if state.phase is RunPhase.FAILED:
            err = (state.error or "").strip()
            desc = f"未完成（失败：{err}）" if err else "未完成（失败）"
            gaps.append({"role": role, "description": desc})
        elif state.phase is RunPhase.SKIPPED:
            # Prefer first-class delivery_gaps (turn-ceiling honesty: 未目验 / 未跑
            # web_quality / {{…}}); fall back to a generic skip row.
            emitted = False
            for row in state.delivery_gaps or []:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("description") or "").strip()
                if not text:
                    continue
                item: dict[str, str] = {"role": role, "description": text}
                reason = str(row.get("reason") or "").strip()
                if reason:
                    item["reason"] = reason
                gaps.append(item)
                emitted = True
            if not emitted:
                gaps.append({"role": role, "description": "未执行（计划收口时跳过）"})
        elif state.phase is RunPhase.CANCELLED and not _has_completed_revision(
            node.run_id, results
        ):
            gaps.append({"role": role, "description": "未完成（中途取消）"})
    return gaps


def build_delivery_status(
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    backend: Any = None,
    criteria_gaps: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build a ``delivery_status`` payload, or ``None`` when there is nothing to report.

    Emission gate: at least one delivered file OR one gap — a pure-prose successful
    batch stays silent (研究 / 分析类委派不该弹交付卡). All inputs are the wrap-up
    signals the engine already computed; nothing here re-verifies the workspace.
    """
    from agentcore.runtime.delegate.completion import (
        collect_worker_gaps,
        plan_mentions_binary_artifact,
        plan_suggests_code_verification,
    )

    delivered = _delivered_files(results)

    gaps: list[dict[str, str]] = []
    # ① 契约 / 交接残差（软接受后仍未对齐的声明交付物、degraded 交接、预算/超时掐断…）。
    for role, rows in collect_worker_gaps(plan, results):
        for row in rows:
            if isinstance(row, dict):
                text = str(row.get("description") or "").strip()
                reason = str(row.get("reason") or "").strip()
            else:
                text = str(row).strip()
                reason = ""
            if not text:
                continue
            item: dict[str, str] = {"role": role, "description": text}
            if reason:
                item["reason"] = reason
            gaps.append(item)
    # ② 完成验收未满足（completion_criteria 缺口，批次级）。
    for gap in criteria_gaps or []:
        text = str(gap).strip()
        if text:
            gaps.append({"role": "验收", "description": text})
    # ③ 失败 / 未执行 / 取消的计划节点（热修已接手的取消节点不算缺口）。
    gaps.extend(_node_gaps(plan, results))
    gaps = gaps[:_MAX_GAPS]

    # 待用户操作：① 无执行环境 → 绑定本地文件夹；② 整页 QA 预算 defer → 一键续派验收；
    # ③ 成篇 partial（token/超时掐断）→ 续写入口；④ 额度 SKIPPED 未跑节点 → 续跑入口
    # （勿把纯 turn_token_budget SKIPPED 误挂成篇续写）。
    # ① 判定复用 code_execution_enabled_for 单一真相源（与 worker registry / 委派闸同一谓词）。
    actions: list[dict[str, str]] = []
    if any(g.get("reason") == REASON_QA_DEFERRED for g in gaps):
        actions.append(_website_verify_action(_infer_website_site(plan)))
    skipped_budget_roles = [
        str(g.get("role") or "").strip() or "未跑节点"
        for g in gaps
        if g.get("reason") == REASON_TURN_TOKEN_BUDGET
    ]
    # Dedup role labels while preserving order.
    seen_roles: set[str] = set()
    skipped_roles_unique: list[str] = []
    for role in skipped_budget_roles:
        if role not in seen_roles:
            seen_roles.add(role)
            skipped_roles_unique.append(role)
    if skipped_roles_unique:
        actions.append(_continue_skipped_runs_action(skipped_roles_unique))
    writing_partial = any(
        g.get("reason") in ("token_budget", "worker_timeout") for g in gaps
    )
    if writing_partial and delivered:
        actions.append(_continue_writing_action())
    if backend is not None and gaps:
        from agentcore.tools.builtin import code_execution_enabled_for

        needs_execution = (
            plan_suggests_code_verification(plan)
            or plan_mentions_binary_artifact(plan)
            or any("code_execute" in g["description"] for g in gaps)
        )
        if needs_execution and not code_execution_enabled_for(backend):
            actions.append(
                {
                    "kind": "bind_local_folder",
                    "description": (
                        "本回合为云端会话、未装配执行环境：绑定本地文件夹后，"
                        "团队可在你的电脑上运行脚本、生成并验证产物。"
                    ),
                }
            )

    if not delivered and not gaps:
        return None

    if not gaps:
        state = "delivered"
        summary = f"已交付 {len(delivered)} 个文件"
    elif delivered:
        state = "partial"
        summary = f"已交付 {len(delivered)} 个文件；{len(gaps)} 项缺口"
    else:
        state = "blocked"
        summary = f"未能交付：{len(gaps)} 项缺口"

    return {
        "execution_id": execution_id,
        "state": state,
        "summary": summary,
        "delivered_files": delivered,
        "gaps": gaps,
        "actions": actions,
    }


def maybe_emit_delivery_status(
    sink: Any,
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    backend: Any = None,
    criteria_gaps: list[str] | None = None,
) -> None:
    """Emit ``delivery_status`` when the reconciliation has substance. Never raises."""
    try:
        payload = build_delivery_status(
            plan,
            results,
            execution_id=execution_id,
            backend=backend,
            criteria_gaps=criteria_gaps,
        )
        if payload is None:
            return
        from agentcore.runtime.events import delivery_status

        sink.emit(delivery_status(**payload))
    except Exception:  # noqa: BLE001 — wrap-up side channel must never break the drive
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning(
            "delegate.delivery_status_failed",
            execution_id=execution_id,
            exc_info=True,
        )

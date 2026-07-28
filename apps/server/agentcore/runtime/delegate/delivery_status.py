"""交付状态结构化（能力闸门与交付诚实性）：delegate 批次收尾的确定性交付对账。

把收尾侧引擎已有的信号——worker ``files_touched``、契约 / 交接缺口
(:func:`~agentcore.runtime.delegate.completion.collect_worker_gaps`，含 degraded 交接与
artifacts 对账残差)、``completion_criteria`` 未满足、失败 / 未执行节点——汇成一条面向
用户的 ``delivery_status`` 事件（已交付文件 / 缺口 / 待用户操作），模板拼接、不调 LLM。

用户面零落盘缺口合并为一种 ``files_not_landed``（契约层与批次 ``files_written`` 同源谓词，
不再并列为两条）；CEO / 工具结果仍可保留分层原文。发射时写入回合
:data:`current_delivery_verdict`，供 CEO ``finish_guard`` 对照终答，禁止与卡矛盾的假完成。

挂在 drive 的各收尾路径旁路（正常终态 / 验收未满足 / 部分失败 stash / replan(stop)），
永不抛错；纯 prose 成功批次（无落盘文件、无缺口）保持无声，不发事件。
折叠语义：同 ``execution_id`` 保最新——反映最近一批委派的对账（多批场景下 FileArtifactsCard
仍是全量文件清单，本事件承载「诚实对账」而非全量枚举）。

严重度：``severity=warning``（待核实/示例自注等）不单独撑起 partial/blocked，
仅有 warning 时 state=``notes``（轻提醒）；blocking 缺口才标「部分未满足 / 未满足」。
成篇未写完改由对话框接着说——不再发 ``continue_writing`` 一键按钮。
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunState
from agentcore.runtime.turn_token_budget import REASON_QA_DEFERRED, REASON_TURN_TOKEN_BUDGET

_MAX_FILES = 24
_MAX_GAPS = 12

REASON_UNVERIFIED_NOTE = "unverified_note"
REASON_FILES_NOT_LANDED = "files_not_landed"
# Verify-shaped tool failure (browser_navigate / test_run / verify 形 code_execute·terminal).
REASON_VERIFY_FAILED = "verify_failed"
_WRITING_CUTOFF_REASONS = frozenset({"token_budget", "worker_timeout"})

# Per-worker contract + batch files_written criteria share this predicate.
_ZERO_LANDING_MARKERS = (
    "未把产物写入工作区",
    "尚无 worker 将产物写入工作区",
)


@dataclass(frozen=True)
class DeliveryVerdict:
    """Turn-scoped delivery reconciliation for CEO finish_guard (not a wire payload)."""

    state: str
    delivered_files: tuple[str, ...]
    execution_id: str


current_delivery_verdict: ContextVar[DeliveryVerdict | None] = ContextVar(
    "current_delivery_verdict", default=None
)

# Soft reminder copy markers (placeholder soft + soft keyword coverage).
_SOFT_REMINDER_MARKERS = (
    "不阻断验收",
    "未核实/示例自注",
    "待核实/示例自注",
    "素材覆盖提醒（软）",
    "契约软提醒",
)

# build_website task books embed ``站点【…】`` — reuse for verify-action prompt.
_SITE_BRACKET_RE = re.compile(r"站点【([^】]+)】")
# 「不阻断验收，3 处」/「自注（3 处）」/ legacy soft copy.
_SOFT_HIT_COUNT_RE = re.compile(r"(?:不阻断验收，|自注（)(\d+)\s*处")
_SOFT_PATH_RE = re.compile(r"`([^`]+)`\s*·")


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


def _is_soft_reminder(text: str, reason: str = "") -> bool:
    """True when this gap row is a soft note (待核实等), not a blocking shortfall."""
    if reason == REASON_UNVERIFIED_NOTE:
        return True
    return any(marker in text for marker in _SOFT_REMINDER_MARKERS)


def _soft_paths(text: str) -> list[str]:
    """Extract workspace paths from soft-warning hit lines (``path`` · label · …)."""
    seen: set[str] = set()
    out: list[str] = []
    for path in _SOFT_PATH_RE.findall(text or ""):
        p = path.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _soft_hit_count(text: str) -> int:
    """Best-effort hit count from soft warning copy; fall back to 1."""
    match = _SOFT_HIT_COUNT_RE.search(text or "")
    if match:
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            pass
    return 1


def _annotate_gap(
    role: str,
    text: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Build one gap row; soft reminders get severity=warning + optional paths."""
    item: dict[str, Any] = {"role": role, "description": text}
    if _is_soft_reminder(text, reason):
        item["severity"] = "warning"
        item["reason"] = reason or REASON_UNVERIFIED_NOTE
        paths = _soft_paths(text)
        if paths:
            item["paths"] = paths
        return item
    if reason:
        item["reason"] = reason
    return item


def _node_gaps(plan: RunPlan, results: dict[str, RunState]) -> list[dict[str, Any]]:
    """Terminal-but-undelivered plan nodes → gap rows (failed / skipped / cancelled)."""
    gaps: list[dict[str, Any]] = []
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
                reason = str(row.get("reason") or "").strip()
                gaps.append(_annotate_gap(role, text, reason=reason))
                emitted = True
            if not emitted:
                gaps.append({"role": role, "description": "未执行（计划收口时跳过）"})
        elif state.phase is RunPhase.CANCELLED and not _has_completed_revision(
            node.run_id, results
        ):
            gaps.append({"role": role, "description": "未完成（中途取消）"})
    return gaps


def _is_blocking(gap: dict[str, Any]) -> bool:
    return gap.get("severity") != "warning"


def _is_zero_landing_text(text: str) -> bool:
    """True when gap copy is the shared zero-``files_touched`` predicate."""
    return any(marker in (text or "") for marker in _ZERO_LANDING_MARKERS)


def _code_ran_without_writeback(results: dict[str, RunState]) -> bool:
    """True when a COMPLETED worker ran ``code_execute`` successfully but landed no files."""
    from agentcore.runtime.delegate.completion import (
        _code_execute_succeeded_in_transcript,
        _worker_files_written,
    )

    for state in results.values():
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        if _worker_files_written(state):
            continue
        if state.transcript and _code_execute_succeeded_in_transcript(state.transcript):
            return True
    return False


def _files_not_landed_gap(results: dict[str, RunState]) -> dict[str, Any]:
    """Single user-facing gap for zero workspace landing (契约 + 批次验收合并投影)."""
    if _code_ran_without_writeback(results):
        text = (
            "未交付：已执行代码但未把产物写回工作区"
            "（沙箱内文件不算交付；须用写文件工具落盘，或确保脚本执行后写回工作区）"
        )
    else:
        from agentcore.runtime.runs.serialize import format_file_landing_tools_slash

        tools = format_file_landing_tools_slash()
        text = f"未交付：工作区没有新文件（须用 {tools} 落盘）"
    return {
        "role": "验收",
        "description": text,
        "reason": REASON_FILES_NOT_LANDED,
    }


def _project_user_gaps(
    raw_gaps: list[dict[str, Any]],
    results: dict[str, RunState],
) -> list[dict[str, Any]]:
    """Collapse duplicate zero-landing rows into one ``files_not_landed`` gap."""
    zero: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for gap in raw_gaps:
        text = str(gap.get("description") or "")
        if _is_zero_landing_text(text):
            zero.append(gap)
        else:
            other.append(gap)
    if not zero:
        return other
    return [_files_not_landed_gap(results), *other]


def _warning_note_stats(warnings: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (hit_count, distinct_file_count) for soft reminder rows."""
    hits = 0
    files: set[str] = set()
    for gap in warnings:
        hits += _soft_hit_count(str(gap.get("description") or ""))
        for path in gap.get("paths") or []:
            if path:
                files.add(str(path))
        if not gap.get("paths"):
            for path in _soft_paths(str(gap.get("description") or "")):
                files.add(path)
    return max(hits, len(warnings) or 0), len(files)


def _build_summary(
    delivered: list[str],
    blocking: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str:
    """Human summary: separate 未完成 vs 待核实; writing cutoff → 成篇未写完."""
    warn_hits, warn_files = _warning_note_stats(warnings)
    warn_bit = ""
    if warn_hits:
        warn_bit = f"{warn_hits} 处待核实备注"
        if warn_files:
            warn_bit += f"（{warn_files} 个文件）"

    if not blocking:
        if warn_bit:
            return f"有 {warn_bit}"
        if delivered:
            return f"已交付 {len(delivered)} 个文件"
        return "无交付缺口"

    writing = any(g.get("reason") in _WRITING_CUTOFF_REASONS for g in blocking)
    other_n = sum(
        1 for g in blocking if g.get("reason") not in _WRITING_CUTOFF_REASONS
    )

    if not delivered:
        if writing and other_n == 0:
            head = "未能交付：成篇未写完"
        elif writing:
            head = f"未能交付：成篇未写完；另有 {other_n} 项未完成"
        else:
            head = f"未能交付：{len(blocking)} 项未完成"
        if warn_bit:
            return f"{head}；另有 {warn_bit}"
        return head

    parts: list[str] = [f"已交付 {len(delivered)} 个文件"]
    if writing:
        parts.append("成篇未写完")
        if other_n:
            parts.append(f"另有 {other_n} 项未完成")
    else:
        parts.append(f"{len(blocking)} 项未完成")
    if warn_bit:
        parts.append(f"另有 {warn_bit}")
    return "；".join(parts)


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
        collect_verify_failure_gaps,
        collect_worker_gaps,
        plan_mentions_binary_artifact,
        plan_suggests_code_verification,
    )

    delivered = _delivered_files(results)

    raw_gaps: list[dict[str, Any]] = []
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
            raw_gaps.append(_annotate_gap(role, text, reason=reason))
    # ①b 验证形工具失败（可用性诚实性 · 丙）——COMPLETED 但 browser_navigate /
    # test_run / verify 形 code_execute·terminal 失败 → 不得仍为 delivered。
    for role, rows in collect_verify_failure_gaps(plan, results):
        for row in rows:
            text = str(row.get("description") or "").strip()
            if not text:
                continue
            reason = str(row.get("reason") or REASON_VERIFY_FAILED).strip()
            raw_gaps.append(_annotate_gap(role, text, reason=reason or REASON_VERIFY_FAILED))
    # ② 完成验收未满足（completion_criteria 缺口，批次级）。
    for gap in criteria_gaps or []:
        text = str(gap).strip()
        if text:
            raw_gaps.append({"role": "验收", "description": text})
    # ③ 失败 / 未执行 / 取消的计划节点（热修已接手的取消节点不算缺口）。
    raw_gaps.extend(_node_gaps(plan, results))
    # 用户面：零落盘（worker 契约 + 批次 files_written）合并为一条 files_not_landed。
    gaps = _project_user_gaps(raw_gaps, results)[:_MAX_GAPS]

    blocking = [g for g in gaps if _is_blocking(g)]
    warnings = [g for g in gaps if not _is_blocking(g)]

    # 待用户操作：① 无执行环境 → 绑定本地文件夹；② 整页 QA 预算 defer → 一键续派验收；
    # ③ 额度 SKIPPED 未跑节点 → 续跑入口。
    # 成篇未写完不再挂 continue_writing——改由对话框接着说。
    # ① 判定复用 code_execution_enabled_for 单一真相源（与 worker registry / 委派闸同一谓词）。
    actions: list[dict[str, str]] = []
    if any(g.get("reason") == REASON_QA_DEFERRED for g in blocking):
        actions.append(_website_verify_action(_infer_website_site(plan)))
    skipped_budget_roles = [
        str(g.get("role") or "").strip() or "未跑节点"
        for g in blocking
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
    if backend is not None and blocking:
        from agentcore.tools.builtin import code_execution_enabled_for

        needs_execution = (
            plan_suggests_code_verification(plan)
            or plan_mentions_binary_artifact(plan)
            or any(g.get("reason") == REASON_FILES_NOT_LANDED for g in blocking)
            or any("code_execute" in str(g.get("description") or "") for g in blocking)
        )
        if needs_execution and not code_execution_enabled_for(backend):
            actions.append(
                {
                    "kind": "bind_local_folder",
                    "description": (
                        "本回合为云端会话、未装配执行环境：绑定本机执行环境"
                        "（本会话 scratch，≠打开本地项目）后，"
                        "团队可在你的电脑上运行脚本、生成并验证产物。"
                    ),
                }
            )

    # 云端已交付文件：即使用户面 state=delivered，也提示导出到本机（找不到文件夹）。
    # 与 bind_local_folder 可并存但语义不同（导出产物 ≠ 绑定执行环境）。
    if (
        delivered
        and backend is not None
        and getattr(backend, "location", None) != "local"
    ):
        actions.append(
            {
                "kind": "export_to_local",
                "description": (
                    "产物在云端工作区——导出到本机文件夹后即可 npm install / 本地运行"
                ),
            }
        )

    if not delivered and not gaps:
        return None

    if not blocking and not warnings:
        state = "delivered"
    elif not blocking and warnings:
        state = "notes"
    elif delivered:
        state = "partial"
    else:
        state = "blocked"

    summary = _build_summary(delivered, blocking, warnings)

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
        current_delivery_verdict.set(
            DeliveryVerdict(
                state=str(payload["state"]),
                delivered_files=tuple(payload.get("delivered_files") or ()),
                execution_id=execution_id,
            )
        )
        from agentcore.runtime.events import delivery_status

        sink.emit(delivery_status(**payload))
    except Exception:  # noqa: BLE001 — wrap-up side channel must never break the drive
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning(
            "delegate.delivery_status_failed",
            execution_id=execution_id,
            exc_info=True,
        )


# 可用性短问（甲）：偏窄识别——能用/可用/好了吗/完成了吗；排除长指令与「打开浏览器验证」。
_AVAILABILITY_STATUS_RE = re.compile(
    r"^(?:"
    r"(?:现在|目前|这[个次回]?)?(?:已经|都)?"
    r"(?:能(?:不能)?用|可以(?:使用|用)?|可用|好了|完成了|搞定了|做好了)"
    r"(?:了|了吗|吗|了没|没|了没有|没有)?"
    r"|is\s+it\s+(?:done|ready|usable|working)\??"
    r"|can\s+(?:i|we)\s+use\s+it\??"
    r")$",
    re.IGNORECASE,
)


def is_availability_status_question(text: str) -> bool:
    """True for narrow「能不能用 / 好了吗 / 完成了吗」status asks (可用性诚实性 · 甲)."""
    compact = re.sub(r"\s+", "", (text or "").strip())
    if not compact or len(compact) > 24:
        return False
    # Drop punctuation commonly glued to short asks.
    compact = re.sub(r"[？?！!。．.，,、…]+$", "", compact)
    if not compact or len(compact) > 20:
        return False
    return _AVAILABILITY_STATUS_RE.match(compact) is not None


def availability_status_nudge_prompt() -> str:
    """CEO one-shot: short availability ask → card is the main answer."""
    return (
        "[系统提示] 可用性短问：用户在问能不能用 / 好了吗 / 完成了吗。"
        "本回合若已发出（或复用）交付状态卡，以该卡为主答——"
        "散文只写一句注释指路看卡，禁止另编口头可用性结论，"
        "禁止用「已完整可用」盖过 partial/blocked 卡。"
    )


def _payload_to_verdict(payload: dict[str, Any]) -> DeliveryVerdict | None:
    """Build a finish_guard verdict from a journal/wire delivery_status payload."""
    execution_id = str(payload.get("execution_id") or "").strip()
    state = str(payload.get("state") or "").strip()
    if not execution_id or state not in ("delivered", "partial", "blocked", "notes"):
        return None
    files = payload.get("delivered_files") or []
    if not isinstance(files, list):
        files = []
    return DeliveryVerdict(
        state=state,
        delivered_files=tuple(str(p) for p in files if p),
        execution_id=execution_id,
    )


async def maybe_reinject_recent_delivery_for_availability_ask(
    sink: Any,
    *,
    conversation_id: str,
    user_message: str,
    exclude_turn_id: str | None = None,
) -> bool:
    """On narrow availability short asks, re-emit the latest delivery_status onto this turn.

    Reuses the conversation's most recent durable delivery reconciliation (不另造第二套).
    Sets ``current_delivery_verdict`` for finish_guard. Returns True when a card was
    re-emitted. Never raises.
    """
    if not is_availability_status_question(user_message):
        return False
    # Same-turn batch already stamped a verdict — no need to pull prior journal.
    if current_delivery_verdict.get() is not None:
        return False
    cid = (conversation_id or "").strip()
    if not cid:
        return False
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            payload = await repo.find_latest_delivery_status(
                conversation_id=cid,
                exclude_turn_id=exclude_turn_id,
            )
        if not isinstance(payload, dict):
            return False
        verdict = _payload_to_verdict(payload)
        if verdict is None:
            return False
        # Normalize wire fields for the event factory.
        raw_gaps = payload.get("gaps")
        raw_actions = payload.get("actions")
        gaps: list[Any] = raw_gaps if isinstance(raw_gaps, list) else []
        actions: list[Any] = raw_actions if isinstance(raw_actions, list) else []
        files = list(verdict.delivered_files)
        summary = str(payload.get("summary") or "").strip() or (
            f"已交付 {len(files)} 个文件" if files else "无交付缺口"
        )
        current_delivery_verdict.set(verdict)
        from agentcore.runtime.events import delivery_status

        sink.emit(
            delivery_status(
                execution_id=verdict.execution_id,
                state=verdict.state,
                summary=summary,
                delivered_files=files,
                gaps=[g for g in gaps if isinstance(g, dict)],
                actions=[a for a in actions if isinstance(a, dict)],
            )
        )
        return True
    except Exception:  # noqa: BLE001 — short-ask side channel must never break the turn
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning(
            "delegate.availability_delivery_reinject_failed",
            conversation_id=cid,
            exc_info=True,
        )
        return False

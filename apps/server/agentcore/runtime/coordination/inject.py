"""Format coordination events into CEO ReAct window messages."""

from __future__ import annotations

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.coordination.pipeline_view import (
    format_idle_yield_brief,
    format_pipeline_progress,
)
from agentcore.runtime.coordination.session import (
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
)
from agentcore.runtime.delegate.team_synthesis import worker_output_blurb


def format_coordination_events(
    session: CoordinationSession,
    events: list[CoordinationEvent],
) -> str:
    """Build a single system-facing brief for a coalesced event batch."""
    lines: list[str] = ["【团队协调事件】"]
    # Pipeline progress rides every inject so CEO sees wave / blocked / running state.
    if session.live_plan is not None or session.total_workers > 0:
        lines.append(format_pipeline_progress(session))
        lines.append("")
    for ev in events:
        lines.append(_format_one(session, ev))
    # 疑似缺依赖提示（builder.suspect_missing_dep 搭车）：随本批事件一并呈现，不新增唤醒。
    if session.dep_advisories:
        lines.append("")
        lines.append("【建图提示·疑似缺依赖】（供参考，无需单独回应）：")
        lines.extend(f"- {adv}" for adv in session.dep_advisories)
    if session.draft.strip():
        lines.append("")
        lines.append(f"当前合成草稿：\n{session.draft.strip()}")
    lines.append("")
    from agentcore.runtime.resolve.ceo_surface import COORDINATION_PERIOD_HINT

    lines.append(COORDINATION_PERIOD_HINT)
    lines.append(
        "先判断本批事件要不要你出手：带指令的事件（阻塞仲裁 / 边界让出 / 插话 / 全部完成）"
        "按其指令办；纯进展事件（worker_completed / note）多数【无需处置】——完成计数与"
        "各队员完成摘要已由系统自动展示给用户，勿为播报进度调 update_synthesis。"
        "无需处置时调 wait（或空响应、不写正文），等下一批事件即可——"
        "禁止用 delegate / update_synthesis 占位等待。"
        "可用工具：wait 确认等待；cancel_worker(run_id, reason) 终止队员；"
        "delegate 再派【全新角色/任务】队员（同回合追加进同一张协作图，不必等全队完成；"
        "禁止对在跑任务同构重派；流水线未完成时亦禁止与在图节点职责/文件目标重叠的追加）；"
        "replan(add=…) 仅在『计划已让出』波边界追加；"
        "resolve_escalation(run_id, answer) 兑现阻塞升级裁决；"
        "queue_user_message(interjection_id, reason) 把无关插话转入对话级排队（下一回合）；"
        "ask_user 向用户请示（偏好/授权/费用类须先问用户再 resolve）；"
        "update_synthesis(draft) 只在【里程碑】写合成草稿——一波/一阶段队员全部完成、"
        "冲突仲裁需记录、方向修正、长跑阶段性收束、终稿收束；例行的单个 worker 完成【不写】"
        "（进度已由系统自动呈现），微调措辞更不算里程碑。"
        "全部完成后做最终合成（走 content_delta），然后退出协调。"
        "【终稿纪律】最终合成是给用户的交付、不是协调日志：交付物在前，过程简述至多一段；"
        "以上协调事件、escalation 原文与合成草稿是你的工作输入，禁止整段粘进终稿"
        "——草稿要用也须重写成交付口吻；未交付的承诺产物须显式列出，不得含糊带过。"
    )
    return "\n".join(lines)


def events_to_messages(
    session: CoordinationSession,
    events: list[CoordinationEvent],
) -> list[LLMMessage]:
    if not events:
        return []
    return [LLMMessage(role="user", content=format_coordination_events(session, events))]


def idle_yield_messages(session: CoordinationSession) -> list[LLMMessage]:
    """Inject pipeline progress on idle-yield (workers busy, no team events)."""
    return [LLMMessage(role="user", content=format_idle_yield_brief(session))]


def _format_one(session: CoordinationSession, ev: CoordinationEvent) -> str:
    p = ev.payload
    if ev.kind is CoordinationEventKind.WORKER_COMPLETED:
        role = p.get("role") or p.get("run_id") or "?"
        status = p.get("status") or "completed"
        summary = p.get("summary") or ""
        done = len(session.completed_run_ids)
        total = session.total_workers
        return f"- worker_completed（{done}/{total}）【{role}】{status}：{summary}"
    if ev.kind is CoordinationEventKind.NOTE_POSTED:
        return (
            f"- note_posted【{p.get('role') or p.get('run_id') or '?'}】"
            f"{p.get('kind') or 'note'}：{p.get('text') or ''}"
        )
    if ev.kind is CoordinationEventKind.ESCALATION:
        role = p.get("role") or p.get("run_id") or "?"
        run_id = p.get("run_id") or "?"
        esc_kind = p.get("kind") or "normal"
        src = p.get("source") or "escalate"
        question = p.get("question") or p.get("summary") or ""
        assumption = p.get("assumption") or ""
        if p.get("blocking"):
            assume_bit = f"；队员假设：{assumption}" if assumption else ""
            return (
                f"- escalation【阻塞仲裁】【{role}】run_id={run_id} "
                f"{esc_kind}（via {src}）：{question}{assume_bit}"
                " ——你须仲裁：resolve_escalation(run_id, answer) 直裁；"
                "偏好/授权/费用类须先 ask_user 征询用户，再 "
                "resolve_escalation(run_id, answer, via_user=true)。"
                "超时无响应时队员会按假设继续，勿永久卡住。"
            )
        return (
            f"- escalation【{role}】{esc_kind}（via {src}）：{question}"
            " ——可 update_synthesis 记分歧、cancel_worker、"
            "ask_user 请用户裁决、或 post_note 给指导。"
        )
    if ev.kind is CoordinationEventKind.TIMEOUT:
        rid = p.get("run_id") or "?"
        role = p.get("role") or rid
        elapsed = p.get("elapsed_s")
        status = p.get("status") or "running"
        reason = p.get("reason") or "运行过久"
        hard = p.get("hard")
        hard_bit = "【硬收尾】" if hard else ""
        # Surface the full run_id so the CEO can copy it straight into
        # cancel_worker (role/short names alone silently never cancel).
        if elapsed is not None:
            return (
                f"- timeout{hard_bit}【{role}】run_id={rid} status={status}，"
                f"已运行 {elapsed}s（阈值 {p.get('threshold_s', '?')}s）：{reason}"
            )
        return f"- timeout{hard_bit}【{role}】run_id={rid}：{reason}"
    if ev.kind is CoordinationEventKind.ALL_COMPLETED:
        done = p.get("completed", 0)
        total = p.get("total", session.total_workers)
        if p.get("cancelled") or p.get("error"):
            lines = [
                f"- all_completed：调度中断，基于已完成部分收口（{done}/{total}）。"
            ]
        else:
            lines = [
                f"- all_completed：团队已全部结束（{done}/{total}）。请做最终合成并收口。"
            ]
        output = p.get("output")
        if isinstance(output, str) and output.strip():
            lines.append(f"团队成品：\n{output.strip()}")
        if not (p.get("cancelled") or p.get("error")):
            lines.append(
                "质量面敏感成品（成篇/构建/审查类）若未经独立审计，先派审计再收尾。"
            )
        lines.append(
            "最终合成按【终稿纪律】写：交付物在前、过程简述至多一段，"
            "不粘贴协调事件 / escalation 原文 / 中间合成草稿；未交付的承诺产物显式列出。"
        )
        return "\n".join(lines)
    if ev.kind is CoordinationEventKind.DRIVE_CANCELLED:
        done = p.get("completed", 0)
        total = p.get("total", session.total_workers)
        return (
            f"- drive_cancelled：调度中断，基于已完成部分收口（{done}/{total}）。"
            "请基于已完成队员产出做最终合成并收口；未完成部分勿当作已交付。"
        )
    if ev.kind is CoordinationEventKind.BOUNDARY_YIELD:
        reason = p.get("reason") or "?"
        brief = p.get("brief") or ""
        if reason == "checkpoint":
            detail = f" 已完成摘要：{brief}" if brief.strip() else ""
            return (
                f"- boundary_yield（checkpoint）：这些节点要求用户把关，"
                "必须立即用 ask_user（blocking）把关键内容交用户拍板，"
                f"不得自行替用户决定。{detail}"
            )
        return (
            f"- boundary_yield（{reason}）：计划在波边界让出——"
            f"{brief or '请用 replan 续跑或收口'}。"
        )
    if ev.kind is CoordinationEventKind.USER_INTERJECTION:
        iid = p.get("interjection_id") or "?"
        text = (p.get("content") or "").strip()
        lines = [f"- user_interjection（id={iid}）：老板中途插话——「{text}」"]
        atts = p.get("attachments")
        if isinstance(atts, list):
            for a in atts:
                if not isinstance(a, dict):
                    continue
                name = a.get("name") or "?"
                wp = a.get("workspace_path") or ""
                binary = bool(a.get("binary"))
                path_bit = f" → {wp}" if isinstance(wp, str) and wp.strip() else ""
                mark = "（二进制）" if binary else ""
                lines.append(f"  附件：{name}{path_bit}{mark}")
        lines.append(
            "  相关：图内处置（update_synthesis / delegate 追加队员 / cancel_worker）。"
        )
        lines.append(
            "  无关（独立新活）：必须 queue_user_message(interjection_id=…) 转入对话级排队，"
            "当前回合结束后自动起新回合；勿假装已办、勿丢弃。"
        )
        return "\n".join(lines)
    return f"- {ev.kind.value}：{p}"


def blurb_from_state(state: object) -> str:
    """Best-effort one-line blurb; accepts RunState or falls back."""
    try:
        from agentcore.runtime.runs.types import RunState

        if isinstance(state, RunState):
            return worker_output_blurb(state)
    except Exception:  # noqa: BLE001
        pass
    content = getattr(state, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip().splitlines()[0][:80]
    return "（无摘要）"

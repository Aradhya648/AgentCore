"""Map ask_user checkpoint responses to tool results (live + resume shared)."""

from __future__ import annotations

from agentcore.runtime.checkpoints import CheckpointDecision, CheckpointResponse
from agentcore.tools.protocol import ToolEffect, ToolResult


def ask_user_tool_result(response: CheckpointResponse) -> ToolResult:
    """Map the user's ask_user answer to the tool result the CEO loop consumes.

    The single source of truth for both the live tool (``AskUserTool.execute``) and
    a durable resume (``runtime/pipeline.resume_chat_pipeline``): submit feeds back as
    a ``CONTINUE`` result (the CEO resumes); stop returns an ``INTERACT`` (terminal)
    result whose closing note rides as ``final_text`` so the engine — or the resume —
    ends the turn gracefully with that text; a timeout hands control back to the CEO to
    wrap up on its own. Pure (no SSE side-effect): the caller streams the stop's
    ``final_text`` via ``content_delta`` (it is persist-only, the engine never re-emits
    it).

    答复正文 (α 答复模型): the desktop composes the user's per-question picks + style +
    free-form note into ONE readable ``note`` string (the picks live in the UI, so the
    answer is composed where the data is — no structured wire payload the only-reader CEO
    would just flatten back to prose anyway).
    """
    decision = response.decision
    if decision is CheckpointDecision.ADJUST:
        raise ValueError("ask_user checkpoints do not accept ADJUST; use CONTINUE with note")
    picks = "、".join(response.selected)
    note = response.note.strip()
    if decision is CheckpointDecision.CONTINUE:
        if note and picks:
            output = f"用户选择：{picks}；并补充：\n{note}\n请据此继续。"
        elif note:
            # The desktop's composed answer (per-question picks + style + note) rides here.
            output = f"用户答复：\n{note}\n请据此继续。"
        elif picks:
            output = f"用户选择：{picks}。请按此继续。"
        else:
            output = "用户确认：按你提出的方向继续。"
        return ToolResult(tool_call_id="", success=True, output=output)
    if decision is CheckpointDecision.STOP:
        closing = note or "好的，已按你的要求停止本回合。"
        return ToolResult(
            tool_call_id="",
            success=True,
            output="用户选择停止本回合。",
            effect=ToolEffect.INTERACT,
            final_text=closing,
        )
    # TIMEOUT — never silently picked a branch; let the CEO decide how to close.
    return ToolResult(
        tool_call_id="",
        success=True,
        output="用户未在时限内回应。请基于目前已掌握的信息，自行决定如何稳妥收尾。",
    )


def ask_user_organize_plan_result(
    response: CheckpointResponse, *, plan_id: str, kept_count: int
) -> ToolResult:
    """CONTINUE result for organize_plan — embeds plan_id for file_batch binding."""
    base = ask_user_tool_result(response)
    if response.decision is not CheckpointDecision.CONTINUE:
        return base
    suffix = (
        f"\n整理方案已确认：plan_id={plan_id}，保留 {kept_count} 项。"
        "请用 file_batch(organize_plan_id=该 id, operations=保留项) 分批执行"
        f"（每批≤50），勿再弹审批。完成后可用 file_batch(organize_undo=true) 撤销。"
    )
    return ToolResult(
        tool_call_id="",
        success=True,
        output=(base.output or "") + suffix,
    )

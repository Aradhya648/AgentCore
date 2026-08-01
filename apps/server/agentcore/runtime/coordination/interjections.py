"""协调中用户插话生命周期（S1）：received → addressed / queued / failed。

- 活跃协调：进 CEO 队列；图内处置 → addressed；无关 → queue_user_message → queued。
- 收口/已结束：未消化自动升格对话 FIFO（queued），禁止「仅协调可用」死路。
- durable ``user_interjection`` 由调用方保证同 id 语义更新；发送方确认流勿重复落 journal。
"""

from __future__ import annotations

from typing import Any

from agentcore.core.logging import get_logger
from agentcore.runtime.events import user_interjection
from agentcore.workspace.attachments import interjection_attachment_meta

logger = get_logger(__name__)

InterjectionStatus = str  # received | addressed | queued | failed


def _att_meta(stashed: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not stashed:
        return None
    meta = interjection_attachment_meta(list(stashed.get("attachments") or []))
    return meta or None


def emit_interjection_status(
    sink: Any | None,
    *,
    session: Any,
    interjection_id: str,
    content: str,
    status: InterjectionStatus,
    note: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    """Emit durable status update on the live turn sink (when available)."""
    if sink is None:
        sink = getattr(session, "event_sink", None)
    if sink is None:
        return
    sink.emit(
        user_interjection(
            interjection_id=interjection_id,
            execution_id=session.execution_id,
            content=content,
            status=status,
            note=note,
            attachments=attachments,
        )
    )


def note_interjections_injected(session: Any, events: list[Any]) -> None:
    """Mark USER_INTERJECTION ids as awaiting CEO disposition (图内 or queue)."""
    from agentcore.runtime.coordination.session import CoordinationEventKind

    for ev in events:
        if getattr(ev, "kind", None) is not CoordinationEventKind.USER_INTERJECTION:
            continue
        payload = getattr(ev, "payload", None) or {}
        iid = str(payload.get("interjection_id") or "").strip()
        if iid:
            session.awaiting_disposition.add(iid)


def address_awaiting_interjections(
    session: Any,
    sink: Any | None = None,
    *,
    note: str | None = None,
) -> list[str]:
    """图内处置成功后：将仍 pending 且已注入 CEO 的插话标为 addressed。"""
    addressed: list[str] = []
    note_text = note or "已在本回合消化"
    for iid in list(session.awaiting_disposition):
        stashed = session.get_interjection(iid)
        if stashed is None:
            session.awaiting_disposition.discard(iid)
            continue
        content = str(stashed.get("content") or "").strip()
        session.take_interjection(iid)
        session.awaiting_disposition.discard(iid)
        session.dispositioned_interjections.add(iid)
        emit_interjection_status(
            sink,
            session=session,
            interjection_id=iid,
            content=content,
            status="addressed",
            note=note_text,
            attachments=_att_meta(stashed),
        )
        addressed.append(iid)
        logger.info(
            "coordination.user_interjection_addressed",
            execution_id=session.execution_id,
            interjection_id=iid,
            via="in_graph",
        )
    return addressed


def enqueue_interjection_to_fifo(
    session: Any,
    interjection_id: str,
    stashed: dict[str, Any],
    *,
    sink: Any | None = None,
    reason: str | None = None,
) -> tuple[bool, str, Any | None]:
    """Move one stashed interjection onto the conversation turn FIFO.

    Returns ``(ok, message, queue_status_or_none)``. On failure the caller should
    emit ``failed`` (or ``addressed`` when终局已答).
    """
    content = str(stashed.get("content") or "").strip()
    conversation_id = str(
        stashed.get("conversation_id") or session.conversation_id or ""
    ).strip()
    if not content or not conversation_id:
        return False, "插话缺少 content / conversation_id，无法转入排队。", None

    from agentcore.runtime.turn_queue import new_queued_turn, turn_queue

    try:
        status = turn_queue.enqueue(
            conversation_id,
            new_queued_turn(
                content=content,
                user_id=str(stashed.get("user_id") or ""),
                attachments=list(stashed.get("attachments") or []),
                requires_tools=bool(stashed.get("requires_tools")),
                x_client_platform=stashed.get("x_client_platform"),
                llm_credentials=stashed.get("llm_credentials"),
                llm_supports_tools=stashed.get("llm_supports_tools"),
            ),
        )
    except Exception as exc:  # noqa: BLE001 — surface as failed, never raise into CEO
        logger.exception(
            "coordination.user_interjection_enqueue_failed",
            execution_id=session.execution_id,
            interjection_id=interjection_id,
        )
        return False, f"转入对话级排队失败：{exc}", None

    note = reason or "与当前团队任务无关，已排到下一回合"
    session.awaiting_disposition.discard(interjection_id)
    session.dispositioned_interjections.add(interjection_id)
    emit_interjection_status(
        sink,
        session=session,
        interjection_id=interjection_id,
        content=content,
        status="queued",
        note=note,
        attachments=_att_meta(stashed),
    )
    logger.info(
        "coordination.user_interjection_queued",
        execution_id=session.execution_id,
        interjection_id=interjection_id,
        queue_id=status.queue_id,
        position=status.position,
    )
    return (
        True,
        (
            f"已将插话转入对话级排队（位置 {status.position}/"
            f"{status.queue_depth}）。当前回合结束后自动起新回合处理。"
        ),
        status,
    )


def mark_interjection_failed(
    session: Any,
    interjection_id: str,
    stashed: dict[str, Any] | None,
    *,
    sink: Any | None = None,
    note: str,
) -> None:
    content = str((stashed or {}).get("content") or "").strip() or "（无正文）"
    session.awaiting_disposition.discard(interjection_id)
    session.dispositioned_interjections.add(interjection_id)
    if stashed is not None:
        session.take_interjection(interjection_id)
    emit_interjection_status(
        sink,
        session=session,
        interjection_id=interjection_id,
        content=content,
        status="failed",
        note=note,
        attachments=_att_meta(stashed),
    )
    logger.info(
        "coordination.user_interjection_failed",
        execution_id=session.execution_id,
        interjection_id=interjection_id,
    )


def mark_interjection_addressed(
    session: Any,
    interjection_id: str,
    stashed: dict[str, Any] | None,
    *,
    sink: Any | None = None,
    note: str | None = None,
) -> None:
    content = str((stashed or {}).get("content") or "").strip() or "（无正文）"
    if stashed is not None:
        session.take_interjection(interjection_id)
    session.awaiting_disposition.discard(interjection_id)
    session.dispositioned_interjections.add(interjection_id)
    emit_interjection_status(
        sink,
        session=session,
        interjection_id=interjection_id,
        content=content,
        status="addressed",
        note=note or "终局已回应",
        attachments=_att_meta(stashed),
    )
    logger.info(
        "coordination.user_interjection_addressed",
        execution_id=session.execution_id,
        interjection_id=interjection_id,
        via="final",
    )


def final_answer_covers(session: Any) -> bool:
    """True when CEO already produced a synthesis draft worth treating as回应."""
    return bool(str(getattr(session, "draft", "") or "").strip())


def promote_pending_on_close(session: Any) -> list[str]:
    """收口：未消化插话自动升格对话 FIFO；入队失败且终局有稿 → addressed，否则 failed。"""
    sink = getattr(session, "event_sink", None)
    promoted: list[str] = []
    for iid in list(session.pending_interjections.keys()):
        stashed = session.take_interjection(iid)
        if stashed is None:
            continue
        ok, msg, _status = enqueue_interjection_to_fifo(
            session,
            iid,
            stashed,
            sink=sink,
            reason="协调已收口，已自动转入下一回合",
        )
        if ok:
            promoted.append(iid)
            continue
        if final_answer_covers(session):
            mark_interjection_addressed(
                session,
                iid,
                stashed,
                sink=sink,
                note="排队未果，但终局已回应",
            )
            promoted.append(iid)
        else:
            mark_interjection_failed(
                session,
                iid,
                stashed,
                sink=sink,
                note=msg or "未能排队，请重试或再说一次",
            )
    session.awaiting_disposition.clear()
    if promoted:
        logger.info(
            "coordination.user_interjection_promoted_on_close",
            execution_id=session.execution_id,
            count=len(promoted),
            interjection_ids=promoted,
        )
    return promoted

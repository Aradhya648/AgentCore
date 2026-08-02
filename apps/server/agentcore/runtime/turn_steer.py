"""Classic in-flight turn steer (同对话再发 P1).

When a solo / non-coordination turn is mid-flight and the user sends
``delivery=steer``, the message is parked here (process-local) until the
captain ``react_loop`` drains it at the next ReAct step boundary and injects
it as a user-role LLM message — **not** a new turn, **not** a hard stop.

Acceptance window = captain ``react_loop`` lifetime for that conversation
(``begin_accepting`` … ``end_accepting``). Outside the window the API falls
back to FIFO ``turn_queue`` (may carry ``degraded_from=steer``).

Parallel to coordination ``user_interjection`` / ``await_coordination_injection``
— do **not** merge, fake a CoordinationSession, or reuse ``coord_inject``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.llm.provider.protocol import LLMMessage

logger = get_logger(__name__)

# Prefix so the model treats the inject as mid-turn correction, not a new task.
_STEER_USER_PREFIX = (
    "[用户中途补充] 以下是用户对当前任务的补充或纠偏。"
    "请继续完成当前任务，并把这些内容纳入后续步骤：\n\n"
)

_CONTENT_PREVIEW_MAX = 200


@dataclass(slots=True)
class PendingTurnSteer:
    """One classic mid-turn steer waiting for the next ReAct step boundary."""

    steer_id: str
    conversation_id: str
    content: str
    user_id: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    requires_tools: bool = False
    x_client_platform: str | None = None
    llm_credentials: Any = None
    llm_supports_tools: bool | None = None


_pending: dict[str, list[PendingTurnSteer]] = {}
_accepting: set[str] = set()


def content_preview(content: str, *, max_len: int = _CONTENT_PREVIEW_MAX) -> str:
    """Truncate steer body for EPHEMERAL SSE toast payloads."""
    text = (content or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _format_steer_attachment_lines(attachments: list[dict[str, Any]]) -> list[str]:
    """Readable attachment inventory for injected user text (parity with coord inject)."""
    lines: list[str] = []
    for a in attachments:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        name = "?" if not isinstance(name, str) or not name.strip() else name.strip()
        wp = a.get("workspace_path") or ""
        path_bit = f" → {wp}" if isinstance(wp, str) and wp.strip() else ""
        mark = "（二进制）" if bool(a.get("binary")) else ""
        lines.append(f"附件：{name}{path_bit}{mark}")
    return lines


def format_steer_user_message(
    content: str,
    attachments: list[dict[str, Any]] | None = None,
) -> str:
    """User-role text injected into the live LLM window.

    Attachments are surfaced as a readable inventory (LLMMessage is text-only here;
    same posture as coordination ``user_interjection`` brief lines). Never silently drop.
    """
    body = (content or "").strip()
    text = f"{_STEER_USER_PREFIX}{body}" if body else _STEER_USER_PREFIX.rstrip()
    att_lines = _format_steer_attachment_lines(list(attachments or []))
    if att_lines:
        text = f"{text}\n\n" + "\n".join(att_lines)
    return text


def is_accepting(conversation_id: str) -> bool:
    return bool(conversation_id.strip()) and conversation_id.strip() in _accepting


def begin_accepting(conversation_id: str) -> None:
    """Open the classic-steer window for this conversation (captain loop enter).

    Drops any stale pending from a prior crashed loop so we never inject orphans.
    """
    cid = conversation_id.strip()
    if not cid:
        return
    stale = _pending.pop(cid, None)
    if stale:
        logger.warning(
            "turn_steer.stale_cleared",
            conversation_id=cid,
            dropped=len(stale),
        )
    _accepting.add(cid)
    logger.debug("turn_steer.accepting_begin", conversation_id=cid)


def end_accepting(conversation_id: str) -> list[PendingTurnSteer]:
    """Close the window; return undrained leftovers for FIFO promote."""
    cid = conversation_id.strip()
    if not cid:
        return []
    _accepting.discard(cid)
    leftovers = _pending.pop(cid, [])
    if leftovers:
        logger.info(
            "turn_steer.accepting_end_leftovers",
            conversation_id=cid,
            leftover=len(leftovers),
        )
    else:
        logger.debug("turn_steer.accepting_end", conversation_id=cid)
    return leftovers


def try_enqueue(
    *,
    conversation_id: str,
    content: str,
    user_id: str = "",
    attachments: list[dict[str, Any]] | None = None,
    requires_tools: bool = False,
    x_client_platform: str | None = None,
    llm_credentials: Any = None,
    llm_supports_tools: bool | None = None,
) -> PendingTurnSteer | None:
    """Park a classic steer if the captain loop is accepting; else ``None`` (→ FIFO)."""
    cid = conversation_id.strip()
    if not cid or cid not in _accepting:
        return None
    item = PendingTurnSteer(
        steer_id=new_id(),
        conversation_id=cid,
        content=content,
        user_id=user_id,
        attachments=list(attachments or []),
        requires_tools=requires_tools,
        x_client_platform=x_client_platform,
        llm_credentials=llm_credentials,
        llm_supports_tools=llm_supports_tools,
    )
    bucket = _pending.setdefault(cid, [])
    bucket.append(item)
    logger.info(
        "turn_steer.enqueued",
        conversation_id=cid,
        steer_id=item.steer_id,
        pending=len(bucket),
        preview=content_preview(content, max_len=80),
    )
    return item


def drain(conversation_id: str) -> list[PendingTurnSteer]:
    """FIFO drain all pending steers for ``conversation_id`` (never blocks)."""
    cid = conversation_id.strip()
    if not cid:
        return []
    items = _pending.pop(cid, [])
    if items:
        logger.info(
            "turn_steer.drained",
            conversation_id=cid,
            count=len(items),
        )
    return items


def drain_as_messages(conversation_id: str) -> list[LLMMessage]:
    """Drain pending steers and map each to a user-role LLM message."""
    return [
        LLMMessage(
            role="user",
            content=format_steer_user_message(item.content, item.attachments),
        )
        for item in drain(conversation_id)
    ]


def peek_count(conversation_id: str) -> int:
    return len(_pending.get(conversation_id.strip(), ()))


def _emit_degraded_turn_queued(
    *,
    conversation_id: str,
    queue_id: str,
    position: int,
    queue_depth: int,
    steer_id: str,
) -> bool:
    """Honest signal: accepted steer could not soft-insert → now FIFO.

    Clients that already toasted ``turn_steer_accepted`` must see
    ``turn_queued.degraded_from=steer`` on the live host sink. Returns whether
    a live sink received the event.
    """
    from agentcore.runtime.events import turn_queued
    from agentcore.runtime.turn_runs import turn_runs

    run = turn_runs.get(conversation_id)
    if run is None or run.task.done():
        logger.info(
            "turn_steer.promoted_to_queue_no_sink",
            conversation_id=conversation_id,
            steer_id=steer_id,
            queue_id=queue_id,
            position=position,
            queue_depth=queue_depth,
            degraded_from="steer",
        )
        return False
    run.sink.emit(
        turn_queued(
            queue_id=queue_id,
            position=position,
            queue_depth=queue_depth,
            conversation_id=conversation_id,
            degraded_from="steer",
        )
    )
    return True


def promote_leftovers_to_queue(leftovers: list[PendingTurnSteer]) -> int:
    """Re-home undrained steers onto the conversation FIFO (回合收口竞态).

    Keeps user content (enqueue + drain unchanged). Emits
    ``turn_queued.degraded_from=steer`` on a live ``turn_runs`` sink when present
    so clients do not keep the false 「已插入」 toast. No live sink → clear log only.

    Returns how many items were enqueued. Caller should only invoke after
    ``end_accepting`` so a live loop cannot race-drain the same items.
    """
    if not leftovers:
        return 0
    from agentcore.runtime.turn_queue import new_queued_turn, turn_queue

    n = 0
    for item in leftovers:
        status = turn_queue.enqueue_and_ensure_drain(
            item.conversation_id,
            new_queued_turn(
                content=item.content,
                user_id=item.user_id,
                attachments=item.attachments,
                requires_tools=item.requires_tools,
                x_client_platform=item.x_client_platform,
                llm_credentials=item.llm_credentials,
                llm_supports_tools=item.llm_supports_tools,
            ),
        )
        emitted = _emit_degraded_turn_queued(
            conversation_id=item.conversation_id,
            queue_id=status.queue_id,
            position=status.position,
            queue_depth=status.queue_depth,
            steer_id=item.steer_id,
        )
        n += 1
        logger.info(
            "turn_steer.promoted_to_queue",
            conversation_id=item.conversation_id,
            steer_id=item.steer_id,
            queue_id=status.queue_id,
            position=status.position,
            queue_depth=status.queue_depth,
            emitted_turn_queued=emitted,
            degraded_from="steer",
        )
    return n


def _reset_for_tests() -> None:
    """Test helper — clear process-local state."""
    _pending.clear()
    _accepting.clear()

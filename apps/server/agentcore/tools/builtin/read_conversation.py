"""read_conversation — Worker deep-read of one past chat (messages + journal).

Worker-only; privacy-gated via ``manual_wire`` + ``_wire_worker_conversation_log_tools``.
Supports cursor continuation so a multi-chunk transcript can be reassembled — never
silently summarised via the default 4k ToolResult head+tail truncate.
"""

from __future__ import annotations

from typing import Any

from agentcore.conversation.log_export import (
    MAX_CHUNK_CHARS,
    chunk_transcript,
    render_conversation_log,
)
from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    TurnJournalRepository,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

_SOFT_MISS = (
    "无法打开该对话（可能不存在、已删除、为 handoff 宿主，或不在可访问范围内）。"
)
_HOST_MISS = "那是本回合正在进行的宿主会话——请直接看本会话工作记忆，无需 read_conversation。"


class ReadConversationTool:
    """Open one owner-scoped conversation as a deep markdown transcript."""

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
        manual_wire=True,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_conversation",
            description=(
                "按 conversation_id 读取一场历史对话的整段原文与过程（用户/助手正文、思考、"
                "工具调用与结果、辩论、证据与引用）。超长时返回 truncated + next_cursor，"
                "请带着 cursor 续读并自行拼回全文——禁止把单次截断当成「摘要版全文」。"
                "读完后向 CEO 回传蒸馏结论 + 出处 id/标题（默认不要把百万字原文原样塞回）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "conversation_id": {
                        "type": "string",
                        "description": "要打开的对话 id（来自 search_conversations）。",
                    },
                    "cursor": {
                        "type": "string",
                        "description": "续读游标；首轮省略 = 从最早消息起。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": (
                            f"本块最大字符数（可选）；服务端硬顶 {MAX_CHUNK_CHARS}。"
                        ),
                    },
                },
                "required": ["conversation_id"],
            },
            category=ToolCategory.SEARCH,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        cid = str(arguments.get("conversation_id") or "").strip()
        if not cid:
            msg = "缺少 conversation_id 参数。"
            return ToolResult(tool_call_id="", success=False, output=msg, error=msg)

        if context.conversation_id and cid == context.conversation_id:
            logger.info(
                "conversation_log.read",
                result="host_exclude",
                conversation_id=cid,
                run_id=context.run_id,
            )
            return ToolResult(
                tool_call_id="",
                success=True,
                output=_HOST_MISS,
                display={
                    "title": "",
                    "conversation_id": cid,
                    "truncated": False,
                    "depth": "full",
                },
            )

        cursor = arguments.get("cursor")
        cursor_s = str(cursor).strip() if cursor else None
        max_chars: int | None = None
        if arguments.get("max_chars") is not None:
            try:
                max_chars = int(arguments["max_chars"])
            except (TypeError, ValueError):
                max_chars = None

        async with async_session_factory() as session:
            conv = await ConversationRepository(session).get_by_id(
                cid, user_id=context.user_id
            )
            # Soft miss: wrong owner / soft-deleted / missing / handoff host.
            if conv is None or conv.mode == "handoff":
                logger.info(
                    "conversation_log.read",
                    result="soft_miss",
                    conversation_id=cid,
                    run_id=context.run_id,
                )
                return ToolResult(
                    tool_call_id="",
                    success=True,
                    output=_SOFT_MISS,
                    display={
                        "title": "",
                        "conversation_id": cid,
                        "truncated": False,
                        "depth": "full",
                    },
                )

            messages = list(
                await MessageRepository(session).list_all_for_conversation(cid)
            )
            assistant_ids = [m.id for m in messages if m.role == "assistant"]
            journal_map = await TurnJournalRepository(session).load_map(assistant_ids)
            full = render_conversation_log(conv, messages, journal_map)
            chunk = chunk_transcript(
                full,
                conversation=conv,
                messages=messages,
                cursor=cursor_s,
                max_chars=max_chars,
            )

        # Build model-facing output: metadata header + transcript body.
        header_lines = [
            f"title: {chunk.title}",
            f"conversation_id: {chunk.conversation_id}",
            f"messages: {chunk.message_count}",
            f"time_range: {chunk.started_at or '—'} → {chunk.ended_at or '—'}",
            f"truncated: {chunk.truncated}",
            f"offset: {chunk.char_offset}/{chunk.total_chars}",
        ]
        if chunk.next_cursor:
            header_lines.append(f"next_cursor: {chunk.next_cursor}")
        header_lines.append("")
        header_lines.append("--- transcript ---")
        header_lines.append("")
        output = "\n".join(header_lines) + chunk.transcript

        # HARD: output_limit must cover this chunk — never default 4k head+tail.
        output_limit = max(len(output), MAX_CHUNK_CHARS)

        logger.info(
            "conversation_log.read",
            result="ok",
            conversation_id=cid,
            truncated=chunk.truncated,
            chars=len(chunk.transcript),
            run_id=context.run_id,
        )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            output_limit=output_limit,
            display={
                "title": chunk.title,
                "conversation_id": chunk.conversation_id,
                "truncated": chunk.truncated,
                "depth": "full",
            },
            metadata={
                "next_cursor": chunk.next_cursor,
                "truncated": chunk.truncated,
                "stats": {
                    "message_count": chunk.message_count,
                    "char_offset": chunk.char_offset,
                    "total_chars": chunk.total_chars,
                },
            },
        )

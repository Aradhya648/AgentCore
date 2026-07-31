"""search_conversations — Worker directory / search over the owner's past chats.

Worker-only (``AUDIENCE_WORKER_ONLY`` + ``ToolSurface.WORKER_ONLY`` + ``manual_wire``).
Wired after ``build_worker_registry`` when ``conversation_history_access`` is on —
mirrors ``_wire_worker_memory_tools``. Never reaches the CEO toolset
(``build_ceo_tool_registry`` only collects builtin CEO-audience tools).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentcore.conversation.log_export import search_snippet_from_messages
from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import ConversationRepository, MessageRepository
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

_SEARCH_HARD_CAP = 30
_DEFAULT_LIMIT = 10
_MAX_LOOKBACK_HOURS = 168
_SOFT_MISS = (
    "未找到可查阅的历史对话（可能不存在、已删除，或不在可访问范围内）。"
)


class SearchConversationsTool:
    """List / search the owner's conversations for on-demand log recall."""

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
        manual_wire=True,
    )

    # Host conversation's project (None = bare chat). Used when scope=project.
    folder_id: str | None = None

    def __init__(self, *, folder_id: str | None = None) -> None:
        self.folder_id = folder_id

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="search_conversations",
            description=(
                "检索当前用户账号下的历史对话目录（标题匹配；query 为空则按最近更新列出）。"
                "用于查阅「上次 / 以前」某场讨论的原文与过程——先搜到 conversation_id，再"
                "用 read_conversation 打开。不含本回合正在进行的宿主会话；不含已软删 / handoff"
                "宿主。偏好与巩固后的事实请用记忆主题（consult_memory），不要用本工具代替。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选；标题关键词。空 = 按更新时间列最近对话。",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["all", "project", "global_chats"],
                        "description": (
                            "all=全账号（默认）；project=宿主对话所在项目；"
                            "global_chats=仅裸聊（无项目）。"
                        ),
                    },
                    "folder_id": {
                        "type": "string",
                        "description": "可选；指定其它项目 id（须属同一用户）。",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "是否包含已归档对话（默认 false）。",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"返回条数，默认 {_DEFAULT_LIMIT}，硬顶 {_SEARCH_HARD_CAP}。"
                        ),
                    },
                    "updated_within_hours": {
                        "type": "integer",
                        "description": (
                            "可选；只返回近 N 小时内有更新的对话"
                            f"（1–{_MAX_LOOKBACK_HOURS}）。日复盘等周期任务应设置。"
                        ),
                    },
                },
                "required": [],
            },
            category=ToolCategory.SEARCH,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        scope = str(arguments.get("scope") or "all").strip() or "all"
        if scope not in {"all", "project", "global_chats"}:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="scope 须为 all / project / global_chats。",
                error="invalid scope",
            )
        include_archived = bool(arguments.get("include_archived") or False)
        try:
            limit = int(arguments.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _SEARCH_HARD_CAP))

        updated_after: datetime | None = None
        raw_hours = arguments.get("updated_within_hours")
        if raw_hours is not None and raw_hours != "":
            try:
                hours = int(raw_hours)
            except (TypeError, ValueError):
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="updated_within_hours 须为正整数。",
                    error="invalid updated_within_hours",
                )
            hours = max(1, min(hours, _MAX_LOOKBACK_HOURS))
            updated_after = datetime.now(UTC) - timedelta(hours=hours)

        explicit_folder = str(arguments.get("folder_id") or "").strip() or None
        folder_id: str | None = None
        global_chats_only = False
        soft_note: str | None = None
        if explicit_folder:
            folder_id = explicit_folder
        elif scope == "project":
            if not self.folder_id:
                soft_note = (
                    "当前是裸聊（无项目）；已按 all 范围检索。"
                    "请改用 scope=all 或 global_chats。"
                )
            else:
                folder_id = self.folder_id
        elif scope == "global_chats":
            global_chats_only = True

        host_id = context.conversation_id
        async with async_session_factory() as session:
            # Owner-check explicit folder_id (do not leak other users' folder ids).
            if explicit_folder:
                from agentcore.db.repositories import FolderRepository

                folder = await FolderRepository(session).get_by_id(
                    explicit_folder, user_id=context.user_id
                )
                if folder is None:
                    logger.info(
                        "conversation_log.search",
                        result="folder_miss",
                        user_id=context.user_id,
                    )
                    return ToolResult(
                        tool_call_id="",
                        success=True,
                        output=_SOFT_MISS,
                        display={"result_count": 0, "scope": scope},
                    )
            rows = await ConversationRepository(session).search_with_projections(
                context.user_id,
                query,
                limit=limit,
                folder_id=folder_id,
                include_archived=include_archived,
                global_chats_only=global_chats_only,
                exclude_conversation_id=host_id or None,
                updated_after=updated_after,
            )
            # Optional snippets (best-effort; keep search cheap).
            msg_repo = MessageRepository(session)
            for row in rows:
                try:
                    msgs = await msg_repo.list_all_for_conversation(row["conversation_id"])
                    snippet = search_snippet_from_messages(msgs, query)
                    if snippet:
                        row["snippet"] = snippet
                except Exception:  # noqa: BLE001 — snippet is best-effort
                    pass

        logger.info(
            "conversation_log.search",
            result="ok",
            user_id=context.user_id,
            count=len(rows),
            scope=scope,
            run_id=context.run_id,
        )
        if not rows:
            text = soft_note + "\n" + _SOFT_MISS if soft_note else _SOFT_MISS
            return ToolResult(
                tool_call_id="",
                success=True,
                output=text,
                display={"result_count": 0, "scope": scope},
            )

        lines: list[str] = []
        if soft_note:
            lines.append(soft_note)
            lines.append("")
        lines.append(f"找到 {len(rows)} 场对话（scope={scope}）：")
        lines.append("")
        for row in rows:
            folder_bit = (
                f" · 项目「{row['folder_name']}」"
                if row.get("folder_name")
                else (" · 裸聊" if not row.get("folder_id") else "")
            )
            arch = " · 已归档" if row.get("archived") else ""
            lines.append(
                f"- `{row['conversation_id']}` · {row['title']} · "
                f"{row.get('message_count', 0)} 条消息 · 更新 {row.get('updated_at') or '—'}"
                f"{folder_bit}{arch}"
            )
            if row.get("snippet"):
                lines.append(f"  摘要：{row['snippet']}")
        output = "\n".join(lines)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            output_limit=max(len(output), 4000),
            display={"result_count": len(rows), "scope": scope},
        )

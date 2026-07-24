"""remember — the user gives an explicit directive, so the CEO records it as a USER RULE.

The memory system splits how durable knowledge is written (Agent记忆与知识系统 §5.7 用户规则
入口① / §1.5 显式记住例外):

- **explicit user directive → user rule** (this tool): when the user clearly says「记住…」「以后
  都要…」「别再…」, the CEO records it as a ``role='rule', ai_maintained=false`` document — the
  user OWNS it, so the offline consolidation never rewrites it, and it injects with authoritative
  wording ahead of AI memory (§二 两档措辞). Effect is immediate: next turn's ``<rules>``.
- **inferred preference → offline consolidation** (NOT this tool): preferences merely observed in
  conversation stay with the two-layer consolidation pass, which writes ``ai_maintained=true``
  memory. The tool description steers the model to that split.

Same master-switch neutrality as user rules generally: a user rule is the user's own instruction,
not AI memory, so it is recorded whenever the user asks — turning off「AI 记忆」silences AI-grown
memory, not the user's explicit rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import DocumentRepository
from agentcore.memory.rules_injection import append_user_rule
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_CEO_ONLY,
    CeoWire,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)


@dataclass
class RememberTool:
    """CEO-only: record an explicit user directive as a user rule (immediate effect)."""

    registration = ToolRegistration(
        surface=ToolSurface.CEO_ORCHESTRATION,
        audience=AUDIENCE_CEO_ONLY,
        ceo_wire=CeoWire.MEMORY,
    )

    # The conversation's project (None for a bare chat). A ``scope='project'`` directive routes
    # the rule to this project's layer; without a project it stays global.
    folder_id: str | None = None

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="remember",
            description=(
                "把用户明确下达的指令记为「用户规则」——长期生效、注入后续每一轮对话，"
                "权威性高于 AI 记忆。仅当用户清楚地说「记住…」「以后都要…」「以后别…」等"
                "明确指令时使用；普通对话里推测出来的偏好不要用本工具，交给会话结束后的离线巩固。"
                "写入后立即生效，下一轮对话即注入。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记住的规则或事实（一句陈述句，用用户的语言）。",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "project"],
                        "description": (
                            "global=对所有对话生效（默认）；project=仅当前项目生效。"
                        ),
                    },
                },
                "required": ["content"],
            },
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        content = str(arguments.get("content") or "").strip()
        scope_token = str(arguments.get("scope") or "global").strip().lower()
        if not content:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="缺少 content。",
                error="缺少 content。",
            )
        # project scope only when the conversation is actually in a project; else global.
        folder_id = self.folder_id if scope_token == "project" and self.folder_id else None

        try:
            async with async_session_factory() as session:
                changed = await append_user_rule(
                    DocumentRepository(session),
                    context.user_id,
                    folder_id=folder_id,
                    content=content,
                )
        except Exception as e:  # noqa: BLE001 - a tool failure must not crash the turn
            logger.warning("memory.remember_failed", user_id=context.user_id, error=str(e))
            return ToolResult(
                tool_call_id="",
                success=False,
                output="记住失败，请稍后再试。",
                error=str(e),
            )

        if not changed:
            return ToolResult(
                tool_call_id="",
                success=True,
                output="这条规则已经记过了（未重复写入）。",
                display={"remembered": False, "content": content, "kind": "user_rule"},
            )

        logger.info(
            "memory.remember_written",
            user_id=context.user_id,
            scope="project" if folder_id else "global",
        )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已记为规则：{content}",
            display={"remembered": True, "content": content, "kind": "user_rule"},
        )


def build_remember_tool(*, folder_id: str | None = None) -> RememberTool:
    return RememberTool(folder_id=folder_id)

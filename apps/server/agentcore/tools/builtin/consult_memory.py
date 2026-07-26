"""consult_memory — the CEO pulls a memory TOPIC note's full text on demand (渐进披露).

CEO-only: wired in ``runtime.pipeline`` next to ``consult_skill`` and deliberately NOT
in ``build_builtin_registry`` (a delegated worker does not hold it). The user's memory is
a FOLDER (docs/03-AI核心/Agent记忆与知识系统.md §二): a small always-injected CORE note
(``画像.md``, rides every prompt via the ``<rules>`` section) plus any number of TOPIC notes
(``主题/<slug>.md``). The CEO's prompt carries a one-line「记忆主题目录」of the topic names
+ a 1-line summary each (``prompt.render_memory_topic_directory``);
when a topic is relevant it calls
``consult_memory(name)`` to feed that note's full body back into its own ReAct loop
(``ToolEffect.CONTINUE``), then acts on it. This keeps the常驻 prompt cheap while letting
deep, occasional knowledge live in the folder.

Gated by the long-term-memory master switch at wiring time (off ⇒ not wired AND the
directory is not rendered), so a user who turned memory off surfaces zero memory — the
same privacy off-ramp as the core-memory injection.

A wrong / unknown name is a soft miss: ``success=True`` (no ``error`` / no red failure),
lists the available topic names so the model can retry, and still logs
``consult_memory.miss``. Only a missing / empty ``name`` is a real parameter failure
(``success=False``). Empty topic libraries never wire this tool (see
``_assemble_ceo_toolset`` / ``_wire_worker_memory_tools``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.memory.store import (
    TOPIC_DIR,
    MemoryStore,
    is_topic_path,
    topic_path,
    topic_slug,
)
from agentcore.runtime.memory_consult_cache import lookup_consult, remember_consult
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    CeoWire,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

# A topic note can be a few hundred to a couple thousand chars; lift the model-facing
# truncation budget above the 4000 default so a longer note is never clipped mid-thought
# (mirrors consult_skill — a half-note teaches half a fact).
_CONSULT_OUTPUT_LIMIT = 8000


@dataclass
class ConsultMemoryTool:
    """The CEO's on-demand memory-recall tool: topic name → note body, fed back.

    ``folder_id`` is the conversation's project (None for a bare/global chat): when set, a
    topic name is resolved in the PROJECT scope first (more specific) then GLOBAL, and the
    "available topics" hint merges both scopes (Agent记忆与知识系统 §二).
    """

    registration = ToolRegistration(
        surface=ToolSurface.CEO_ORCHESTRATION,
        audience=AUDIENCE_BOTH,
        ceo_wire=CeoWire.MEMORY,
    )

    store: MemoryStore
    folder_id: str | None = None

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="consult_memory",
            description=(
                "按 name 查阅一条「记忆主题笔记」的全文：你的系统提示词里有一张「记忆主题目录」"
                "列出该用户可查阅的主题 name；当某主题与当前任务相关时，用本工具把它的全文拉回来"
                "（作为工具结果返回），读完据此执行。常驻的核心记忆（用户画像）已在提示词里、无需"
                "查阅；只有目录中列出的按需主题才用本工具拉取。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "要查阅的记忆主题名称，取自系统提示词「记忆主题目录」里列出的 name"
                            "（如 部署流程）。"
                        ),
                    },
                },
                "required": ["name"],
            },
            # A CEO orchestration primitive (sits beside consult_skill in
            # _CEO_ORCHESTRATION_TOOLS), NOT a「技能」-category tool. Like every category
            # it is declarative metadata only — the engine acts on the ToolResult, never
            # on a tool's name or category.
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def _available_topics(self, user_id: str) -> list[str]:
        """The user's topic names, merged across project + global scope (sorted, deduped)."""
        names = {
            topic_slug(m.path) for m in await self.store.list(user_id) if is_topic_path(m.path)
        }
        if self.folder_id:
            names |= {
                topic_slug(m.path)
                for m in await self.store.list(user_id, scope=self.folder_id)
                if is_topic_path(m.path)
            }
        return sorted(names)

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raw = str(arguments.get("name") or "").strip()
        # Be forgiving about how the model spells the name: accept a bare slug (部署流程),
        # a "主题/部署流程" path, or a "部署流程.md" filename — all resolve to the same note.
        # The store sanitizes path segments anyway, so a malformed name can only miss
        # (never escape the user's folder).
        slug = raw.removeprefix(f"{TOPIC_DIR}/").removesuffix(".md").strip()
        # Resume 段复用 kickoff 已查过的同一 key，避免同回合重复拉全文。
        if slug:
            cached = lookup_consult(slug)
            if cached is not None:
                logger.info("consult_memory.reuse", name=slug)
                return ToolResult(
                    tool_call_id="",
                    success=True,
                    output=cached,
                    output_limit=_CONSULT_OUTPUT_LIMIT,
                    display={"topic": slug, "reused": True},
                )
        body = ""
        # Which scope actually produced the body — surfaced in the hit log so a real run
        # (esp. a project-scoped resume) is verifiable: did consult_memory hit THIS project's
        # 主题 or fall back to global? Without it "命中项目主题" can't be confirmed from logs.
        hit_scope: str | None = None
        if slug:
            # The current project's note is more specific → try it first, then fall back to
            # the global note of the same name (Agent记忆与知识系统 §二).
            if self.folder_id:
                body = await self.store.load(
                    context.user_id, topic_path(slug), scope=self.folder_id
                )
                if body.strip():
                    hit_scope = "project"
            if not body.strip():
                body = await self.store.load(context.user_id, topic_path(slug))
                if body.strip():
                    hit_scope = "global"
        if not slug:
            msg = "缺少 name 参数。"
            available = "、".join(await self._available_topics(context.user_id))
            if available:
                msg += f" 可查阅的主题：{available}。"
            logger.info("consult_memory.miss", name=raw, folder_id=self.folder_id)
            return ToolResult(tool_call_id="", success=False, output=msg, error=msg)
        if not body.strip():
            available = "、".join(await self._available_topics(context.user_id))
            head = f"没有名为 '{raw}' 的记忆主题。"
            tail = f" 可查阅的主题：{available}。" if available else " 当前没有任何记忆主题。"
            logger.info("consult_memory.miss", name=raw, folder_id=self.folder_id)
            # Soft miss: wrong name is informational, not a tool failure (avoids red-error UX).
            return ToolResult(tool_call_id="", success=True, output=head + tail)

        remember_consult(slug, body)
        logger.info("consult_memory.hit", name=slug, scope=hit_scope)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=body,
            output_limit=_CONSULT_OUTPUT_LIMIT,
            # Render-oriented twin of ``output`` (工具结果富渲染): the topic name lets the
            # desktop label the step「查阅记忆：{topic}」and frame the pulled note instead
            # of dumping the raw body as anonymous tool text. 形状是数据不是模式.
            display={"topic": slug},
        )

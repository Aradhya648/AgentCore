"""post_note — a worker's「贴便签」channel: broadcast a decision / heads-up to siblings.

Worker-only, the broadcast dual of ``escalate`` (which is the worker's UPWARD channel to
the CEO). Wired into the delegated worker toolset (``build_worker_registry``) and NOT into
``build_builtin_registry`` — so it never reaches the CEO's own toolset or the read-only
capability catalog as a CEO tool, mirroring ``escalate``.

It posts a short one-line note to the batch's :class:`~agentcore.runtime.runs.notewall.NoteWall`
(团队便签墙, §2.2 通): a fire-and-forget side effect — the call returns immediately telling
the worker to keep going, never waiting for a reply (so it can't become a chat / can't spin).
The note is pushed into concurrent siblings before their next step (推增量), letting the team
build on each other's evolving work instead of each guessing in isolation.

Three kinds: ``decision`` (我定了 X — a choice others depend on: interface / field name /
format / naming), ``heads_up`` (提个醒 Y — a pitfall / discovery), and ``claim`` (我领了 Z — a
piece of work / file this worker is taking, so a sibling doesn't duplicate it: the proactive,
visible counterpart of ``WriteCoordinator``'s hard file guard).
Off a team (solo worker / CEO / tests) ``note_wall`` is ``None`` → a clean「无并行队友」result
so the model learns the note went nowhere rather than assuming teammates saw it. The wall +
the live ``team_note_posted`` SSE emit live behind ``ToolContext`` (引擎纯化); this tool owns
only validation + the post→ack mapping.
"""

from __future__ import annotations

import contextlib
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.runs.constants import POST_NOTE_TOOL_NAME
from agentcore.runtime.runs.notewall import (
    NOTE_KIND_CLAIM,
    NOTE_KIND_DECISION,
    NOTE_KIND_HEADS_UP,
    SYSTEM_AGENT_ID,
    SYSTEM_ROLE,
    SYSTEM_RUN_ID,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)


class PostNoteTool:
    """The worker's「贴便签」primitive: broadcast a one-line decision / heads-up, keep working.

    Stateless: the call records onto the batch ``NoteWall`` (via ``ToolContext``) and returns
    a CONTINUE acknowledgement. It never blocks and never ends the turn — posting a note is a
    side effect, not a question (the question primitive is ``escalate``).
    """

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=POST_NOTE_TOOL_NAME,
            description=(
                "把一条【给并行队友看的】短便签贴到团队便签墙。仅当这条会让某个【还在跑的】"
                "队友改变做法时才用——贴完立刻继续做你的活、不等任何回复；不是聊天、不是提问"
                "（要上级拍板请用 escalate）。\n"
                "便签必须【一行、简短具体】（如"
                "『POST /auth/session 收 {email,password} 返 {token}』"
                "『用户表是软删除，查询要带 deleted_at IS NULL』『登录页我来写』），"
                "别写成寒暄或长篇。\n"
                "kind 三类：decision=【我定了】别人要依赖的决定（接口 / 字段名 / 格式 / 命名）；"
                "heads_up=【提个醒】你踩到的坑 / 发现；claim=【我领了】【开工前占坑】——你正要"
                "动手的一块活 / 文件（避免和队友撞活 / 重复）。完工信息走 handoff，【不要】贴"
                "完工宣告。队友新便签每轮自动推给你；read_notes 只用于找推送里没有的旧约定。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            NOTE_KIND_DECISION,
                            NOTE_KIND_HEADS_UP,
                            NOTE_KIND_CLAIM,
                        ],
                        "description": (
                            "decision=我定了（别人要依赖的决定：接口 / 字段名 / 格式 / 命名）；"
                            "heads_up=提个醒（我踩到的坑 / 发现）；"
                            "claim=我领了（开工前占坑：认领一块正要动手的活 / 文件；"
                            "完工不贴，走 handoff）。"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "便签正文，一行、简短、具体、自包含——队友会直接据此对齐，别依赖"
                            "只有你才懂的局部上下文。过长会被截断。"
                        ),
                    },
                },
                "required": ["kind", "text"],
            },
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        wall = context.note_wall
        if wall is None:
            # Solo worker / CEO / tests: no concurrent siblings, so a note has no audience.
            # Tell the model plainly rather than letting it假装队友看到了.
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "便签墙仅在你有并行队友时可用：当前没有同时干活的队友，便签无人可看。"
                    "直接把这条信息写进你的产出 / 交接简报即可。"
                ),
            )
        text = str(arguments.get("text") or "").strip()
        if not text:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="post_note 需要非空的 text（写清要广播给队友的一行信息）。",
            )
        kind = str(arguments.get("kind") or NOTE_KIND_HEADS_UP).strip().lower()
        if kind not in (NOTE_KIND_DECISION, NOTE_KIND_HEADS_UP, NOTE_KIND_CLAIM):
            kind = NOTE_KIND_HEADS_UP
        note = wall.post(
            run_id=context.run_id,
            agent_id=context.agent_id,
            role=context.agent_role,
            kind=kind,
            text=text,
        )
        if note is None:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="post_note 的 text 清理后为空（请写一行有内容的便签）。",
            )
        logger.info("worker.post_note", run_id=context.run_id, kind=kind, chars=len(note.text))
        # Surface it live (best-effort; the durable record rides the journaled event the
        # executor emits via on_note). Never let a liveliness hiccup break the worker.
        if context.on_note is not None:
            try:
                context.on_note(note)
            except Exception:  # noqa: BLE001 — liveliness only; never break the worker
                logger.warning("worker.post_note.emit_failed", run_id=context.run_id)
        conflict_desc = wall.detect_conflict(note)
        if conflict_desc:
            system_note = wall.post(
                run_id=SYSTEM_RUN_ID,
                agent_id=SYSTEM_AGENT_ID,
                role=SYSTEM_ROLE,
                kind=NOTE_KIND_HEADS_UP,
                text=conflict_desc,
            )
            if system_note is not None and context.on_note is not None:
                with contextlib.suppress(Exception):
                    context.on_note(system_note)
            logger.info(
                "worker.post_note.conflict_detected",
                run_id=context.run_id,
                conflicting_note=note.seq,
            )
        # CEO 协调模式 Phase 3: surface notes (+ conflicts as escalation) to the CEO queue.
        try:
            from agentcore.runtime.coordination.bridge import post_note_to_coordination

            post_note_to_coordination(
                run_id=context.run_id,
                role=context.agent_role or "",
                kind=kind,
                text=note.text,
                conflict=conflict_desc,
                execution_id=context.execution_id,
            )
        except Exception:  # noqa: BLE001 — liveliness only
            logger.warning("worker.post_note.coordination_route_failed", run_id=context.run_id)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=(
                f"已贴到团队便签墙〔编号 N{note.seq}〕，并行队友在各自下一步会看到。"
                f"若这条决定之后变了 / 不作数了，可用 amend_note ref=N{note.seq} 改写或作废它。"
                "继续做你的任务即可，不必等待任何回复。"
            ),
        )

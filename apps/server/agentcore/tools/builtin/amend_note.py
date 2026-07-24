"""amend_note — a worker's「改写 / 作废便签」channel: correct a stale note it posted.

Worker-only, the third of the team-note trio (post_note = 贴 / read_notes = 翻 / amend_note =
改写·作废). Wired into the delegated worker toolset (``build_worker_registry``) and NOT into
``build_builtin_registry`` — so it never reaches the CEO's own toolset or the read-only
capability catalog as a CEO tool, mirroring ``post_note`` / ``read_notes`` / ``escalate``.

便签会过期 (§2.2「便签会过期」): a decision a worker broadcast can change (the login example:
``password`` → ``pwd``). If the original note just keeps hanging on the wall, a sibling reads
the stale value and builds on the wrong thing — the classic「陈旧传播」failure. This tool lets
the AUTHOR correct it: give new ``text`` to 改写 (the target is superseded, the new decision is
broadcast in its place) or omit ``text`` to 作废 (the target is retracted with no replacement).
Either way a NEW active amendment note is appended, so it rides the normal 推增量 push and
running siblings learn the change mid-wave — not at the CEO.

It references a note by the ``N{seq}`` handle the ``post_note`` ack returned (a worker never sees
its own notes pushed / pulled, so the handle is how it points back at one). A worker may amend
ONLY its OWN active notes (no cross-worker edit wars / chat-slide); a wrong / missing handle gets
a precise error that lists the caller's own amendable notes so it can retry. Off a team (solo
worker / CEO / tests) ``note_wall`` is ``None`` → a clean「无并行队友」result.
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.runs.constants import AMEND_NOTE_TOOL_NAME
from agentcore.runtime.runs.notewall import SUPERSEDE_MODE_VOID
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

# A worker passes the handle the post ack gave it — accept "N3" / "n3" / "3" / "#3".
_REF_DIGITS = re.compile(r"\d+")


class AmendNoteTool:
    """The worker's「改写 / 作废便签」primitive: correct a stale note it posted, keep working.

    Stateless: the call resolves the handle onto the batch ``NoteWall`` (via ``ToolContext``),
    flips the target + appends the amendment, and returns an acknowledgement. It never blocks
    and never ends the turn — amending a note is a side effect, not a question (the question
    primitive is ``escalate``).
    """

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=AMEND_NOTE_TOOL_NAME,
            description=(
                "改写或作废你【之前贴在团队便签墙上的某条便签】——当你早先广播的决定"
                "后来变了 / 不作数了（比如字段从 password 改成 pwd），用它把旧便签更正掉，"
                "免得队友照着过时的便签继续做。\n"
                "ref 填那条便签的编号（贴便签成功时返回的 N 编号，如 N3）：\n"
                "· 想【改写】（决定变了）→ 同时给 text 写新的一行内容，"
                "旧便签标为「已被更新」、新内容会广播给队友；\n"
                "· 想【作废】（这条不作数、且无替代）→ 省略 text，"
                "旧便签标为「已作废」、并广播一条撤回提醒。\n"
                "只能改你自己贴的、还活跃的便签；编号填错会返回你当前可改的便签清单。"
                "它是顺手更正、贴完即继续干活，不等任何回复（不是聊天、不是提问）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": (
                            "要改写 / 作废的便签编号——即你 post_note 成功时返回的 N 编号（如 N3）。"
                            "只能是你自己贴的、还活跃的便签。"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "新的一行内容 = 【改写】（旧便签被它取代）；省略或留空 = 【作废】"
                            "（旧便签作废、无替代）。同 post_note：一行、简短、具体、自包含。"
                        ),
                    },
                },
                "required": ["ref"],
            },
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        wall = context.note_wall
        if wall is None:
            # Solo worker / CEO / tests: no concurrent siblings, so there is no shared wall.
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "便签墙仅在你有并行队友时存在：当前没有同时干活的队友，"
                    "没有可改写 / 作废的团队便签。"
                ),
            )
        raw_ref = str(arguments.get("ref") or "").strip()
        m = _REF_DIGITS.search(raw_ref)
        if not m:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "amend_note 需要 ref（要改写 / 作废的便签编号，"
                    "如 N3——贴便签成功时返回的编号）。"
                ),
            )
        ref_seq = int(m.group())
        text = str(arguments.get("text") or "")
        outcome = wall.amend(
            run_id=context.run_id,
            agent_id=context.agent_id,
            role=context.agent_role,
            ref_seq=ref_seq,
            text=text,
        )
        if outcome.error is not None or outcome.note is None:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=outcome.error or "amend_note 未能改写该便签。",
            )
        note = outcome.note
        voided = note.supersede_mode == SUPERSEDE_MODE_VOID
        logger.info(
            "worker.amend_note",
            run_id=context.run_id,
            ref_seq=ref_seq,
            mode=note.supersede_mode,
        )
        # Surface it live (best-effort) on the same narrow callback post_note uses — the durable
        # record rides the journaled team_note_posted event the executor emits via on_note.
        if context.on_note is not None:
            try:
                context.on_note(note)
            except Exception:  # noqa: BLE001 — liveliness only; never break the worker
                logger.warning("worker.amend_note.emit_failed", run_id=context.run_id)
        ack = (
            f"已作废便签 N{ref_seq}，并广播撤回提醒给并行队友。"
            if voided
            else (
                f"已改写便签 N{ref_seq}（旧的标为「已被更新」），"
                f"新内容〔编号 N{note.seq}〕已广播给并行队友。"
            )
        )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"{ack}继续做你的任务即可，不必等待任何回复。",
        )

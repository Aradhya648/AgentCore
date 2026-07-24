"""read_notes — a worker's「翻便签墙」channel: pull the team's current shared notes.

Worker-only, the on-demand READ dual of ``post_note`` (the fire-and-forget WRITE). Wired
into the delegated worker toolset (``build_worker_registry``) and NOT into
``build_builtin_registry`` — so it never reaches the CEO's own toolset or the read-only
capability catalog as a CEO tool, mirroring ``post_note`` / ``escalate``.

The note wall (团队便签墙, §2.2 通) already PUSHES freshly-posted teammate notes into a
worker before each step (推增量). This tool is the PULL the worker reaches for when it
realizes mid-task that it needs something a sibling may already have decided — 「字段名谁定
了」「甲的接口定义」(§2.4 变·worker 的「拉」, case a: 东西已存在、只是没主动给它). It returns the
WHOLE current wall (every other run's note) so the worker can look it up, instead of guessing
in isolation and only reconciling at the CEO.

It is a pure read: non-blocking, never waits for a teammate (绝不同步等兄弟 → 死锁), and does
NOT touch the push cursor — so an explicit look-up and the automatic 推增量 stream stay
independent. Off a team (solo worker / CEO / tests) ``note_wall`` is ``None`` → a clean
「无并行队友」result; on a team with nothing posted yet → a clean「墙上暂无便签」result, so the
model never assumes a teammate's product when none was broadcast. If what it needs ISN'T on the
wall (东西还不存在), that is a dependency gap — it uses ``escalate kind=dep`` instead (case b).
"""

from __future__ import annotations

from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.runs.constants import READ_NOTES_TOOL_NAME
from agentcore.runtime.runs.notewall import format_wall_snapshot
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)


class ReadNotesTool:
    """The worker's「翻便签墙」primitive: read the team's current shared notes on demand.

    Stateless: the call reads the batch ``NoteWall`` (via ``ToolContext``) and returns the
    rendered snapshot. It never blocks, never waits for a teammate, and never ends the turn —
    looking at the wall is a read, not a question (the question primitive is ``escalate``).
    """

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=READ_NOTES_TOOL_NAME,
            description=(
                "翻看团队便签墙：拉取并行队友【当前已贴的全部便签】（他们广播的决定 / 提醒）。"
                "当你干到一半，需要某个队友已经定下的东西才能继续——比如『接口 / 字段名 / 格式 / "
                "命名是谁定的、定成什么』『某个坑队友提没提过』——又想不起来时，用它主动翻一遍墙，"
                "据此对齐、避免和队友重复或冲突。\n"
                "它只是【读】：不打断你、不等任何回复，看完接着干。队友新贴的便签本来每步开始前也"
                "会自动推给你，这个工具是让你在两次推送之间【主动】再查一次整面墙。\n"
                "若你要的东西【墙上根本没有】（没人产出过 / 计划也没安排），"
                "那是依赖缺口：别硬猜瞎编"
                "一个凑数、真卡在再猜也是错的缺口上就主动改用 escalate kind=dep 写清你卡在缺什么"
                "（强过闷头产出一堆作废的东西），不要空等，"
                "由主管 / lead 在波边界补一个产出它的步骤。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        wall = context.note_wall
        if wall is None:
            # Solo worker / CEO / tests: no concurrent siblings, so there is no shared wall.
            # Tell the model plainly rather than letting it假装翻到了队友的便签.
            return ToolResult(
                tool_call_id="",
                success=True,
                output=(
                    "便签墙仅在你有并行队友时存在：当前没有同时干活的队友，没有可翻看的团队便签。"
                    "按你已有的上下文继续即可。"
                ),
            )
        notes = wall.all_for(context.run_id)
        logger.info("worker.read_notes", run_id=context.run_id, count=len(notes))
        if not notes:
            return ToolResult(
                tool_call_id="",
                success=True,
                output=(
                    "团队便签墙目前还没有队友贴的便签。继续做你的任务；若你卡在缺一个还不存在的"
                    "输入 / 依赖，别硬猜瞎编一个——主动用 escalate kind=dep 上报"
                    "（再猜也是错就别闷头产废），"
                    "别空等队友。"
                ),
            )
        return ToolResult(tool_call_id="", success=True, output=format_wall_snapshot(notes))

"""consult_skill — the CEO pulls a system Skill's full guidance on demand (渐进披露).

CEO-only: wired in ``runtime.pipeline`` next to ``delegate`` / ``ask_user`` and
deliberately NOT in ``build_builtin_registry`` (a delegated worker does not hold
it). The CEO's always-on prompt carries only a one-line「能力目录」of advanced
capabilities (``skills.render_skill_directory``); when it decides to use one
(advanced orchestration / debate / continuation / asking the user) it calls
``consult_skill(name)`` to feed that skill's full HOW guidance back into its
own ReAct loop (``ToolEffect.CONTINUE``), then acts on it.

A wrong / unknown name degrades gracefully (mirrors ``ToolNotFoundError``): the
result is non-fatal and lists the registered skill names so the model can retry —
a model-config / typo problem must never break a turn.

→ 见设计: docs/06-规划/提示词瘦身与系统Skill落地设计.md §4.3
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.skills import SkillRegistry
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_CEO_ONLY,
    CeoWire,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

# A skill body is a few hundred to ~1.5k chars; lift the model-facing truncation
# budget above the 4000 default so a longer guidance is never clipped mid-sentence
# (it would teach a half-mechanism).
_CONSULT_OUTPUT_LIMIT = 8000


@dataclass
class ConsultSkillTool:
    """The CEO's on-demand capability-retrieval tool: name → skill body, fed back."""

    registration = ToolRegistration(
        surface=ToolSurface.CEO_ORCHESTRATION,
        audience=AUDIENCE_CEO_ONLY,
        ceo_wire=CeoWire.ALWAYS,
    )

    registry: SkillRegistry

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="consult_skill",
            description=(
                "按 name 查阅一个系统「能力」的完整使用指引：你的系统提示词里有一张「能力目录」"
                "列出可查阅的 name 与一行说明；决定要用某能力时，用本工具把它的完整指引拉回来"
                "（作为工具结果返回），读完据此执行即可。何时该查阅、以及对话直答无需查阅，"
                "见能力目录开头的说明。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "要查阅的能力名称，取自系统提示词「能力目录」里列出的 name"
                            "（如 team_orchestration_advanced）。"
                        ),
                    },
                },
                "required": ["name"],
            },
            # A CEO orchestration primitive (sits beside delegate / replan in
            # _CEO_ORCHESTRATION_TOOLS), NOT a「技能」-category tool: 技能 are Prompt
            # injection, surfaced in the「AI 提示词」catalog, not as a tool group. Keeping
            # this orchestration also drops the spurious「技能」group from the tools page.
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        name = str(arguments.get("name") or "").strip()
        skill = self.registry.get(name) if name else None
        if skill is None:
            available = "、".join(s.name for s in self.registry.list_all())
            msg = (
                f"没有名为 '{name}' 的能力。" if name else "缺少 name 参数。"
            ) + f" 可查阅的能力：{available}。"
            # Known playbook name mistaken for a skill → point at delegate(playbook=…).
            if name:
                from agentcore.runtime.runs.playbooks import PLAYBOOKS

                if name in PLAYBOOKS:
                    msg += (
                        f" 『{name}』是 playbook 不是 skill，"
                        f"请用 `delegate(playbook=\"{name}\", …)`。"
                    )
            logger.info("consult_skill.miss", name=name)
            return ToolResult(tool_call_id="", success=False, output=msg, error=msg)

        logger.info("consult_skill.hit", name=name)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=skill.body,
            output_limit=_CONSULT_OUTPUT_LIMIT,
            # Render-oriented twin of ``output`` (工具结果富渲染): the catalog name +
            # one-line summary let the desktop label the step「查阅能力：{summary}」and
            # frame the pulled guidance, instead of dumping the raw body as anonymous
            # tool text. The full body still rides ``output`` (the verbatim guidance the
            # user can expand). 形状是数据不是模式 — just what the consult_skill view needs.
            display={"skill_name": skill.name, "summary": skill.summary},
        )

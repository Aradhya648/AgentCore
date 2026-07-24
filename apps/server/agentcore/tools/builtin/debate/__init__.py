"""debate: CEO 发起结构化辩论 / 交叉审查的编排原语（主持人驱动）。

→ 见设计: docs/03-AI核心/辩论编排设计.md
"""

from __future__ import annotations

from agentcore.tools.builtin.debate.schema import DEBATE_OUTPUT_LIMIT
from agentcore.tools.builtin.debate.tool import DebateTool

__all__ = [
    "DEBATE_OUTPUT_LIMIT",
    "DebateTool",
]

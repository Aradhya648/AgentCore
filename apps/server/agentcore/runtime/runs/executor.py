"""Host-side AGENT run executor: run one RunSpec node via the shared ReAct loop.

Thin facade — implementation split across executor_*.py modules.
→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

from agentcore.runtime.runs.executor_agent import build_agent_executor
from agentcore.runtime.runs.executor_captain import (
    build_captain_executor,
    build_captain_resumer,
)
from agentcore.runtime.runs.executor_continue import continue_run
from agentcore.runtime.runs.executor_identities import ESCALATION_CONCURRENCY_CAP, DelegateFactory

__all__ = [
    "DelegateFactory",
    "ESCALATION_CONCURRENCY_CAP",
    "build_agent_executor",
    "build_captain_executor",
    "build_captain_resumer",
    "continue_run",
]

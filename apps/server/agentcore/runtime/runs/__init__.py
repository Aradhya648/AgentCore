"""Run model package (统一 Run 模型).

统一 Run 模型（types / plan / scheduler / wave / concurrency / builder /
executor）是 CEO ``delegate`` 原语的执行地基：``delegate`` 用 ``build_run_plan``
建图、``WaveScheduler`` + ``build_agent_executor`` 分波执行。旧的外部 planner +
``run_multi_agent`` 路径已退役。

→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

from agentcore.runtime.runs.builder import build_added_nodes, build_run_plan
from agentcore.runtime.runs.concurrency import (
    child_budget,
    current_budget,
    reset_budget,
    resolve_max_parallel,
    set_budget,
)
from agentcore.runtime.runs.executor import (
    build_agent_executor,
    build_captain_executor,
    build_captain_resumer,
    continue_run,
)
from agentcore.runtime.runs.plan import RunPlan, RunPlanError
from agentcore.runtime.runs.scheduler import (
    BoundaryOutcome,
    BoundaryReason,
    OnBoundary,
    RunExecutor,
    RunScheduler,
)
from agentcore.runtime.runs.session import RunSession
from agentcore.runtime.runs.types import (
    TERMINAL_PHASES,
    BatchMetrics,
    Deliverable,
    RunContract,
    RunKind,
    RunOrigin,
    RunPhase,
    RunPolicy,
    RunSpec,
    RunState,
)
from agentcore.runtime.runs.wave import WaveScheduler

__all__ = [
    "build_run_plan",
    "build_added_nodes",
    "build_agent_executor",
    "build_captain_executor",
    "build_captain_resumer",
    "continue_run",
    "RunPlan",
    "RunPlanError",
    "RunExecutor",
    "RunScheduler",
    "BoundaryReason",
    "BoundaryOutcome",
    "OnBoundary",
    "RunSession",
    "WaveScheduler",
    "resolve_max_parallel",
    "RunKind",
    "RunPhase",
    "RunOrigin",
    "RunPolicy",
    "Deliverable",
    "RunContract",
    "RunSpec",
    "RunState",
    "BatchMetrics",
    "TERMINAL_PHASES",
    "child_budget",
    "current_budget",
    "set_budget",
    "reset_budget",
]

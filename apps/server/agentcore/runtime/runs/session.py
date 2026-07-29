"""RunSession — a recoverable snapshot of a finished worker run (留人).

The substrate of 定向唤回（乙 热修）: when a worker run completes, its full message
transcript is preserved as a :class:`RunSession` so the SAME author can be recalled
to continue on its own draft (统一「续写」原语) instead of re-delegating a cold new
worker. The :class:`~agentcore.runtime.sessions.SessionStore` holds the live roster;
the executor's ``continue_run`` re-runs a session with an appended instruction.

→ 见设计: docs/03-AI核心/多轮编排与同人续派.md §二（可恢复运行 RunSession + 续写）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentcore.runtime.runs.types import RunSpec

if TYPE_CHECKING:
    from agentcore.llm.provider.protocol import LLMMessage


@dataclass
class RunSession:
    """One worker run kept alive for 定向唤回 / 跑一半改方向热续写.

    ``transcript`` is the worker's message history (system + task + every
    assistant/tool turn + its final answer when complete) — replayable as the
    starting point for a revision. ``spec`` is the source :class:`RunSpec` (carries
    role / model tier / allowed tools / contract), so a continuation runs as the
    same author; tools follow「只增不减」— new task may declare a tools superset
    that merges into the session (never silently shrink). ``recall_count`` is how
    many times this run has been revised (the 改次闸 reads it). ``content`` mirrors
    the latest answer for quick display.

    ``partial`` marks a mid-flight salvage from a redirect cancel (尚未 COMPLETED、
    但有可序列化 transcript)。热路径 ``continue_run`` 吃这份草稿；空 transcript 不
    应建成 partial session（直接冷回落）。
    """

    run_id: str
    spec: RunSpec
    transcript: list[LLMMessage]
    content: str
    recall_count: int = 0
    partial: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

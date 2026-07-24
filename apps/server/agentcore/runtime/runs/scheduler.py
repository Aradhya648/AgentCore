"""RunScheduler — the one scheduler that drives a RunPlan to completion.

A scheduler advances a plan by dependency order — launching each node the moment
its ``depends_on`` are terminal and a concurrency slot is free (continuous, not
wave-synchronous) — runs nodes concurrently through an injected
:class:`RunExecutor`, and accepts nodes appended mid-run (阶段2 captain
``delegate``). Isolating the interface keeps ``runs`` free of any host import — the
executor (*how* a node runs) is the host's concern, not the scheduler's (which only
owns *when*).

→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from enum import Enum
from typing import Protocol, runtime_checkable

from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec, RunState

# Runs one node to terminal and returns its final state. The host injects this:
# it builds the worker's messages and runs the ReAct loop (阶段1), or — 阶段2 —
# spawns a child engine / folds a synthesis. The scheduler stays ignorant of
# *how* a node runs, only *when* (its wave).
#
# The second argument is the terminal states of every node finished so far, keyed
# by ``run_id``; an executor reads its node's ``depends_on`` entries from it to
# inject upstream products (the DAG dep-context). A node with no deps ignores it.
RunExecutor = Callable[[RunSpec, Mapping[str, RunState]], Awaitable[RunState]]


class BoundaryReason(Enum):
    """Why the scheduler yielded a decision boundary to the host (受监督的波循环).

    The scheduler pauses at a *quiescent* point (in-flight work drained) and hands
    control to the host's :data:`OnBoundary` hook; the reason tells the host which
    arm is in play:

    - ``CHECKPOINT``: a ``checkpoint_after`` node COMPLETED and downstream work
      remains — the existing user ``plan_review`` (continue / adjust / stop).
    - ``BIND``: a ``bind_after_deps`` node's deps are all resolved but its spec is
      not yet finalised — the CEO must late-bind it (``replan``) before it can run.
    - ``SCOPE`` (偏离信号 / 自底向上反应臂): a COMPLETED node flagged a 职责/范围 deviation
      (``escalate kind=scope``) while not-yet-run downstream remains — the CEO reads the
      deviation + the node's output and re-steers the un-run tail (``replan``). The
      reactive twin of ``BIND`` (the CEO's *proactive* late-binding): both hand control
      back to the CEO at a wave boundary, neither needs a live user (≠ ``CHECKPOINT``).

    → 见设计: docs/03-AI核心/执行引擎架构设计.md §受监督的波循环
    """

    CHECKPOINT = "checkpoint"
    BIND = "bind"
    SCOPE = "scope"


class BoundaryOutcome(Enum):
    """The host's verdict at a decision boundary (受监督的波循环).

    Generalises the old ``on_checkpoint`` bool (proceed / stop) to a three-way
    verdict so the same seam serves both arms:

    - ``PROCEED``: resolve and keep scheduling — a CHECKPOINT continues to the gated
      downstream; a BIND means the host finalised the node(s) in place
      (``bind_after_deps`` cleared), so the next ready-scan dispatches them.
    - ``YIELD``: soft-pause like ``should_stop`` — drain in-flight, return the partial
      map with the un-run tail LEFT OUT, so a resume re-runs exactly it (the CEO-arm
      hand-back: the CEO acts on the boundary then resumes the same DAG).
    - ``ABORT``: graceful abort — drain, then materialise the un-run tail as SKIPPED
      (the existing plan_review ``stop`` shape).
    """

    PROCEED = "proceed"
    YIELD = "yield"
    ABORT = "abort"


# The scheduler↔host decision-boundary hook (受监督的波循环). Fired at a quiescent
# boundary with the reason, the triggering node(s), and the completed-so-far map;
# returns the :class:`BoundaryOutcome`. Like :data:`RunExecutor` it stays a
# host-injected callable, so the scheduler owns no interaction / LLM concern — the
# host decides how to resolve each boundary (user plan_review or CEO late-binding).
OnBoundary = Callable[
    [BoundaryReason, Sequence[RunSpec], Mapping[str, RunState]],
    Awaitable[BoundaryOutcome],
]


@runtime_checkable
class RunScheduler(Protocol):
    """The system's single scheduler."""

    async def run(self, plan: RunPlan, executor: RunExecutor) -> dict[str, RunState]:
        """Drive ``plan`` to completion; return each node's terminal
        :class:`RunState` keyed by ``run_id``.

        Dispatch order honours ``depends_on`` (a node runs only once its deps are
        terminal); per-node failure handling follows the node's :class:`RunPolicy`
        (``on_failure``), so a failed dependency can fail / skip / retry its
        dependents without the caller branching.
        """
        ...

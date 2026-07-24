"""Tree-wide run concurrency budget.

Bounds the *total* number of concurrently-running child runs across a whole Run
tree, enforcing the configured parallel budget (``settings.engine_max_parallel_delegations``,
fallback ``MAX_PARALLEL_DELEGATIONS``) — the cap a single scheduler's own width does *not*
enforce across nesting.

Why this matters: :class:`WaveScheduler` caps how many nodes *it* runs at once, but
a node's executor can (阶段2) spawn a child engine that itself fans out into a
*nested* scheduler. Without a tree-wide budget those caps multiply — depth 3 ×
fan-out 6 explodes to ``6 + 36 + 216`` concurrent runs, each holding a DB session
and firing its own LLM call. The budget rides an async-context :class:`ContextVar`:
each scheduler divides its budget by the number of nodes it runs concurrently
(:func:`child_budget`) and installs the reduced share on each child run's task
context, so nested fan-outs *divide* rather than *multiply* — with no shared lock
held across recursion, so the classic recursive-semaphore deadlock can't happen.
"""

from __future__ import annotations

import contextvars

from agentcore.runtime.runs.constants import MAX_PARALLEL_DELEGATIONS

# No ``default=`` on the ContextVar: the root budget is resolved LAZILY (see
# :func:`current_budget`) the first time it is read without an explicit :func:`set_budget`,
# so the configured value governs the tree root. A module-level ``default=`` would freeze at
# import time — before settings load — and re-reading settings at module import is forbidden
# for the ``runs`` package (依赖纪律). Once a scheduler seeds / divides the budget via
# :func:`set_budget`, that explicit value wins in-context, exactly as before.
_budget: contextvars.ContextVar[int] = contextvars.ContextVar("run_parallel_budget")


def resolve_max_parallel() -> int:
    """The configured tree-wide + single-scheduler parallel budget.

    Reads ``settings.engine_max_parallel_delegations`` via a lazy import so the ``runs``
    package imports nothing package-external at module load (parity with
    :func:`~agentcore.runtime.runs.worker_budget._settings_default_token_ceiling`); falls back
    to :data:`MAX_PARALLEL_DELEGATIONS` when settings are unavailable (unit stubs) or the
    configured value is non-positive.
    """
    try:
        from agentcore.config import settings

        value = int(settings.engine_max_parallel_delegations)
        if value > 0:
            return value
    except Exception:  # noqa: BLE001 — settings optional in unit stubs
        pass
    return MAX_PARALLEL_DELEGATIONS


def current_budget() -> int:
    """Remaining parallel slots available to the current subtree (always >= 1).

    With no budget explicitly installed on this context (tree root not yet seeded by a
    scheduler), the configured budget is resolved lazily via :func:`resolve_max_parallel`.
    """
    try:
        value = _budget.get()
    except LookupError:
        value = resolve_max_parallel()
    return max(1, value)


def set_budget(value: int) -> contextvars.Token[int]:
    """Set the parallel budget for the current context; returns a reset token.

    Seeds the root budget at a tree entry point (and by tests), and is called inside
    each child run's task to install its reduced share — no reset needed there, the
    task's context copy is discarded when it ends.
    """
    return _budget.set(max(1, value))


def reset_budget(token: contextvars.Token[int]) -> None:
    """Restore a budget previously set via :func:`set_budget`."""
    _budget.reset(token)


def child_budget(width: int) -> int:
    """The per-child budget when this subtree runs ``width`` nodes concurrently.

    Integer-dividing the current budget by the concurrency width keeps the sum of
    the concurrent children's budgets ≤ this subtree's budget, so the product across
    depth can't explode. Always ≥ 1 (a single slot still makes progress).
    """
    return max(1, current_budget() // max(1, width))

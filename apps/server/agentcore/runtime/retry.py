"""Retry-failed contextvar: threads completed-worker states from the entry point to DelegateTool."""

from __future__ import annotations

from contextvars import ContextVar

from agentcore.runtime.runs.types import RunState

# When set (by retry_failed_chat), DelegateTool reads this to seed_completed
# the WaveScheduler — so workers that already succeeded are skipped and only
# failed ones re-run. None on a normal send / regenerate.
retry_seed: ContextVar[dict[str, RunState] | None] = ContextVar("retry_seed", default=None)

# Failed worker run_ids from the previous turn (retry-failed only). DelegateTool
# reads this once alongside ``retry_seed`` to emit audit retry events.
retry_failed_targets: ContextVar[list[dict[str, str | None]] | None] = ContextVar(
    "retry_failed_targets", default=None
)

"""Outer tool liveness deadline — single owner for FILESYSTEM channel timeouts.

``tool_exec`` sets the ContextVar to the engine outer ``wait_for`` budget before
invoking a tool. ``WorkspaceChannel.request`` derives its transport deadline from
that budget (minus a small settle slack) so Local ops never run two independent
60s clocks with no master/slave relationship.

Capacity failures (bytes / extract) must fail via ``contract_failure`` *before*
this wall-clock matters.
"""

from __future__ import annotations

from contextvars import ContextVar

# Seconds remaining on the engine outer tool ceiling for the in-flight call.
# ``None`` = not inside tool_exec / tool manages its own lifecycle (exempt).
_tool_deadline_seconds: ContextVar[float | None] = ContextVar(
    "tool_deadline_seconds", default=None
)

# Inner channel must finish before outer cancels the tool coroutine.
_CHANNEL_SETTLE_SLACK_SECONDS = 1.0


def set_tool_deadline(seconds: float | None):
    """Bind the outer liveness budget for the current tool call; return a reset token."""
    return _tool_deadline_seconds.set(seconds)


def reset_tool_deadline(token) -> None:
    _tool_deadline_seconds.reset(token)


def current_tool_deadline() -> float | None:
    return _tool_deadline_seconds.get()


def derive_channel_timeout(
    *,
    explicit: float | None = None,
    channel_default: float,
) -> float:
    """Channel deadline derived from the outer tool budget when present.

    Precedence:
    1. Per-op ``explicit`` (e.g. execute timeout + slack) — still capped by outer.
    2. Outer tool deadline − settle slack (master).
    3. Channel default (only when no outer deadline is bound).
    """
    outer = current_tool_deadline()
    base = channel_default if explicit is None else explicit
    if outer is None:
        return max(1.0, base)
    # Slave: never outlive the outer liveness owner.
    capped = min(base, max(1.0, outer - _CHANNEL_SETTLE_SLACK_SECONDS))
    return max(1.0, capped)

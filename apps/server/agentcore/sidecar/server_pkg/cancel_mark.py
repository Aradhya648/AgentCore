"""Mark why a sidecar turn task was cancelled (RPC fingerprint for salvage logs).

Solo blocking drives never arm a coordination session, so ``coordination.user_stop_*``
is absent on cancel. Stamping the asyncio.Task lets ``CancelledError`` salvage log
``reason`` even when the only prior signal was ``task.cancel()``.
"""

from __future__ import annotations

from typing import Any

# Set on the turn ``asyncio.Task`` by ``_on_cancel`` before ``task.cancel()``.
CANCEL_REASON_ATTR = "_agentcore_cancel_reason"

# Desktop-known sources (SidecarCancelRequest.reason). Unknown → kept as trimmed str
# or fall back to ``unspecified`` / ``cancelled_without_rpc``.
KNOWN_CANCEL_REASONS = frozenset(
    {
        "user_stop",
        "abort_signal",
        "attach_abort",
        "unspecified",
        "cancelled_without_rpc",
    }
)


def normalize_cancel_reason(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "unspecified"
    if text in KNOWN_CANCEL_REASONS:
        return text
    # Allow short custom tags from newer clients without catalog churn.
    return text[:64]


def cancel_reason_from_task(task: Any | None) -> str:
    """Read RPC stamp; absent ⇒ cancel did not go through ``_on_cancel``."""
    if task is None:
        return "cancelled_without_rpc"
    stamped = getattr(task, CANCEL_REASON_ATTR, None)
    if stamped is None:
        return "cancelled_without_rpc"
    return normalize_cancel_reason(stamped)

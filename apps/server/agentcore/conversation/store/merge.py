"""D7 merge rules — re-export from the leaf ``agentcore.core.message_merge``.

Canonical home is ``core.message_merge`` so ``db`` can apply the same rules without
importing ``conversation``. Callers may keep importing from this path.
"""

from __future__ import annotations

from agentcore.core.message_merge import (
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INCOMPLETE,
    MESSAGE_STATUS_RUNNING,
    is_terminal_status,
    merge_usage_status,
    pick_longest,
    pick_merged_content,
    pick_monotonic_content,
    should_advance_status,
    should_apply_checkpoint_content,
    status_rank,
    visible_failed_assistant_content,
)

__all__ = [
    "MESSAGE_STATUS_COMPLETE",
    "MESSAGE_STATUS_FAILED",
    "MESSAGE_STATUS_INCOMPLETE",
    "MESSAGE_STATUS_RUNNING",
    "is_terminal_status",
    "merge_usage_status",
    "pick_longest",
    "pick_merged_content",
    "pick_monotonic_content",
    "should_advance_status",
    "should_apply_checkpoint_content",
    "status_rank",
    "visible_failed_assistant_content",
]

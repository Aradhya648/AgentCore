"""ConversationStore implementations (turn-authority persistence driver).

``CloudStore`` is lazy-exported: eager import pulls memory consolidation → messaging
→ Pillow, which is outside the sidecar runtime subset. Sidecar only needs
``OutboxStore`` (+ merge constants) at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.conversation.store.merge import (
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INCOMPLETE,
    MESSAGE_STATUS_RUNNING,
)
from agentcore.conversation.store.outbox import OutboxStore

if TYPE_CHECKING:
    from agentcore.runtime.ports import ConversationStore

__all__ = [
    "MESSAGE_STATUS_COMPLETE",
    "MESSAGE_STATUS_FAILED",
    "MESSAGE_STATUS_INCOMPLETE",
    "MESSAGE_STATUS_RUNNING",
    "CloudStore",
    "OutboxStore",
    "get_cloud_store",
    "get_conversation_store",
    "set_conversation_store",
    "reset_conversation_store_for_tests",
]

# Process-wide active ConversationStore. Cloud host defaults to CloudStore; the
# sidecar swaps in OutboxStore on initialize (as-built: 双模式工作区 §10.3; 执行引擎 §8.6).
_active_store: ConversationStore | None = None

_CLOUD_EXPORTS = frozenset({"CloudStore", "get_cloud_store"})


def __getattr__(name: str) -> Any:
    if name in _CLOUD_EXPORTS:
        from agentcore.conversation.store import cloud as _cloud

        return getattr(_cloud, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_conversation_store() -> ConversationStore:
    """Return the process-wide ConversationStore (CloudStore unless sidecar swapped)."""
    global _active_store
    if _active_store is None:
        from agentcore.conversation.store.cloud import get_cloud_store

        _active_store = get_cloud_store()
    return _active_store


def set_conversation_store(store: ConversationStore) -> None:
    """Install the active ConversationStore (sidecar → OutboxStore)."""
    global _active_store
    _active_store = store


def reset_conversation_store_for_tests() -> None:
    """Drop the override so the next get returns a fresh CloudStore default."""
    global _active_store
    _active_store = None

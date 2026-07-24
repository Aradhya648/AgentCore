"""Unit tests for the per-leaf memory route helpers (Agent记忆与知识系统 §1.6).

The full HTTP round-trip (CAS / clear / scope) is exercised by the PG-gated
``tests/integration/test_memory_api.py``; here we pin the pure ``kind × folder_id →
(file, scope)`` routing that decides which file and which layer a leaf addresses — the
load-bearing invariant being that 偏好 is GLOBAL-only no matter what folder is passed.
"""

from agentcore.api.routes.memory import MemoryKind, _resolve_file_scope
from agentcore.memory.store import CORE_MEMORY_FILE, PREFERENCES_MEMORY_FILE


def test_resolve_preferences_is_global_even_with_folder():
    # 偏好 is universal → always 偏好.md, scope forced to None regardless of folder_id.
    assert _resolve_file_scope(MemoryKind.preferences, None) == (PREFERENCES_MEMORY_FILE, None)
    assert _resolve_file_scope(MemoryKind.preferences, "F1") == (PREFERENCES_MEMORY_FILE, None)


def test_resolve_profile_global_when_no_folder():
    assert _resolve_file_scope(MemoryKind.profile, None) == (CORE_MEMORY_FILE, None)


def test_resolve_profile_honors_folder_scope():
    assert _resolve_file_scope(MemoryKind.profile, "F1") == (CORE_MEMORY_FILE, "F1")

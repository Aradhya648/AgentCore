"""Tests for memory watermark backfill (memory/backfill.py)."""

from agentcore.memory.backfill import is_user_memory_empty
from agentcore.memory.store import CORE_MEMORY_FILE, PREFERENCES_MEMORY_FILE, FileMemoryStore


async def test_is_user_memory_empty_when_both_core_files_missing(tmp_path):
    store = FileMemoryStore(tmp_path)
    assert await is_user_memory_empty(store, "u1") is True


async def test_is_user_memory_empty_false_when_preferences_have_content(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", PREFERENCES_MEMORY_FILE, "## 沟通偏好\n- 中文\n")
    assert await is_user_memory_empty(store, "u1") is False


async def test_is_user_memory_empty_false_when_profile_has_content(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 技术栈\n- Python\n")
    assert await is_user_memory_empty(store, "u1") is False


async def test_is_user_memory_empty_false_when_topic_exists(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", "主题/部署.md", "# deploy\n")
    assert await is_user_memory_empty(store, "u1") is False


async def test_is_user_memory_empty_false_when_project_scope_exists(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "project fact", scope="folder-1")
    assert await is_user_memory_empty(store, "u1") is False

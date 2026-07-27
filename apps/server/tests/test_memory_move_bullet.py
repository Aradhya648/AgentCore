"""Unit tests for memory bullet layer moves (P2-b 搬层纠错)."""

import pytest

from agentcore.memory.move_bullet import (
    MoveBulletConflict,
    MoveBulletError,
    MoveBulletOk,
    move_memory_bullet,
    validate_move,
)
from agentcore.memory.store import CORE_MEMORY_FILE, FileMemoryStore, memory_version

_FOLDER = "11111111-1111-1111-1111-111111111111"
_UID = "u1"


def test_validate_rejects_corrections_to_project():
    err = validate_move(
        file=CORE_MEMORY_FILE, section="纠正记录", direction="to_project"
    )
    assert err is not None
    assert "纠正记录" in err.message


def test_validate_rejects_project_constraints_to_global():
    err = validate_move(
        file=CORE_MEMORY_FILE, section="项目约束", direction="to_global"
    )
    assert err is not None
    assert "项目约束" in err.message


@pytest.mark.asyncio
async def test_move_global_fact_to_project(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(
        _UID,
        CORE_MEMORY_FILE,
        "## 关于用户的事实\n- 本仓库用 React\n- 全局共享事实\n",
    )
    result = await move_memory_bullet(
        store,
        user_id=_UID,
        content="本仓库用 React",
        section="关于用户的事实",
        folder_id=_FOLDER,
        direction="to_project",
    )
    assert isinstance(result, MoveBulletOk)
    global_md = await store.load(_UID, CORE_MEMORY_FILE)
    project_md = await store.load(_UID, CORE_MEMORY_FILE, scope=_FOLDER)
    assert "本仓库用 React" not in global_md
    assert "全局共享事实" in global_md
    assert "本仓库用 React" in project_md


@pytest.mark.asyncio
async def test_move_project_fact_to_global(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(
        _UID,
        CORE_MEMORY_FILE,
        "## 技术栈与工具\n- 仅本项目用 Vite\n",
        scope=_FOLDER,
    )
    result = await move_memory_bullet(
        store,
        user_id=_UID,
        content="仅本项目用 Vite",
        section="技术栈与工具",
        folder_id=_FOLDER,
        direction="to_global",
    )
    assert isinstance(result, MoveBulletOk)
    assert "仅本项目用 Vite" in await store.load(_UID, CORE_MEMORY_FILE)
    assert (
        await store.load(_UID, CORE_MEMORY_FILE, scope=_FOLDER)
    ).strip() == "" or "仅本项目用 Vite" not in await store.load(
        _UID, CORE_MEMORY_FILE, scope=_FOLDER
    )


@pytest.mark.asyncio
async def test_move_rejects_corrections_via_api_path(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(
        _UID, CORE_MEMORY_FILE, "## 纠正记录\n- 不是 npm，是 pnpm\n"
    )
    result = await move_memory_bullet(
        store,
        user_id=_UID,
        content="不是 npm，是 pnpm",
        section="纠正记录",
        folder_id=_FOLDER,
        direction="to_project",
    )
    assert isinstance(result, MoveBulletError)
    assert "纠正记录" in result.message


@pytest.mark.asyncio
async def test_move_rejects_missing_bullet(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save(
        _UID, CORE_MEMORY_FILE, "## 关于用户的事实\n- 仍在\n"
    )
    result = await move_memory_bullet(
        store,
        user_id=_UID,
        content="早就没了",
        section="关于用户的事实",
        folder_id=_FOLDER,
        direction="to_project",
    )
    assert isinstance(result, MoveBulletError)
    assert "找不到" in result.message


@pytest.mark.asyncio
async def test_move_cas_conflict(tmp_path):
    store = FileMemoryStore(tmp_path)
    body = "## 关于用户的事实\n- 待搬\n"
    await store.save(_UID, CORE_MEMORY_FILE, body)
    result = await move_memory_bullet(
        store,
        user_id=_UID,
        content="待搬",
        section="关于用户的事实",
        folder_id=_FOLDER,
        direction="to_project",
        source_baseline="stale-tag",
    )
    assert isinstance(result, MoveBulletConflict)
    assert result.source_version == memory_version(body)

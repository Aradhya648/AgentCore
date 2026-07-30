"""R1 explore refresh — scheduler + fake-LLM runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import pytest

from agentcore.memory.episodic import load_scope_meta
from agentcore.memory.explore_profile import record_explore_closeout
from agentcore.memory.explore_refresh import (
    ExploreRefreshScheduler,
    _PendingRefresh,
    refresh_project_explore_from_snapshot,
    schedule_explore_refresh,
)
from agentcore.memory.store import CORE_MEMORY_FILE, NAVIGATION_MEMORY_FILE, FileMemoryStore
from agentcore.workspace.stage_dirs import PROJECT_DOCS_DIR, PROJECT_DOCS_PREFIX


@dataclass
class _FakeResponse:
    content: str
    usage: object = None
    model: str = "fake"


class _FakeProvider:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        self.calls += 1
        return _FakeResponse(content=self._content)

    async def close(self) -> None:
        return None


class _RefreshRecorder:
    def __init__(self) -> None:
        self.calls: list[_PendingRefresh] = []
        self.pulsed = asyncio.Event()

    async def __call__(self, pending: _PendingRefresh) -> None:
        self.calls.append(pending)
        self.pulsed.set()


@pytest.mark.asyncio
async def test_explore_refresh_scheduler_debounces_per_folder():
    runner = _RefreshRecorder()
    sched = ExploreRefreshScheduler(idle_seconds=0.08, runner=runner)
    pending = _PendingRefresh(
        user_id="u1",
        folder_id="f1",
        workspace_key="folder:f1",
        snapshot="# Top-level\n- [dir] src",
        live_fingerprint="fp1",
    )
    for _ in range(3):
        sched.schedule(pending)
        await asyncio.sleep(0.01)
    assert runner.calls == []
    await asyncio.wait_for(runner.pulsed.wait(), 1)
    await asyncio.sleep(0.05)
    assert len(runner.calls) == 1
    assert runner.calls[0].folder_id == "f1"


@pytest.mark.asyncio
async def test_schedule_explore_refresh_noop_when_disabled(monkeypatch):
    from agentcore.memory import explore_refresh as mod

    monkeypatch.setattr(mod.settings, "memory_explore_refresh_enabled", False)
    # Must not raise even without a running scheduler payload.
    schedule_explore_refresh(
        user_id="u",
        folder_id="f",
        workspace_key="k",
        snapshot="x",
        live_fingerprint="fp",
    )


@pytest.mark.asyncio
async def test_refresh_from_snapshot_writes_nav_profile_and_clears_dirty(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    await store.save(uid, CORE_MEMORY_FILE, "## 技术栈与工具\n- OldStack\n", scope=folder)
    await record_explore_closeout(
        store,
        uid,
        folder,
        workspace_key=f"folder:{folder}",
        fingerprint="fp-old",
    )
    from agentcore.memory.episodic import load_scope_meta, save_scope_meta

    async def _mark_dirty() -> None:
        meta = await load_scope_meta(store, uid, scope=folder)
        meta.explore_fingerprint_dirty = True
        await save_scope_meta(store, uid, meta, scope=folder)

    await _mark_dirty()
    meta = await load_scope_meta(store, uid, scope=folder)
    assert meta.explore_fingerprint_dirty is True

    provider = _FakeProvider(
        content=(
            '{"profile":"## 技术栈与工具\\n- NewStack\\n",'
            '"navigation":"# 导航\\n一句话：测试仓\\n\\n| 我要… | 先读 |\\n|---|---|\\n| 改后端 | apps/server |\\n",'
            '"topics":[]}'
        )
    )
    ok = await refresh_project_explore_from_snapshot(
        user_id=uid,
        folder_id=folder,
        workspace_key=f"folder:{folder}",
        snapshot="# Top-level\n- [dir] apps\n\n# Key manifests\n## README.md\nhello\n",
        live_fingerprint="fp-new",
        provider=provider,  # type: ignore[arg-type]
        model="fake",
        store=store,
    )
    assert ok is True
    assert provider.calls == 1
    profile = await store.load(uid, CORE_MEMORY_FILE, scope=folder)
    assert "NewStack" in profile
    nav = await store.load(uid, NAVIGATION_MEMORY_FILE, scope=folder)
    assert "测试仓" in nav
    meta = await load_scope_meta(store, uid, scope=folder)
    assert meta.explore_fingerprint == "fp-new"
    assert meta.explore_fingerprint_dirty is False


@pytest.mark.asyncio
async def test_refresh_parse_failure_leaves_dirty(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    await store.save(uid, CORE_MEMORY_FILE, "## 技术栈与工具\n- Go\n", scope=folder)
    await record_explore_closeout(
        store, uid, folder, workspace_key=f"folder:{folder}", fingerprint="fp-old"
    )
    from agentcore.memory.episodic import save_scope_meta

    meta = await load_scope_meta(store, uid, scope=folder)
    meta.explore_fingerprint_dirty = True
    await save_scope_meta(store, uid, meta, scope=folder)

    provider = _FakeProvider(content="not-json")
    ok = await refresh_project_explore_from_snapshot(
        user_id=uid,
        folder_id=folder,
        workspace_key=f"folder:{folder}",
        snapshot="# Top-level\n- [file] a",
        live_fingerprint="fp-new",
        provider=provider,  # type: ignore[arg-type]
        model="fake",
        store=store,
    )
    assert ok is False
    meta = await load_scope_meta(store, uid, scope=folder)
    assert meta.explore_fingerprint_dirty is True
    assert meta.explore_fingerprint == "fp-old"


def test_project_docs_stage_constant():
    assert PROJECT_DOCS_DIR == "AgentCore/文档/项目"
    assert PROJECT_DOCS_PREFIX == "AgentCore/文档/项目/"

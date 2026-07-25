"""Cold-start explore act — profile probe, section merge, write tool, prompt gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from agentcore.memory.explore_profile import (
    build_workspace_key,
    load_explore_workspace_key,
    merge_profile_by_sections,
    normalize_explore_topic_slug,
    parse_explore_topics,
    profile_has_substance,
    project_profile_explore_reason,
    project_profile_is_empty,
    project_profile_needs_explore,
    record_explore_workspace_key,
    write_project_profile_cas,
    write_project_topics_replace,
)
from agentcore.memory.store import CORE_MEMORY_FILE, FileMemoryStore
from agentcore.runtime.resolve.prompt import compose_ceo_chat_prompt
from agentcore.runtime.skills import build_system_skill_registry
from agentcore.tools.builtin.remember import RememberTool
from agentcore.tools.builtin.update_project_profile import UpdateProjectProfileTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


@dataclass
class _PromptHolder:
    _system_prompt: str = "base prompt"


def _ctx(*, user_id: str | None = None) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id=user_id or str(uuid4()),
        conversation_id=str(uuid4()),
    )


# --- 够用探针 -----------------------------------------------------------------


def test_profile_substance_probe_empty_and_chrome_only():
    assert project_profile_is_empty("")
    assert project_profile_is_empty("   \n")
    assert project_profile_is_empty(
        "# 用户记忆\n> 本文件由 AI 自动维护，你可随时编辑或删除任何条目。\n"
    )
    assert project_profile_is_empty("## 技术栈与工具\n\n## 项目约束\n")
    assert not profile_has_substance("## 技术栈与工具\n")


def test_profile_substance_probe_with_bullets():
    md = "## 技术栈与工具\n- Python monorepo\n"
    assert profile_has_substance(md)
    assert not project_profile_is_empty(md)


@pytest.mark.asyncio
async def test_project_profile_needs_explore_gate(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())

    assert await project_profile_needs_explore(store, uid, None) is False
    assert await project_profile_needs_explore(store, uid, folder) is True
    assert await project_profile_explore_reason(store, uid, folder) == "empty"

    await store.save(uid, CORE_MEMORY_FILE, "## 技术栈与工具\n- Go\n", scope=folder)
    # Non-empty without stored key → no hard rebind (legacy).
    assert await project_profile_needs_explore(store, uid, folder) is False
    assert await project_profile_explore_reason(store, uid, folder) is None


@pytest.mark.asyncio
async def test_explore_reason_rebind_when_workspace_key_mismatches(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    await store.save(uid, CORE_MEMORY_FILE, "## 技术栈与工具\n- Go\n", scope=folder)
    await record_explore_workspace_key(store, uid, folder, "local:root-a:")
    assert (
        await project_profile_explore_reason(
            store, uid, folder, current_workspace_key="local:root-a:"
        )
        is None
    )
    assert (
        await project_profile_explore_reason(
            store, uid, folder, current_workspace_key="local:root-b:"
        )
        == "rebind"
    )
    assert await project_profile_needs_explore(
        store, uid, folder, current_workspace_key="local:root-b:"
    )


def test_build_workspace_key_local_and_cloud():
    @dataclass
    class _B:
        root_id: str
        subpath: str = ""

    assert build_workspace_key(folder_id="f1", binding=_B("rid", "sub")) == "local:rid:sub"
    assert build_workspace_key(folder_id="f1", binding=None) == "folder:f1"

# --- 合并语义 -----------------------------------------------------------------


def test_merge_profile_bootstrap_when_empty():
    new = "## 技术栈与工具\n- Python\n\n## 项目约束\n- 禁止 jQuery\n"
    merged = merge_profile_by_sections("", new)
    assert "Python" in merged
    assert "禁止 jQuery" in merged
    assert merged.startswith("#")


def test_merge_profile_keeps_unmentioned_sections():
    old = (
        "## 技术栈与工具\n- Python\n\n"
        "## 关于用户的事实\n- 这是支付结算 monorepo\n\n"
        "## 项目约束\n- 必须 PostgreSQL\n"
    )
    new = "## 技术栈与工具\n- Python + FastAPI\n- pnpm workspace\n"
    merged = merge_profile_by_sections(old, new)
    assert "Python + FastAPI" in merged
    assert "pnpm workspace" in merged
    assert "支付结算" in merged  # untouched section kept
    assert "必须 PostgreSQL" in merged


def test_merge_profile_rejects_empty_new_as_wipe():
    old = "## 技术栈与工具\n- Keep me\n"
    assert merge_profile_by_sections(old, "") == old
    assert merge_profile_by_sections(old, "   ") == old


# --- CAS 写入 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_project_profile_cas_merge(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    await store.save(
        uid,
        CORE_MEMORY_FILE,
        "## 技术栈与工具\n- Python\n\n## 项目约束\n- 保留约束\n",
        scope=folder,
    )
    ok, resulting, conflict = await write_project_profile_cas(
        store=store,
        user_id=uid,
        folder_id=folder,
        new_markdown="## 技术栈与工具\n- Python 3.12\n",
    )
    assert ok and not conflict
    assert "Python 3.12" in resulting
    assert "保留约束" in resulting
    loaded = await store.load(uid, CORE_MEMORY_FILE, scope=folder)
    assert loaded == resulting


@pytest.mark.asyncio
async def test_write_project_profile_cas_rejects_empty_content(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    ok, resulting, conflict = await write_project_profile_cas(
        store=store,
        user_id=uid,
        folder_id=folder,
        new_markdown="## 技术栈与工具\n\n",
    )
    assert not ok and not conflict and resulting == ""


# --- 工具：裸聊 / remember 不碰画像 ---------------------------------


@pytest.mark.asyncio
async def test_update_project_profile_refuses_bare_chat(tmp_path):
    tool = UpdateProjectProfileTool(folder_id=None, store=FileMemoryStore(tmp_path))
    res = await tool.execute(
        {"content": "## 技术栈与工具\n- X\n"},
        _ctx(),
    )
    assert not res.success
    assert res.error == "no_project"


@pytest.mark.asyncio
async def test_update_project_profile_writes_and_hot_refreshes(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    holder = _PromptHolder(_system_prompt="worker base\n<rules>\nold\n</rules>")
    tool = UpdateProjectProfileTool(
        folder_id=folder,
        store=store,
        prompt_holders=[holder],
        workspace_key=f"folder:{folder}",
    )
    res = await tool.execute(
        {"content": "## 技术栈与工具\n- TypeScript\n"},
        _ctx(user_id=uid),
    )
    assert res.success
    assert res.display["kind"] == "project_profile"
    assert "TypeScript" in res.output
    assert "<project_profile_updated>" in holder._system_prompt
    assert "TypeScript" in holder._system_prompt
    loaded = await store.load(uid, CORE_MEMORY_FILE, scope=folder)
    assert "TypeScript" in loaded
    assert await load_explore_workspace_key(store, uid, folder) == f"folder:{folder}"


@pytest.mark.asyncio
async def test_remember_does_not_touch_project_profile(tmp_path, monkeypatch):
    """remember → user rule only; project 画像.md stays untouched."""
    from agentcore.tools.builtin import remember as remember_mod

    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):  # noqa: ANN002
            return None

    def _fake_factory():
        return _FakeSession()

    async def _fake_append(repo, user_id, *, folder_id, content):  # noqa: ANN001
        return True

    monkeypatch.setattr(remember_mod, "async_session_factory", _fake_factory)
    monkeypatch.setattr(remember_mod, "append_user_rule", _fake_append)
    monkeypatch.setattr(remember_mod, "DocumentRepository", lambda session: object())

    tool = RememberTool(folder_id=folder)
    res = await tool.execute({"content": "以后都用中文回复"}, _ctx(user_id=uid))
    assert res.success
    assert res.display["kind"] == "user_rule"
    assert await store.load(uid, CORE_MEMORY_FILE, scope=folder) == ""
    assert "项目画像" in tool.schema.description
    assert "update_project_profile" in tool.schema.description


# --- 提示词闸：画像空注入 / 闲聊纪律文案 -----------------------------------------


def test_compose_prompt_cold_start_block_only_when_flagged():
    skills = build_system_skill_registry()
    names = {"consult_memory", "update_project_profile", "delegate"}
    without = compose_ceo_chat_prompt(
        "BASE",
        skill_registry=skills,
        ceo_tool_names=names,
        cold_start_explore=False,
    )
    with_flag = compose_ceo_chat_prompt(
        "BASE",
        skill_registry=skills,
        ceo_tool_names=names,
        cold_start_explore=True,
    )
    assert "当前项目约定记忆「画像.md」为空" not in without
    assert "当前项目约定记忆「画像.md」为空" in with_flag
    assert "<cold_start_explore>" in with_flag
    assert "闲聊" in with_flag or "问候" in with_flag
    assert "假画像" in with_flag
    assert "update_project_profile" in with_flag
    assert "remember" in with_flag
    assert "需要我继续吗" in with_flag
    assert "topics" in with_flag
    assert "重新了解" in with_flag


def test_compose_prompt_rebind_gate():
    skills = build_system_skill_registry()
    text = compose_ceo_chat_prompt(
        "BASE",
        skill_registry=skills,
        ceo_tool_names={"update_project_profile", "delegate"},
        cold_start_explore="rebind",
    )
    assert "绑定已变" in text
    assert "合并更新" in text
    assert "<cold_start_explore>" in text
    assert "画像.md」为空" not in text

def test_compose_prompt_without_profile_tool_skips_write_hint():
    skills = build_system_skill_registry()
    text = compose_ceo_chat_prompt(
        "BASE",
        skill_registry=skills,
        ceo_tool_names={"delegate"},
        cold_start_explore=False,
    )
    assert "【项目画像写入】" not in text


def test_compose_prompt_profile_tool_hint_covers_continue_and_topics():
    skills = build_system_skill_registry()
    text = compose_ceo_chat_prompt(
        "BASE",
        skill_registry=skills,
        ceo_tool_names={"update_project_profile", "delegate"},
        cold_start_explore=False,
    )
    assert "【项目画像写入】" in text
    assert "topics" in text
    assert "立刻继续" in text


# --- P1：主题拆分 -----------------------------------------------------------------


def test_normalize_and_parse_explore_topics():
    assert normalize_explore_topic_slug("Desktop") == "desktop"
    assert normalize_explore_topic_slug("../etc") is None
    assert normalize_explore_topic_slug("有中文") is None
    topics, warnings = parse_explore_topics(
        [
            {"slug": "runtime", "content": "## 入口\n- FastAPI\n"},
            {"slug": "desktop", "content": "## 入口\n- Electron\n"},
            {"slug": "admin", "content": "x"},
            {"slug": "extra", "content": "should warn"},
        ]
    )
    assert [s for s, _ in topics] == ["runtime", "desktop", "admin"]
    assert any("超过" in w for w in warnings)


@pytest.mark.asyncio
async def test_update_project_profile_writes_topics(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    tool = UpdateProjectProfileTool(
        folder_id=folder, store=store, workspace_key=f"folder:{folder}"
    )
    res = await tool.execute(
        {
            "content": "## 技术栈与工具\n- Monorepo\n",
            "topics": [
                {"slug": "runtime", "content": "## 结构\n- apps/server\n"},
                {"slug": "desktop", "content": "## 结构\n- apps/desktop\n"},
            ],
        },
        _ctx(user_id=uid),
    )
    assert res.success
    assert res.display["topics"] == ["主题/runtime.md", "主题/desktop.md"]
    assert "立刻继续" in res.output
    assert "需要我继续吗" in res.output
    assert "Monorepo" in await store.load(uid, CORE_MEMORY_FILE, scope=folder)
    assert "apps/server" in await store.load(uid, "主题/runtime.md", scope=folder)
    assert "apps/desktop" in await store.load(uid, "主题/desktop.md", scope=folder)


@pytest.mark.asyncio
async def test_update_project_profile_clears_explore_pending(tmp_path):
    """画像写入成功须翻转 ToolContext.cold_start_explore_pending，避免误伤同回合交付批。"""
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    tool = UpdateProjectProfileTool(
        folder_id=folder, store=store, workspace_key=f"folder:{folder}"
    )
    context = _ctx(user_id=uid)
    context.cold_start_explore_pending = True
    res = await tool.execute(
        {"content": "## 技术栈与工具\n- Python\n"},
        context,
    )
    assert res.success
    assert context.cold_start_explore_pending is False


@pytest.mark.asyncio
async def test_write_project_topics_replace_overwrites(tmp_path):
    store = FileMemoryStore(tmp_path)
    uid = str(uuid4())
    folder = str(uuid4())
    await write_project_topics_replace(
        store=store,
        user_id=uid,
        folder_id=folder,
        topics=[("runtime", "old")],
    )
    await write_project_topics_replace(
        store=store,
        user_id=uid,
        folder_id=folder,
        topics=[("runtime", "new body")],
    )
    assert (await store.load(uid, "主题/runtime.md", scope=folder)).strip() == "new body"

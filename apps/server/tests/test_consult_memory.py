"""Tests for consult_memory — the CEO's on-demand recall of a 记忆主题笔记 (记忆文件夹化 §六).

Covers the read side of memory folderization:

1. ``ConsultMemoryTool`` — returns a topic note's full body (CONTINUE) on a hit; a wrong
   / unknown name is a soft miss (``success=True``, lists available topics, no ``error``);
   only a missing / empty ``name`` is a real parameter failure. Always-injected CORE
   (画像) is NOT reachable as a topic. Name spelling is forgiving (bare slug /
   主题/<slug> path / <slug>.md filename all resolve).
2. ``render_memory_topic_directory`` + ``compose_ceo_chat_prompt`` — the directory lists
   the user's topic names and rides the CEO prompt ONLY when consult_memory is wired
   (memory on AND at least one topic — same live-tool gate as the skill directory).
3. Assembly — ``consult_memory`` is omitted when memory is off OR the topic catalog is
   empty (CEO + worker symmetric); ``remember`` still wires whenever memory is on.
"""

from pathlib import Path

from agentcore.core.types import ToolCategory
from agentcore.memory import MemoryTopic
from agentcore.memory.store import CORE_MEMORY_FILE, FileMemoryStore, topic_path
from agentcore.runtime.resolve.prepare import _wire_worker_memory_tools
from agentcore.runtime.resolve.prompt import (
    assemble_system_prompt,
    compose_ceo_chat_prompt,
    compose_worker_base_prompt,
    render_memory_topic_directory,
    render_worker_memory_topic_directory,
)
from agentcore.runtime.skills import build_system_skill_registry
from agentcore.tools.builtin import build_worker_registry
from agentcore.tools.builtin.consult_memory import ConsultMemoryTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(user_id: str = "u") -> ToolContext:
    # consult_memory never touches the backend; a real one only satisfies the shape.
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id=user_id,
    )


# --- consult_memory tool -----------------------------------------------------


def test_consult_memory_schema_is_ceo_orchestration_primitive(tmp_path):
    tool = ConsultMemoryTool(store=FileMemoryStore(tmp_path))
    schema = tool.schema
    assert schema.name == "consult_memory"
    assert schema.category is ToolCategory.ORCHESTRATION
    assert schema.parameters["type"] == "object"
    assert "name" in schema.parameters["properties"]


async def test_consult_memory_returns_body_on_hit(tmp_path):
    store = FileMemoryStore(tmp_path)
    body = "## 笔记\n- 用 pnpm dev 起前端\n- 服务端用 uv run\n"
    await store.save("u", topic_path("部署流程"), body)
    result = await ConsultMemoryTool(store=store).execute({"name": "部署流程"}, _ctx())
    assert result.success
    assert result.output == body
    assert result.display == {"topic": "部署流程"}


async def test_consult_memory_name_spelling_is_forgiving(tmp_path):
    store = FileMemoryStore(tmp_path)
    body = "## 笔记\n- x\n"
    await store.save("u", topic_path("部署流程"), body)
    tool = ConsultMemoryTool(store=store)
    # A bare slug, the 主题/<slug> path, and a <slug>.md filename all resolve to the note.
    for name in ("部署流程", "主题/部署流程", "部署流程.md", "主题/部署流程.md"):
        result = await tool.execute({"name": name}, _ctx())
        assert result.success, name
        assert result.output == body


async def test_consult_memory_degrades_on_unknown_name(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("部署流程"), "x")
    await store.save("u", topic_path("项目背景"), "y")
    result = await ConsultMemoryTool(store=store).execute({"name": "不存在的主题"}, _ctx())
    # Soft miss: informational output, not a red-error tool failure.
    assert result.success
    assert result.error is None
    assert "部署流程" in result.output
    assert "项目背景" in result.output


async def test_consult_memory_handles_missing_name_arg(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("部署流程"), "x")
    result = await ConsultMemoryTool(store=store).execute({}, _ctx())
    assert not result.success
    assert result.error
    assert "name" in result.output


async def test_consult_memory_reports_when_user_has_no_topics(tmp_path):
    # Tool-level soft miss if somehow invoked with an empty catalog (assembly omits the
    # tool when prepare finds no topics — covered by test_assemble_omits_*_empty_topics).
    store = FileMemoryStore(tmp_path)
    result = await ConsultMemoryTool(store=store).execute({"name": "随便"}, _ctx())
    assert result.success
    assert result.error is None
    assert "没有任何记忆主题" in result.output


async def test_consult_memory_cannot_reach_core_note(tmp_path):
    # The always-injected CORE note (画像) rides every prompt — it is NOT a consultable
    # topic, so asking for it by name misses (topics live under 主题/<slug>.md only).
    store = FileMemoryStore(tmp_path)
    await store.save("u", CORE_MEMORY_FILE, "## 沟通偏好\n- 用中文\n")
    result = await ConsultMemoryTool(store=store).execute({"name": "画像"}, _ctx())
    assert result.success
    assert "画像" in result.output or "没有任何记忆主题" in result.output


async def test_consult_memory_is_per_user(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("alice", topic_path("私密"), "alice note")
    # Bob asking for Alice's topic name misses — the store is addressed by user_id.
    result = await ConsultMemoryTool(store=store).execute({"name": "私密"}, _ctx("bob"))
    assert result.success
    assert result.error is None
    assert "alice note" not in result.output
    assert "没有名为" in result.output


# --- scope-aware recall (project + global, Agent记忆与知识系统 §二) -----------------


async def test_consult_memory_resolves_project_topic(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("部署流程"), "本项目部署笔记", scope="F1")
    tool = ConsultMemoryTool(store=store, folder_id="F1")
    result = await tool.execute({"name": "部署流程"}, _ctx())
    assert result.success
    assert result.output == "本项目部署笔记"


async def test_consult_memory_prefers_project_over_global_same_name(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("部署流程"), "全局部署笔记")
    await store.save("u", topic_path("部署流程"), "本项目部署笔记", scope="F1")
    tool = ConsultMemoryTool(store=store, folder_id="F1")
    result = await tool.execute({"name": "部署流程"}, _ctx())
    assert result.output == "本项目部署笔记"  # project (more specific) wins


async def test_consult_memory_falls_back_to_global_in_project(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("全局主题"), "全局笔记")
    tool = ConsultMemoryTool(store=store, folder_id="F1")  # no such project topic
    result = await tool.execute({"name": "全局主题"}, _ctx())
    assert result.success
    assert result.output == "全局笔记"


async def test_consult_memory_miss_lists_both_scopes(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u", topic_path("全局主题"), "g")
    await store.save("u", topic_path("项目主题"), "p", scope="F1")
    tool = ConsultMemoryTool(store=store, folder_id="F1")
    result = await tool.execute({"name": "不存在"}, _ctx())
    assert result.success
    assert result.error is None
    assert "全局主题" in result.output
    assert "项目主题" in result.output


# --- 记忆主题目录 rendering + prompt gating ------------------------------------


def test_topic_directory_lists_names_and_points_at_consult():
    out = render_memory_topic_directory(
        [MemoryTopic("部署流程", "先 build 再 deploy"), MemoryTopic("项目背景", "")]
    )
    assert "<记忆主题目录>" in out and "</记忆主题目录>" in out
    assert "consult_memory" in out  # the soft push to pull a topic
    assert "- 部署流程：先 build 再 deploy" in out  # name + one-line summary (§1.4)
    assert "- 项目背景" in out and "- 项目背景：" not in out  # no summary ⇒ just the name


def test_topic_directory_empty_when_no_topics():
    # No topic notes ⇒ nothing rendered, so the caller appends no empty block.
    assert render_memory_topic_directory([]) == ""


def test_ceo_prompt_lists_topic_directory_only_when_consult_memory_wired():
    base = assemble_system_prompt()
    registry = build_system_skill_registry()

    # Memory on ⇒ consult_memory wired ⇒ the directory rides the CEO prompt.
    with_memory = compose_ceo_chat_prompt(
        base,
        skill_registry=registry,
        ceo_tool_names={"delegate", "consult_skill", "consult_memory"},
        memory_topics=[MemoryTopic("部署流程", "先 build")],
    )
    assert "<记忆主题目录>" in with_memory
    assert "- 部署流程：先 build" in with_memory

    # Memory off ⇒ consult_memory NOT wired ⇒ the directory is gated out entirely, even
    # if topics were passed (the directory↔tool privacy invariant).
    without_memory = compose_ceo_chat_prompt(
        base,
        skill_registry=registry,
        ceo_tool_names={"delegate", "consult_skill"},
        memory_topics=[MemoryTopic("部署流程", "先 build")],
    )
    assert "<记忆主题目录>" not in without_memory


# --- assembly wiring: folder_id → consult_memory project scope (resume folder_id 缺口) ---


def _assemble_chat_tools(
    *,
    folder_id: str | None,
    memory_enabled: bool = True,
    has_memory_topics: bool = True,
):
    """Run the real CEO toolset assembly and return its chat ToolRegistry.

    The SAME ``_assemble_ceo_toolset`` a fresh turn and a 2b resume call — the resume now
    passes the frame's ``folder_id`` (Agent记忆与知识系统 §二), so this pins that a
    non-None folder_id scopes consult_memory to that project rather than global-only.
    ``has_memory_topics`` mirrors the prepare-phase catalog signal (empty ⇒ omit tool).
    """
    from agentcore.llm.profiles import default_turn_profiles as default_profile_set
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.resolve.prepare import _assemble_ceo_toolset
    from agentcore.tools.registry import ToolRegistry

    _, _, chat_tools = _assemble_ceo_toolset(
        llm=object(),
        sink=EventSink(),
        base_system_prompt="SYS",
        user_message="原始请求",
        history=[],
        worker_tools=ToolRegistry(),
        base_tool_context=_ctx(),
        profiles=default_profile_set(),
        approval_gate=None,
        session_store=None,
        session_saver=None,
        session_loader=None,
        conversation_id="c",
        captain_run_id="cap",
        checkpoint_enabled=False,
        message_id="m",
        suspension_saver=None,
        suspension_deleter=None,
        backend_location="cloud",
        skill_registry=build_system_skill_registry(),
        memory_enabled=memory_enabled,
        folder_id=folder_id,
        has_memory_topics=has_memory_topics,
    )
    return chat_tools


def test_assemble_wires_consult_memory_to_folder_scope():
    cm = _assemble_chat_tools(folder_id="F1").get_optional("consult_memory")
    assert cm is not None
    assert cm.folder_id == "F1"  # resume recalls THIS project's 主题 first


def test_assemble_consult_memory_is_global_without_folder():
    cm = _assemble_chat_tools(folder_id=None).get_optional("consult_memory")
    assert cm is not None
    assert cm.folder_id is None  # 裸聊 / local: global-only, as before


def test_assemble_omits_consult_memory_when_memory_off():
    # Master switch off ⇒ not wired at all (privacy off-ramp); folder_id is irrelevant.
    chat_tools = _assemble_chat_tools(folder_id="F1", memory_enabled=False)
    assert chat_tools.get_optional("consult_memory") is None


def test_assemble_omits_consult_memory_when_topics_empty():
    # Memory on but no TOPIC notes ⇒ no consult_memory (aligns with empty directory).
    chat_tools = _assemble_chat_tools(
        folder_id="F1", memory_enabled=True, has_memory_topics=False
    )
    assert chat_tools.get_optional("consult_memory") is None
    # remember still wires — only the on-demand recall tool is topic-gated.
    assert chat_tools.get_optional("remember") is not None


# --- worker wiring + prompt --------------------------------------------------


def test_worker_topic_directory_lists_names_only():
    out = render_worker_memory_topic_directory(
        [MemoryTopic("部署流程", "先 build 再 deploy"), MemoryTopic("项目背景", "")]
    )
    assert "<记忆主题目录>" in out and "</记忆主题目录>" in out
    assert "consult_memory" in out
    assert "- 部署流程" in out
    assert "先 build 再 deploy" not in out  # worker catalog: names only


def test_worker_prompt_lists_topic_directory_when_memory_on():
    base = assemble_system_prompt()
    with_memory = compose_worker_base_prompt(
        base,
        memory_topics=[MemoryTopic("部署流程", "先 build")],
        memory_enabled=True,
    )
    assert "<记忆主题目录>" in with_memory
    assert "- 部署流程" in with_memory
    assert "先 build" not in with_memory  # summaries stay CEO-only

    without_memory = compose_worker_base_prompt(
        base,
        memory_topics=[MemoryTopic("部署流程", "先 build")],
        memory_enabled=False,
    )
    assert "<记忆主题目录>" not in without_memory


def test_worker_registry_wires_consult_memory_when_memory_on():
    worker_tools = build_worker_registry()
    _wire_worker_memory_tools(
        worker_tools, memory_enabled=True, folder_id="F1", has_memory_topics=True
    )
    cm = worker_tools.get_optional("consult_memory")
    assert cm is not None
    assert cm.folder_id == "F1"


def test_worker_registry_omits_consult_memory_when_memory_off():
    worker_tools = build_worker_registry()
    _wire_worker_memory_tools(
        worker_tools, memory_enabled=False, folder_id="F1", has_memory_topics=True
    )
    assert worker_tools.get_optional("consult_memory") is None


def test_worker_registry_omits_consult_memory_when_topics_empty():
    worker_tools = build_worker_registry()
    _wire_worker_memory_tools(
        worker_tools, memory_enabled=True, folder_id="F1", has_memory_topics=False
    )
    assert worker_tools.get_optional("consult_memory") is None

"""Tests for memory injection assembly (global + project layers, Agent记忆与知识系统 §二)."""

from agentcore.memory.injection import MemoryTopic, load_injected_memory, load_memory_topics
from agentcore.memory.store import CORE_MEMORY_FILE, PREFERENCES_MEMORY_FILE, FileMemoryStore
from agentcore.memory.user_memory import topic_summary_line


async def test_injected_memory_combines_preferences_and_profile(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", PREFERENCES_MEMORY_FILE, "## 沟通偏好\n- 用中文\n")
    await store.save("u1", CORE_MEMORY_FILE, "## 技术栈与工具\n- 用 Python\n")
    body = await load_injected_memory(store, "u1", folder_id=None, enabled=True)
    assert "用中文" in body
    assert "用 Python" in body


async def test_injected_memory_appends_project_layer_after_global(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 技术栈与工具\n- 用 Python\n")
    await store.save("u1", CORE_MEMORY_FILE, "## 关于用户的事实\n- 本项目用 Rust\n", scope="F1")
    body = await load_injected_memory(store, "u1", folder_id="F1", enabled=True)
    assert "用 Python" in body
    assert "本项目用 Rust" in body
    # Global is the stable prefix → comes before the labeled project layer.
    assert body.index("用 Python") < body.index("本项目用 Rust")


async def test_injected_memory_appends_project_navigation_after_profile(tmp_path):
    from agentcore.memory.store import NAVIGATION_MEMORY_FILE

    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 关于用户的事实\n- 本项目用 Rust\n", scope="F1")
    await store.save(
        "u1",
        NAVIGATION_MEMORY_FILE,
        "# 导航\n一句话：Rust 服务\n\n- 改 API → apps/server\n",
        scope="F1",
    )
    body = await load_injected_memory(store, "u1", folder_id="F1", enabled=True)
    assert "本项目用 Rust" in body
    assert "改 API" in body
    assert "导航短入口" in body
    assert body.index("本项目用 Rust") < body.index("改 API")
    # Missing navigation is skipped (no crash / no empty label).
    bare = FileMemoryStore(tmp_path / "bare")
    await bare.save("u1", CORE_MEMORY_FILE, "## 关于用户的事实\n- only profile\n", scope="F1")
    only = await load_injected_memory(bare, "u1", folder_id="F1", enabled=True)
    assert "only profile" in only
    assert "导航短入口" not in only


async def test_injected_memory_skips_project_layer_for_bare_chat(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 关于用户的事实\n- 本项目用 Rust\n", scope="F1")
    body = await load_injected_memory(store, "u1", folder_id=None, enabled=True)
    assert "本项目用 Rust" not in body


async def test_injected_memory_strips_chrome_per_file(tmp_path):
    store = FileMemoryStore(tmp_path)
    chrome = "# 用户记忆\n> 本文件由 AI 自动维护，你可随时编辑或删除任何条目。\n\n"
    await store.save("u1", PREFERENCES_MEMORY_FILE, chrome + "## 沟通偏好\n- 用中文\n")
    await store.save("u1", CORE_MEMORY_FILE, chrome + "## 技术栈与工具\n- 用 Python\n")
    body = await load_injected_memory(store, "u1", folder_id=None, enabled=True)
    # The human chrome of BOTH files is shed (not just the first) — it's stripped per file.
    assert "本文件由 AI 自动维护" not in body
    assert "用中文" in body and "用 Python" in body


async def test_injected_memory_empty_when_disabled(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 技术栈与工具\n- 用 Python\n")
    assert await load_injected_memory(store, "u1", folder_id=None, enabled=False) == ""


async def test_memory_topics_merge_global_and_project(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", "主题/全局主题.md", "## 要点\n- g\n")
    await store.save("u1", "主题/项目主题.md", "## 要点\n- p\n", scope="F1")
    topics = await load_memory_topics(store, "u1", folder_id="F1", enabled=True)
    # Names merged + sorted, each carrying its note's first-line summary (§1.4).
    assert topics == [MemoryTopic("全局主题", "g"), MemoryTopic("项目主题", "p")]


async def test_memory_topics_dedupe_across_scopes(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", "主题/部署.md", "## 要点\n- g\n")
    await store.save("u1", "主题/部署.md", "## 要点\n- p\n", scope="F1")
    topics = await load_memory_topics(store, "u1", folder_id="F1", enabled=True)
    # Same name in both scopes appears once; the GLOBAL summary wins (stable-prefix layer).
    assert topics == [MemoryTopic("部署", "g")]


async def test_memory_topics_empty_when_disabled(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", "主题/部署.md", "## 要点\n- g\n")
    assert await load_memory_topics(store, "u1", folder_id=None, enabled=False) == []


async def test_memory_topics_summary_skips_chrome_and_section(tmp_path):
    # The summary is the first SUBSTANTIVE line: H1/blockquote chrome + ## headers skipped,
    # the first bullet's text wins (记忆系统 §1.4「拟存主题文件首行」).
    store = FileMemoryStore(tmp_path)
    body = "# 用户记忆\n> 本文件由 AI 自动维护。\n\n## 要点\n- 先 build 再 deploy\n- 二线\n"
    await store.save("u1", "主题/部署流程.md", body)
    topics = await load_memory_topics(store, "u1", folder_id=None, enabled=True)
    assert topics == [MemoryTopic("部署流程", "先 build 再 deploy")]


async def test_injected_memory_caps_oversized_file_deterministically(tmp_path):
    # COST-001 读侧 backstop: an abnormally large memory file is DETERMINISTICALLY capped
    # (head slice + fixed notice), so it can't blow up the <rules> prefix AND the same body
    # yields the same truncation every turn (memory is the stable prefix → cache-safe).
    store = FileMemoryStore(tmp_path)
    big = "## 沟通偏好\n" + "- 用中文\n" * 5000
    await store.save("u1", PREFERENCES_MEMORY_FILE, big)
    out1 = await load_injected_memory(store, "u1", folder_id=None, enabled=True, file_char_cap=200)
    out2 = await load_injected_memory(store, "u1", folder_id=None, enabled=True, file_char_cap=200)
    assert out1 == out2  # deterministic → prefix-cache safe
    assert "已截断" in out1  # the fixed truncation notice rode along
    assert len(out1) < 400  # capped to ~200 + short notice, nowhere near the original


async def test_injected_memory_uncapped_when_no_cap_given(tmp_path):
    # Default (no file_char_cap) is unbounded — backward compatible with callers/tests
    # that don't pass it.
    store = FileMemoryStore(tmp_path)
    body = "## 沟通偏好\n" + "- 用中文\n" * 500
    await store.save("u1", PREFERENCES_MEMORY_FILE, body)
    out = await load_injected_memory(store, "u1", folder_id=None, enabled=True)
    assert "已截断" not in out
    assert out.count("用中文") == 500


def test_topic_summary_line_handles_freeform_truncation_and_empty():
    # Freeform first line (no bullet) is taken verbatim.
    assert topic_summary_line("自由文本第一行\n第二行") == "自由文本第一行"
    # Over-long summary is truncated with an ellipsis (directory stays cheap).
    summary = topic_summary_line("- " + "а" * 100)
    assert summary.endswith("…") and len(summary) == 60
    # Empty / chrome-only note → "" so the directory shows just the name.
    assert topic_summary_line("") == ""
    assert topic_summary_line("# 用户记忆\n> 注释\n") == ""

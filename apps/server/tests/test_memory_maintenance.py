"""Tests for the long-term memory store + per-turn maintenance closed loop."""

from collections.abc import Sequence

from agentcore.memory.maintenance import maintain_user_memory
from agentcore.memory.store import (
    CORE_MEMORY_FILE,
    PREFERENCES_MEMORY_FILE,
    FileMemoryStore,
    MemoryFileMeta,
    memory_version,
)
from agentcore.memory.user_memory import (
    MemoryAction,
    MemoryExtractInput,
    MemoryOp,
)

# --- FileMemoryStore (real disk via tmp_path) ---


async def test_store_load_missing_returns_empty(tmp_path):
    store = FileMemoryStore(tmp_path)
    assert await store.load("u1", CORE_MEMORY_FILE) == ""


async def test_store_save_then_load_round_trip(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 沟通偏好\n- 用中文\n")
    assert await store.load("u1", CORE_MEMORY_FILE) == "## 沟通偏好\n- 用中文\n"
    # Stored under a per-user folder, not a flat <user>.md file.
    assert (tmp_path / "u1" / CORE_MEMORY_FILE).is_file()


async def test_store_is_per_user(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("alice", CORE_MEMORY_FILE, "alice memory")
    await store.save("bob", CORE_MEMORY_FILE, "bob memory")
    assert await store.load("alice", CORE_MEMORY_FILE) == "alice memory"
    assert await store.load("bob", CORE_MEMORY_FILE) == "bob memory"


async def test_store_neutralizes_user_id_separators(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("../../etc/passwd", CORE_MEMORY_FILE, "x")
    # Stays inside the base dir (no traversal); round-trips by the same key.
    assert await store.load("../../etc/passwd", CORE_MEMORY_FILE) == "x"
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1
    assert all(tmp_path in p.parents for p in files)


async def test_store_neutralizes_path_segments(tmp_path):
    store = FileMemoryStore(tmp_path)
    # A crafted relative path with traversal must not escape the user folder.
    await store.save("u1", "../../escape.md", "x")
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files and all(tmp_path / "u1" in p.parents for p in files)
    assert await store.load("u1", "../../escape.md") == "x"


async def test_store_list_empty_for_new_user(tmp_path):
    store = FileMemoryStore(tmp_path)
    assert await store.list("nobody") == []


async def test_store_list_reports_path_and_per_file_version(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "body")
    assert await store.list("u1") == [
        MemoryFileMeta(path=CORE_MEMORY_FILE, version=memory_version("body"))
    ]


async def test_store_delete_removes_file(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "body")
    await store.delete("u1", CORE_MEMORY_FILE)
    assert await store.load("u1", CORE_MEMORY_FILE) == ""
    assert await store.list("u1") == []
    # Deleting a missing file is a no-op, never an error.
    await store.delete("u1", CORE_MEMORY_FILE)


# --- maintain_user_memory (extractor + applier + store) ---


class _FakeExtractor:
    """Returns canned ops and records the inputs it saw."""

    def __init__(self, ops: list[MemoryOp]) -> None:
        self._ops = ops
        self.inputs: list[MemoryExtractInput] = []

    async def extract(self, data: MemoryExtractInput) -> list[MemoryOp]:
        self.inputs.append(data)
        return list(self._ops)


class _RaisingExtractor:
    async def extract(self, data: MemoryExtractInput) -> list[MemoryOp]:
        raise RuntimeError("llm down")


def _turn() -> Sequence[dict]:
    return [{"role": "user", "content": "我以后都用 pnpm"}]


async def test_maintain_writes_when_ops_present(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [MemoryOp(action=MemoryAction.ADD, section="技术栈与工具", content="偏好 pnpm")]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store
    )
    assert changed is True
    saved = await store.load("u1", CORE_MEMORY_FILE)
    assert "## 技术栈与工具" in saved
    assert "- 偏好 pnpm" in saved


async def test_maintain_passes_current_profile_to_extractor(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 沟通偏好\n- 已有偏好\n")
    extractor = _FakeExtractor([])
    await maintain_user_memory(user_id="u1", messages=_turn(), extractor=extractor, store=store)
    assert "已有偏好" in extractor.inputs[0].current_profile


async def test_maintain_skips_write_when_no_ops(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "original")
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=_FakeExtractor([]), store=store
    )
    assert changed is False
    assert await store.load("u1", CORE_MEMORY_FILE) == "original"


async def test_maintain_is_idempotent_for_duplicate_op(tmp_path):
    store = FileMemoryStore(tmp_path)
    op = MemoryOp(action=MemoryAction.ADD, section="技术栈与工具", content="偏好 pnpm")
    # First turn writes the bullet (and canonicalizes the file).
    assert await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=_FakeExtractor([op]), store=store
    )
    before = await store.load("u1", CORE_MEMORY_FILE)
    # Second turn re-extracts the same bullet: the applier dedups it, so the
    # canonical content is unchanged and the write is skipped.
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=_FakeExtractor([op]), store=store
    )
    assert changed is False
    assert await store.load("u1", CORE_MEMORY_FILE) == before


async def test_maintain_empty_messages_returns_false(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor([MemoryOp(action=MemoryAction.ADD, section="沟通偏好", content="x")])
    changed = await maintain_user_memory(
        user_id="u1", messages=[], extractor=extractor, store=store
    )
    assert changed is False
    assert extractor.inputs == []  # extractor not even called


async def test_maintain_swallows_extractor_failure(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "original")
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=_RaisingExtractor(), store=store
    )
    assert changed is False
    assert await store.load("u1", CORE_MEMORY_FILE) == "original"


# --- topic notes (on-demand 主题/<slug>.md) ---


async def test_maintain_creates_topic_note(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [MemoryOp(action=MemoryAction.ADD, content="用 docker compose 部署", file="主题/部署.md")]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store
    )
    assert changed is True
    assert "用 docker compose 部署" in await store.load("u1", "主题/部署.md")
    assert (tmp_path / "u1" / "主题" / "部署.md").is_file()


async def test_maintain_routes_ops_to_core_and_topic(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [
            MemoryOp(action=MemoryAction.ADD, section="技术栈与工具", content="偏好 pnpm"),
            MemoryOp(action=MemoryAction.ADD, content="部署踩坑：忘了迁移", file="主题/部署.md"),
        ]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store
    )
    assert changed is True
    assert "偏好 pnpm" in await store.load("u1", CORE_MEMORY_FILE)
    assert "部署踩坑" in await store.load("u1", "主题/部署.md")


async def test_maintain_surfaces_existing_topics_to_extractor(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", "主题/部署.md", "## 要点\n- 旧记录\n")
    extractor = _FakeExtractor([])
    await maintain_user_memory(user_id="u1", messages=_turn(), extractor=extractor, store=store)
    assert "部署" in extractor.inputs[0].topic_files


async def test_maintain_enforces_topic_cap(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [
            MemoryOp(action=MemoryAction.ADD, content="a", file="主题/A.md"),
            MemoryOp(action=MemoryAction.ADD, content="b", file="主题/B.md"),
            MemoryOp(action=MemoryAction.ADD, content="c", file="主题/C.md"),
        ]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store, max_topic_files=2
    )
    assert changed is True
    # Only the first two new topic notes are admitted under the cap; the third is dropped.
    assert sorted(m.path for m in await store.list("u1")) == ["主题/A.md", "主题/B.md"]


# --- scope isolation (FileMemoryStore global vs project layers, Agent记忆与知识系统 §1.4) ---


async def test_store_project_scope_is_isolated_from_global(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "global facts")
    await store.save("u1", CORE_MEMORY_FILE, "project facts", scope="F1")
    assert await store.load("u1", CORE_MEMORY_FILE) == "global facts"
    assert await store.load("u1", CORE_MEMORY_FILE, scope="F1") == "project facts"


async def test_store_global_list_excludes_project_notes(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "g")
    await store.save("u1", "主题/部署.md", "gt")
    await store.save("u1", CORE_MEMORY_FILE, "p", scope="F1")
    await store.save("u1", "主题/proj.md", "pt", scope="F1")
    # The global list never surfaces a project's notes (nested under the reserved container).
    assert sorted(m.path for m in await store.list("u1")) == ["主题/部署.md", "画像.md"]
    assert sorted(m.path for m in await store.list("u1", scope="F1")) == ["主题/proj.md", "画像.md"]


async def test_store_projects_are_isolated_from_each_other(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "f1", scope="F1")
    await store.save("u1", CORE_MEMORY_FILE, "f2", scope="F2")
    assert await store.load("u1", CORE_MEMORY_FILE, scope="F1") == "f1"
    assert await store.load("u1", CORE_MEMORY_FILE, scope="F2") == "f2"
    assert await store.load("u1", CORE_MEMORY_FILE) == ""  # global untouched


async def test_store_delete_is_scoped(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "g")
    await store.save("u1", CORE_MEMORY_FILE, "p", scope="F1")
    await store.delete("u1", CORE_MEMORY_FILE, scope="F1")
    assert await store.load("u1", CORE_MEMORY_FILE, scope="F1") == ""
    assert await store.load("u1", CORE_MEMORY_FILE) == "g"  # global delete didn't fire


# --- project_scopes (which projects have memory → the「文件」rail node, P2) ----------


async def test_store_project_scopes_lists_projects_with_memory(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "global")  # global-only → not a project scope
    await store.save("u1", CORE_MEMORY_FILE, "p1", scope="F1")
    await store.save("u1", "主题/x.md", "t", scope="F2")  # topic-only project still counts
    assert await store.project_scopes("u1") == ["F1", "F2"]


async def test_store_project_scopes_empty_without_projects(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "global only")
    assert await store.project_scopes("u1") == []


async def test_store_project_scopes_drops_emptied_project(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "p", scope="F1")
    assert await store.project_scopes("u1") == ["F1"]
    await store.delete("u1", CORE_MEMORY_FILE, scope="F1")  # last file gone
    assert await store.project_scopes("u1") == []  # empty dir no longer surfaces


# --- scope + 偏好/画像 routing through maintain_user_memory (P0+P1) ---


async def test_maintain_routes_project_scoped_op_to_project_layer(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [
            MemoryOp(
                action=MemoryAction.ADD,
                section="关于用户的事实",
                content="本项目用 Rust",
                file=CORE_MEMORY_FILE,
                scope="F1",
            )
        ]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store, folder_id="F1"
    )
    assert changed is True
    assert "本项目用 Rust" in await store.load("u1", CORE_MEMORY_FILE, scope="F1")
    assert await store.load("u1", CORE_MEMORY_FILE) == ""  # global core untouched


async def test_maintain_routes_global_and_project_in_one_pass(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [
            MemoryOp(action=MemoryAction.ADD, section="技术栈与工具", content="全局 Python"),
            MemoryOp(
                action=MemoryAction.ADD,
                section="技术栈与工具",
                content="本项目 Rust",
                file=CORE_MEMORY_FILE,
                scope="F1",
            ),
        ]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store, folder_id="F1"
    )
    assert changed is True
    assert "全局 Python" in await store.load("u1", CORE_MEMORY_FILE)
    assert "本项目 Rust" in await store.load("u1", CORE_MEMORY_FILE, scope="F1")


async def test_maintain_writes_preferences_to_preferences_file(tmp_path):
    store = FileMemoryStore(tmp_path)
    extractor = _FakeExtractor(
        [
            MemoryOp(
                action=MemoryAction.ADD,
                section="沟通偏好",
                content="用中文",
                file=PREFERENCES_MEMORY_FILE,
            )
        ]
    )
    changed = await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store
    )
    assert changed is True
    assert "用中文" in await store.load("u1", PREFERENCES_MEMORY_FILE)


async def test_maintain_surfaces_project_layer_to_extractor(tmp_path):
    store = FileMemoryStore(tmp_path)
    await store.save("u1", CORE_MEMORY_FILE, "## 关于用户的事实\n- 本项目事实\n", scope="F1")
    await store.save("u1", "主题/部署.md", "## 要点\n- x\n", scope="F1")
    extractor = _FakeExtractor([])
    await maintain_user_memory(
        user_id="u1", messages=_turn(), extractor=extractor, store=store, folder_id="F1"
    )
    data = extractor.inputs[0]
    assert data.folder_id == "F1"
    assert "本项目事实" in data.current_project_memory
    assert "部署" in data.project_topic_files


async def test_maintain_topic_cap_is_per_scope(tmp_path):
    store = FileMemoryStore(tmp_path)
    # Global is already at cap=1; a NEW project topic is still admitted (counted separately).
    await store.save("u1", "主题/G.md", "## 要点\n- g\n")
    extractor = _FakeExtractor(
        [MemoryOp(action=MemoryAction.ADD, content="proj", file="主题/P.md", scope="F1")]
    )
    changed = await maintain_user_memory(
        user_id="u1",
        messages=_turn(),
        extractor=extractor,
        store=store,
        folder_id="F1",
        max_topic_files=1,
    )
    assert changed is True
    assert "proj" in await store.load("u1", "主题/P.md", scope="F1")

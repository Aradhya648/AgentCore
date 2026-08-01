"""Tests for the intra-batch write-conflict guard (并行写隔离·硬约束).

Two layers: the pure :class:`WriteCoordinator` ownership rules, and the
``FileWriteTool`` end-to-end behaviour when a coordinator is wired onto the context
(concurrent sibling refused; dependency overwrite allowed; no-coordinator path inert).
"""

import json
from pathlib import Path

from agentcore.llm.provider.protocol import ToolCall, ToolCallFunction
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.runtime.events import EventSink
from agentcore.runtime.loop_controller import DEFAULT_TOOL_FAILURE_DISABLE, LoopController
from agentcore.tools.builtin.file_ops import FileAppendTool, FileWriteTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from agentcore.workspace.write_claims import WriteCoordinator


def _ctx(
    workspace: Path,
    *,
    run_id: str = "s",
    coordinator: WriteCoordinator | None = None,
    ancestors: frozenset[str] = frozenset(),
) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id=run_id,
        agent_id="a",
        backend=ServerWorkspace(root=workspace, sandbox=SubprocessSandbox()),
        user_id="u",
        write_coordinator=coordinator,
        write_ancestors=ancestors,
    )


# --- WriteCoordinator unit rules ---


def test_first_claim_granted():
    c = WriteCoordinator()
    assert c.claim("report.md", "a", frozenset()) is None


def test_concurrent_sibling_conflicts():
    c = WriteCoordinator()
    assert c.claim("report.md", "a", frozenset()) is None
    # b has no dependency on a → blocked, told who owns it.
    assert c.claim("report.md", "b", frozenset()) == "a"


def test_same_run_may_rewrite_its_own_file():
    c = WriteCoordinator()
    assert c.claim("report.md", "a", frozenset()) is None
    # A contract retry re-writes the same path under the same run → allowed.
    assert c.claim("report.md", "a", frozenset()) is None


def test_descendant_may_overwrite_ancestor_file():
    c = WriteCoordinator()
    assert c.claim("report.md", "upstream", frozenset()) is None
    # d depends on upstream → consolidating its product is intended, not a clobber.
    assert c.claim("report.md", "d", frozenset({"upstream"})) is None
    # ownership transferred to d: a fresh unrelated sibling now conflicts with d.
    assert c.claim("report.md", "e", frozenset()) == "d"


def test_paths_normalized_to_one_owner():
    c = WriteCoordinator()
    assert c.claim("out/report.md", "a", frozenset()) is None
    # ./out/report.md and out//report.md are the same file → same conflict.
    assert c.claim("./out/report.md", "b", frozenset()) == "a"
    assert c.claim("out//report.md", "b", frozenset()) == "a"


def test_release_frees_a_failed_write():
    c = WriteCoordinator()
    assert c.claim("report.md", "a", frozenset()) is None
    c.release("report.md", "a")
    # a never really wrote it (write failed) → b is free to take the name.
    assert c.claim("report.md", "b", frozenset()) is None


def test_release_only_affects_the_owner():
    c = WriteCoordinator()
    assert c.claim("report.md", "a", frozenset()) is None
    # b doesn't own it; its release is a no-op (can't free a's claim).
    c.release("report.md", "b")
    assert c.claim("report.md", "b", frozenset()) == "a"


# --- FileWriteTool end-to-end ---


async def test_concurrent_sibling_write_is_refused_and_does_not_clobber(tmp_path: Path):
    coordinator = WriteCoordinator()
    a = await FileWriteTool().execute(
        {"path": "report.md", "content": "from-A"},
        _ctx(tmp_path, run_id="a", coordinator=coordinator),
    )
    assert a.success is True

    b = await FileWriteTool().execute(
        {"path": "report.md", "content": "from-B"},
        _ctx(tmp_path, run_id="b", coordinator=coordinator),
    )
    assert b.success is False
    assert "写入冲突" in b.error
    assert "`a`" in b.error or "owner" in b.error.lower() or "负责" in b.error
    # A's deliverable survives — B never overwrote it.
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "from-A"


async def test_dependency_overwrite_is_allowed(tmp_path: Path):
    coordinator = WriteCoordinator()
    await FileWriteTool().execute(
        {"path": "report.md", "content": "draft"},
        _ctx(tmp_path, run_id="up", coordinator=coordinator),
    )
    # downstream depends on "up" → may consolidate (overwrite) its file.
    d = await FileWriteTool().execute(
        {"path": "report.md", "content": "final"},
        _ctx(tmp_path, run_id="down", coordinator=coordinator, ancestors=frozenset({"up"})),
    )
    assert d.success is True
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "final"


async def test_write_conflict_result_is_contract_failure(tmp_path: Path):
    """并发写冲突回执标 contract_failure（自我纠正型参数打回）——file_write 与 file_append 对称。"""
    coordinator = WriteCoordinator()
    await FileWriteTool().execute(
        {"path": "report.md", "content": "from-A"},
        _ctx(tmp_path, run_id="a", coordinator=coordinator),
    )
    # A concurrent sibling's file_write onto A's claimed path collides.
    w = await FileWriteTool().execute(
        {"path": "report.md", "content": "from-B"},
        _ctx(tmp_path, run_id="b", coordinator=coordinator),
    )
    assert w.success is False
    assert w.contract_failure is True

    # file_append onto the same claimed path collides identically.
    ap = await FileAppendTool().execute(
        {"path": "report.md", "content": "more"},
        _ctx(tmp_path, run_id="c", coordinator=coordinator),
    )
    assert ap.success is False
    assert ap.contract_failure is True


async def test_write_conflict_does_not_trip_run_circuit_breaker(tmp_path: Path):
    """写冲突经 execute_tools→LoopController 不计入 run 级熔断：同批连撞不烧穿禁用阈值。"""
    coordinator = WriteCoordinator()
    a = await FileWriteTool().execute(
        {"path": "report.md", "content": "from-A"},
        _ctx(tmp_path, run_id="a", coordinator=coordinator),
    )
    assert a.success is True

    reg = ToolRegistry()
    reg.register(FileWriteTool())
    controller = LoopController(tool_failure_warn=2, tool_failure_disable=3)
    # A concurrent sibling collides more times than the disable threshold.
    for _ in range(DEFAULT_TOOL_FAILURE_DISABLE + 1):
        tc = ToolCall(
            id="c",
            function=ToolCallFunction(
                name="file_write",
                arguments=json.dumps({"path": "report.md", "content": "from-B"}),
            ),
        )
        _msgs, _terminal, attempts = await execute_tools(
            [tc], reg, _ctx(tmp_path, run_id="b", coordinator=coordinator), EventSink()
        )
        assert attempts[0].success is False
        assert attempts[0].contract_failure is True  # forwarded from the ToolResult
        controller.record(attempts)

    # The run-scoped breaker never tallied the collisions → tool stays enabled.
    # Same-fingerprint validation may path-stop (steer) without disabling the pen.
    assert controller.tool_failure_count("file_write") == 0
    cb = controller.tool_circuit_breaker()
    assert cb.disabled == ()
    assert cb.warned == ()
    assert cb.force_segmented == frozenset()
    # A's deliverable survived every collision (B never overwrote it).
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "from-A"


async def test_no_coordinator_means_no_guard(tmp_path: Path):
    # The CEO / tests path: without a coordinator, file_write is unguarded (two writes
    # to the same path just overwrite, last-writer-wins — the pre-existing behaviour).
    first = await FileWriteTool().execute(
        {"path": "report.md", "content": "one"}, _ctx(tmp_path, run_id="a")
    )
    second = await FileWriteTool().execute(
        {"path": "report.md", "content": "two"}, _ctx(tmp_path, run_id="b")
    )
    assert first.success is True
    assert second.success is True
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "two"


# --- C3: str_replace / write_section / declare / transfer ---


async def test_str_replace_respects_ownership(tmp_path: Path):
    from agentcore.tools.builtin.file_ops import StrReplaceTool

    coordinator = WriteCoordinator()
    # 新建（非覆盖非空代码）以建立 integration 归属。
    await FileWriteTool().execute(
        {"path": "App.tsx", "content": "from-integration"},
        _ctx(tmp_path, run_id="integration", coordinator=coordinator),
    )
    r = await StrReplaceTool().execute(
        {"path": "App.tsx", "old_string": "from-integration", "new_string": "hijack"},
        _ctx(tmp_path, run_id="frontend", coordinator=coordinator),
    )
    assert r.success is False
    assert "integration" in (r.error or "")
    assert "负责" in (r.error or "")
    assert (tmp_path / "App.tsx").read_text(encoding="utf-8") == "from-integration"


def test_declare_does_not_steal_from_ancestor():
    """交接式：下游派发声明同 path 不抢祖先锁；真写时再交接。"""
    c = WriteCoordinator()
    assert c.declare("site/index.html", "skeleton", frozenset()) is None
    assert (
        c.declare("site/index.html", "assemble", frozenset({"skeleton"})) is None
    )
    assert c.owner_of("site/index.html") == "skeleton"
    assert c.claim("site/index.html", "assemble", frozenset({"skeleton"})) is None
    assert c.owner_of("site/index.html") == "assemble"


def test_declare_ancestor_handoff_opt_in():
    c = WriteCoordinator()
    c.declare("a.ts", "lead", frozenset())
    assert (
        c.declare(
            "a.ts",
            "child",
            frozenset({"lead"}),
            allow_ancestor_handoff=True,
        )
        is None
    )
    assert c.owner_of("a.ts") == "child"


def test_declare_and_completed_owner_still_blocks():
    c = WriteCoordinator()
    assert c.declare("site/index.html", "skeleton", frozenset()) is None
    # Completed owner still holds — unrelated sibling cannot declare or claim.
    assert c.declare("site/index.html", "frontend", frozenset()) == "skeleton"
    assert c.claim("site/index.html", "frontend", frozenset()) == "skeleton"


def test_replaces_transfers_ownership():
    c = WriteCoordinator()
    c.declare("App.tsx", "old_fe", frozenset())
    moved = c.transfer_all_from("old_fe", "new_fe")
    assert "App.tsx" in moved
    assert c.owner_of("App.tsx") == "new_fe"
    assert c.claim("App.tsx", "new_fe", frozenset()) is None


def test_force_claim_transfers():
    c = WriteCoordinator()
    c.claim("x.md", "a", frozenset())
    assert c.claim("x.md", "b", frozenset(), force=True) is None
    assert c.owner_of("x.md") == "b"


def test_ownership_snapshot_roundtrip():
    c = WriteCoordinator()
    c.declare("a/b.md", "w1", frozenset())
    c.mark_written("a/b.md")
    restored = WriteCoordinator.from_dict(c.to_dict())
    assert restored.owner_of("a/b.md") == "w1"
    assert restored.is_written("a/b.md")
    assert restored.claim("a/b.md", "w2", frozenset()) == "w1"


def test_legacy_flat_snapshot_still_loads():
    restored = WriteCoordinator.from_dict({"a/b.md": "w1"})
    assert restored.owner_of("a/b.md") == "w1"
    assert not restored.is_written("a/b.md")


def test_conflict_message_distinguishes_declared_vs_written():
    from agentcore.workspace.write_claims import ownership_conflict_message

    declared = ownership_conflict_message(
        "src/x.ts",
        "backend-fix",
        ownership_kind="declared",
        owner_status="running",
    )
    assert "仅派发占位" in declared
    assert "不是上一 run 残留锁" in declared
    assert "进行中" in declared
    assert "transfer_ownership" in declared

    written = ownership_conflict_message(
        "src/x.ts",
        "backend-fix",
        owner_role="后端补齐",
        ownership_kind="written",
        owner_status="completed",
    )
    assert "已成功写入" in written
    assert "已完成" in written
    assert "后端补齐" in written


def test_ancestors_include_nested_parent_run_id():
    from agentcore.runtime.runs.executor_context import _ancestors_by_id
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec

    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="storage",
                role="存储",
                task="写 storage",
                parent_run_id="backend-fix",
                depth=1,
            ),
            RunSpec(
                run_id="tools",
                role="工具",
                task="写 tools",
                parent_run_id="backend-fix",
                depth=1,
            ),
        ]
    )
    anc = _ancestors_by_id(plan)
    assert "backend-fix" in anc["storage"]
    assert "backend-fix" in anc["tools"]
    # Siblings do not count each other as ancestors.
    assert "tools" not in anc["storage"]
    assert "storage" not in anc["tools"]


def test_nested_child_may_claim_parent_declared_path():
    c = WriteCoordinator()
    assert c.declare("src/storage/db.ts", "backend-fix", frozenset()) is None
    # Child write_ancestors includes nested parent → claim succeeds and transfers.
    assert (
        c.claim("src/storage/db.ts", "storage", frozenset({"backend-fix"})) is None
    )
    assert c.owner_of("src/storage/db.ts") == "storage"
    # Unrelated peer still blocked by the new owner.
    assert c.claim("src/storage/db.ts", "other", frozenset()) == "storage"


def test_nested_siblings_still_mutex_under_shared_parent():
    c = WriteCoordinator()
    c.declare("src/tools/base-tool.ts", "backend-fix", frozenset())
    assert (
        c.claim("src/tools/base-tool.ts", "tools_a", frozenset({"backend-fix"}))
        is None
    )
    # Sibling only has parent in ancestors, not tools_a → conflict.
    assert (
        c.claim("src/tools/base-tool.ts", "tools_b", frozenset({"backend-fix"}))
        == "tools_a"
    )

def test_handoff_owned_paths_on_complete_unique_dependent():
    from agentcore.runtime.coordination.append_guard import (
        declare_plan_artifacts,
        handoff_owned_paths_on_complete,
    )
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import Deliverable, RunSpec
    from agentcore.workspace.write_claims import WriteCoordinator

    plan = RunPlan()
    for node in (
        RunSpec(
            run_id="skeleton",
            role="骨架",
            task="壳",
            deliverable=Deliverable(
                artifacts=["site/index.html", "site/styles.css", "site/CONTRACT.md"]
            ),
        ),
        RunSpec(
            run_id="section_0",
            role="分区",
            task="块",
            depends_on=["skeleton"],
            deliverable=Deliverable(artifacts=["site/sections/s0.html"]),
        ),
        RunSpec(
            run_id="assemble",
            role="组装",
            task="合",
            depends_on=["section_0"],
            deliverable=Deliverable(
                artifacts=["site/index.html", "site/styles.css", "site/main.js"]
            ),
        ),
    ):
        plan.add(node)
    ownership = WriteCoordinator()
    declare_plan_artifacts(plan, ownership)
    assert ownership.owner_of("site/index.html") == "skeleton"
    assert ownership.owner_of("site/styles.css") == "skeleton"
    # assemble declared intent only — did not steal
    moved = handoff_owned_paths_on_complete(
        plan, ownership, "skeleton", completed_run_ids={"skeleton"}
    )
    assert ("site/index.html", "assemble") in moved
    assert ("site/styles.css", "assemble") in moved
    assert ownership.owner_of("site/CONTRACT.md") == "skeleton"
    assert ownership.owner_of("site/index.html") == "assemble"

from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.executor import build_agent_executor
from agentcore.runtime.runs.executor_context import (
    _build_messages,
    _safe_index_files,
    _workspace_manifest,
)
from agentcore.runtime.runs.types import RunSpec
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.runs_executor.conftest import (
    _WS_ROOT,
    _ContentProvider,
    _CountingIndexBackend,
    _plan,
    _state,
)


def test_workspace_manifest_lists_nondep_teammate_files():
    plan = _plan(
        RunSpec(run_id="a", agent_id="a", role="队友A", task="x"),
        RunSpec(run_id="b", agent_id="b", role="队友B", task="y"),
    )
    completed = {"a": _state(files=["a.py"]), "b": _state(files=["b.py"])}
    # The worker depends on "a" (excluded — it gets the richer pointer block); the
    # non-dep peer "b" is surfaced so its product is discoverable.
    manifest = _workspace_manifest(plan, completed, [], exclude_runs={"a"})
    assert "b.py" in manifest and "队友B" in manifest
    assert "a.py" not in manifest  # the dep is not duplicated here


def test_workspace_manifest_lists_preexisting_files():
    plan = _plan(RunSpec(run_id="a", agent_id="a", role="队友A", task="x"))
    # No peer products; the ambient index (uploads / prior turns) is surfaced.
    manifest = _workspace_manifest(plan, {}, ["上传/data.csv", "spec.md"], exclude_runs=set())
    assert "上传/data.csv" in manifest and "spec.md" in manifest
    assert "工作区已有" in manifest


def test_workspace_manifest_lists_attachments_with_label():
    plan = _plan(RunSpec(run_id="a", agent_id="a", role="队友A", task="x"))
    manifest = _workspace_manifest(
        plan, {}, ["attachments/brief.pdf", "notes.md"], exclude_runs=set()
    )
    assert "attachments/brief.pdf（附件）" in manifest
    assert "notes.md（工作区已有）" in manifest


def test_workspace_manifest_project_summarizes_shared_files():
    plan = _plan(RunSpec(run_id="a", agent_id="a", role="队友A", task="x"))
    completed = {"a": _state(files=["peer_out.py"])}
    index = ["attachments/in.md", *[f"src/f{i}.py" for i in range(10)]]
    manifest = _workspace_manifest(
        plan, completed, index, exclude_runs=set(), shared_workspace=True
    )
    assert "peer_out.py" in manifest and "队友A" in manifest
    assert "attachments/in.md（附件）" in manifest
    assert "最近触达" in manifest
    assert "另有 5 个文件，需要时用 file_list / grep" in manifest
    # Shared tree is not fully enumerated.
    assert manifest.count("src/f") <= 5


def test_workspace_manifest_dedupes_dep_and_peer_files_from_index():
    plan = _plan(
        RunSpec(run_id="dep", agent_id="dep", role="前置", task="x"),
        RunSpec(run_id="peer", agent_id="peer", role="队友", task="y"),
    )
    completed = {"dep": _state(files=["dep.py"]), "peer": _state(files=["peer.py"])}
    # The index also lists dep.py + peer.py (they're on disk) plus an ambient file.
    manifest = _workspace_manifest(
        plan, completed, ["dep.py", "peer.py", "ambient.txt"], exclude_runs={"dep"}
    )
    # dep file stays out entirely (it has the pointer block); peer file is attributed,
    # not re-listed as「工作区已有」; the genuinely ambient file is labeled as such.
    assert "dep.py" not in manifest
    assert manifest.count("peer.py") == 1 and "队友" in manifest
    assert "ambient.txt（工作区已有）" in manifest


def test_workspace_manifest_empty_when_nothing_to_surface():
    plan = _plan(RunSpec(run_id="a", agent_id="a", role="队友A", task="x"))
    # Only files belong to a dep (excluded) and nothing in the index → empty.
    assert _workspace_manifest(plan, {"a": _state(files=["a.py"])}, [], exclude_runs={"a"}) == ""
    # A teammate that wrote nothing + no index contributes nothing.
    assert _workspace_manifest(plan, {"a": _state("仅文字")}, [], exclude_runs=set()) == ""


def test_workspace_manifest_caps_total_files():
    specs = [RunSpec(run_id=f"r{i}", agent_id=f"r{i}", role=f"R{i}", task="t") for i in range(60)]
    plan = _plan(*specs)
    completed = {f"r{i}": _state(files=[f"r{i}.txt"]) for i in range(60)}
    # 60 peer files + 60 ambient files: the count cap binds (short paths stay well under
    # the char budget) → exactly WORKSPACE_MANIFEST_MAX_FILES entries + one elision line.
    index = [f"amb{i}.txt" for i in range(60)]
    manifest = _workspace_manifest(plan, completed, index, exclude_runs=set())
    entries = [ln for ln in manifest.splitlines() if ln.startswith("- ")]
    assert len(entries) == 40  # WORKSPACE_MANIFEST_MAX_FILES
    assert "另有" in manifest.splitlines()[-1] or manifest.splitlines()[-1].startswith("……")


def test_workspace_manifest_char_budget_binds_before_count():
    # A few very long paths blow the char budget before the 40-file count cap — the
    # budget must bind first so long paths can't bloat the prompt.
    plan = _plan(RunSpec(run_id="a", agent_id="a", role="A", task="t"))
    long_paths = [f"deeply/nested/dir/segment/{i}/" + ("x" * 200) + ".txt" for i in range(40)]
    manifest = _workspace_manifest(plan, {}, long_paths, exclude_runs=set())
    entries = [ln for ln in manifest.splitlines() if ln.startswith("- ")]
    assert 0 < len(entries) < 40  # stopped by the char budget, not the count cap
    assert len(manifest) <= 2200  # ~CHAR_BUDGET + the elision line, not 40×200
    assert "另有" in manifest.splitlines()[-1] or manifest.splitlines()[-1].startswith("……")


def test_build_messages_injects_workspace_manifest():
    plan = _plan(
        RunSpec(run_id="me", agent_id="me", role="我", task="干活", depends_on=["dep"]),
        RunSpec(run_id="dep", agent_id="dep", role="前置", task="前置"),
        RunSpec(run_id="peer", agent_id="peer", role="并行队友", task="别的"),
    )
    completed = {
        "dep": _state("前置产物"),
        "peer": _state(files=["peer/out.json"]),
    }
    msgs = _build_messages(
        plan, plan.by_id("me"), completed, "SYS", "原始请求", index_paths=["上传/raw.txt"]
    )
    user = msgs[1].content or ""
    assert "工作区现有文件" in user
    assert "peer/out.json" in user and "并行队友" in user  # peer product, attributed
    assert "上传/raw.txt" in user  # pre-existing file from the index


def test_build_messages_no_manifest_block_when_nothing_ambient():
    plan = _plan(RunSpec(run_id="me", agent_id="me", role="我", task="干活"))
    msgs = _build_messages(plan, plan.by_id("me"), {}, "SYS", "原始请求")
    assert "工作区现有文件" not in (msgs[1].content or "")


async def test_safe_index_files_swallows_backend_failure():
    class _Boom:
        async def index_files(self, **_kw):
            raise RuntimeError("desktop dropped")

    class _Ok:
        def __init__(self) -> None:
            self.order: str | None = None

        async def index_files(self, *, order: str = "path"):
            self.order = order
            return (["a.txt", "b.txt"], True)

    assert await _safe_index_files(_Boom()) == []  # failure → empty, never raises
    assert await _safe_index_files(object()) == []  # backend without indexing → empty
    ok = _Ok()
    assert await _safe_index_files(ok) == ["a.txt", "b.txt"]  # paths, flag dropped
    assert ok.order == "recent"  # manifest asks for newest-first relevance ordering


async def test_preexisting_index_snapshotted_once_per_turn():
    # Three workers in one batch share a SINGLE workspace index walk (the per-turn
    # snapshot cache), not one walk per worker — so the mtime stat cost doesn't multiply.
    backend = _CountingIndexBackend(ServerWorkspace(root=_WS_ROOT, sandbox=SubprocessSandbox()))
    ctx = ToolContext(execution_id="e", run_id="s", agent_id="a", backend=backend, user_id="u")
    plan, _ = build_run_plan(
        [
            {"role": "A", "task": "a"},
            {"role": "B", "task": "b"},
            {"role": "C", "task": "c"},
        ],
        id_prefix="t",
    )
    provider = _ContentProvider(["A", "B", "C"])
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=ctx,
        system_prompt="SYS",
        user_message="原始请求",
        execution_id="e",
    )
    await WaveScheduler().run(plan, executor)
    assert backend.index_calls == 1  # one walk for the whole batch, not three

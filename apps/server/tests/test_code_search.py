"""Tests for code_search indexing and tool."""

from pathlib import Path

import pytest

from agentcore.tools.builtin.code_search import CodeSearchTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.indexing.chunker import chunk_file, detect_language
from agentcore.workspace.indexing.manager import IndexManager
from agentcore.workspace.server import ServerWorkspace


@pytest.fixture
def sample_py(tmp_path: Path) -> Path:
    src = tmp_path / "pkg" / "sample.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        '''"""Sample module."""

class ApprovalGate:
    """Gate tool approvals."""

    async def check(self, tool_name: str) -> bool:
        """Check whether a tool may run."""
        return True


def helper_function():
  return "noop"
''',
        encoding="utf-8",
    )
    return tmp_path


def test_detect_language_python():
    assert detect_language("apps/foo/bar.py") == "python"
    assert detect_language("component.tsx") == "tsx"


@pytest.mark.asyncio
async def test_chunk_file_python_symbols():
    content = '''class Foo:
    def bar(self):
        pass

def baz():
    return 1
'''
    chunks = await chunk_file("mod.py", content, "python")
    assert chunks
    symbols = {c.symbol for c in chunks if c.symbol}
    assert "Foo" in symbols or "bar" in symbols or "baz" in symbols


@pytest.mark.asyncio
async def test_index_manager_build_and_search(sample_py: Path):
    ws = ServerWorkspace(root=sample_py, sandbox=SubprocessSandbox())
    manager = IndexManager.for_workspace_root(str(sample_py))

    updated = await manager.ensure_index(ws)
    assert updated is True

    result = await manager.search("approval gate check", max_results=5)
    assert result.chunks
    assert result.scores
    assert len(result.chunks) == len(result.scores)
    paths = {c.path for c in result.chunks}
    assert any("sample.py" in p for p in paths)

    db_path = sample_py / ".agentcore" / "index" / "code_search.db"
    assert db_path.is_file()


@pytest.mark.asyncio
async def test_code_search_tool_end_to_end(sample_py: Path):
    ws = ServerWorkspace(root=sample_py, sandbox=SubprocessSandbox())
    tool = CodeSearchTool()
    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="a1",
        backend=ws,
        user_id="u1",
    )
    result = await tool.execute({"query": "ApprovalGate check"}, ctx)
    assert result.success
    assert "sample.py" in result.output
    assert "score=" in result.output


@pytest.mark.asyncio
async def test_ensure_code_index_is_incremental(sample_py: Path):
    ws = ServerWorkspace(root=sample_py, sandbox=SubprocessSandbox())
    manager = IndexManager.for_workspace_root(str(sample_py))

    assert await manager.ensure_index(ws) is True
    assert await manager.ensure_index(ws) is False

    py_file = sample_py / "pkg" / "sample.py"
    py_file.write_text(py_file.read_text() + "\n# touch\n", encoding="utf-8")
    assert await manager.ensure_index(ws) is True


@pytest.mark.asyncio
async def test_local_workspace_code_search_via_channel(sample_py: Path, tmp_path: Path, monkeypatch):
    """Cloud→desktop LocalWorkspace indexes via channel reads (not a disk stub)."""
    from agentcore.config import settings
    from agentcore.workspace.channel import WorkspaceOp
    from agentcore.workspace.local import LocalWorkspace

    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))

    files = {
        "pkg/sample.py": (sample_py / "pkg" / "sample.py").read_text(encoding="utf-8"),
    }

    class _FakeChannel:
        root_id = "root-local-test"

        async def request(self, op, args, *, timeout=None, root_id=None):
            _ = (timeout, root_id)
            if op == WorkspaceOp.INDEX_FILES:
                return {"paths": list(files), "truncated": False}
            if op == WorkspaceOp.READ:
                path = str(args["path"]).replace("\\", "/").lstrip("./")
                if path not in files:
                    from agentcore.workspace.protocol import PathNotFound

                    raise PathNotFound(path)
                return files[path]
            raise AssertionError(f"unexpected op {op}")

    ws = LocalWorkspace(_FakeChannel(), root_label="proj")
    assert await ws.ensure_code_index() is True
    result = await ws.code_search("ApprovalGate check", max_results=5)
    assert result.chunks
    assert any("sample.py" in c.path for c in result.chunks)
    assert result.index_stale is False


@pytest.mark.asyncio
async def test_code_search_requires_query(sample_py: Path):
    ws = ServerWorkspace(root=sample_py, sandbox=SubprocessSandbox())
    tool = CodeSearchTool()
    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="a1",
        backend=ws,
        user_id="u1",
    )
    result = await tool.execute({"query": ""}, ctx)
    assert not result.success
    assert "query" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_code_search_empty_is_success_with_next_steps(sample_py: Path):
    ws = ServerWorkspace(root=sample_py, sandbox=SubprocessSandbox())
    tool = CodeSearchTool()
    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="a1",
        backend=ws,
        user_id="u1",
    )
    result = await tool.execute({"query": "zzz_definitely_missing_symbol"}, ctx)
    assert result.success
    assert result.metadata["match_count"] == 0
    assert "可执行下一步" in result.output
    assert "grep" in result.output
    assert "zzz_definitely_missing_symbol" in result.output


def test_tokenize_query_keeps_identifiers_and_splits_cjk_latin():
    from agentcore.workspace.indexing.bm25 import tokenize_query

    assert "check_approval" in tokenize_query("check_approval")
    assert "ApprovalGate" in tokenize_query("ApprovalGate")
    mixed = tokenize_query("审批门控ApprovalGate")
    assert "ApprovalGate" in mixed
    assert any("审批" in t or t.startswith("审") for t in mixed)
    # Adjacent CJK+Latin must not glue into one token.
    assert "审批门控ApprovalGate" not in mixed


@pytest.mark.asyncio
async def test_symbol_column_ranks_above_body_only_hit(tmp_path: Path):
    """Symbol-field hits should outrank content-only mentions of the same token."""
    from agentcore.workspace.indexing.bm25 import BM25Index
    from agentcore.workspace.indexing.chunker import RawChunk

    db = tmp_path / "idx.db"
    index = BM25Index(str(db))
    await index.upsert_file(
        "sym.py",
        "class ApprovalGate:\n    pass\n",
        [
            RawChunk(
                path="sym.py",
                symbol="ApprovalGate",
                symbol_type="class",
                start_line=1,
                end_line=2,
                language="python",
                content="class ApprovalGate:\n    pass\n",
            )
        ],
    )
    await index.upsert_file(
        "body.py",
        "# see ApprovalGate elsewhere\n",
        [
            RawChunk(
                path="body.py",
                symbol="helper",
                symbol_type="function",
                start_line=1,
                end_line=1,
                language="python",
                content="# see ApprovalGate elsewhere\n",
            )
        ],
    )
    hits = await index.search("ApprovalGate", limit=5)
    assert hits
    assert hits[0][0].path == "sym.py"
    assert hits[0][0].symbol == "ApprovalGate"

"""Tests for LocalWorkspace subpath scoping (工作区对称化 D1a).

When bound to a sub-directory under a shared container root, every op path is
prefixed on the way to the desktop and stripped on the way back, so the
engine/tools/user only see workspace-relative paths. Unscoped (``base=""``) is a
pure pass-through (regression guard for root-bound local projects).
"""

import asyncio

import pytest

from agentcore.runtime.events import EventSink, SSEEvent
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.workspace.channel import WorkspaceChannel
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.protocol import GrepQuery

pytestmark = pytest.mark.anyio

CONV = "conv-1"
ROOT_ID = "root-abc"


def _make(base: str = "") -> tuple[LocalWorkspace, InteractionRegistry, EventSink]:
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=5.0,
        root_id=ROOT_ID,
    )
    return LocalWorkspace(channel, base_subpath=base), registry, sink


async def _await_request(sink: EventSink) -> SSEEvent:
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001 - test-only inspection
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no workspace_op_required event emitted")


async def _round_trip(coro, sink, registry, response: dict):
    task = asyncio.create_task(coro)
    event = await _await_request(sink)
    assert registry.resolve(event.payload["request_id"], response, conversation_id=CONV)
    return await task, event


async def test_scoped_read_prefixes_subpath():
    local, registry, sink = _make(base="proj")
    _, event = await _round_trip(local.read("a.txt"), sink, registry, {"ok": True, "value": "hi"})
    assert event.payload["args"]["path"] == "proj/a.txt"


async def test_scoped_write_and_move_prefix_paths():
    local, registry, sink = _make(base="proj")
    _, ew = await _round_trip(
        local.write("out.txt", "data"), sink, registry, {"ok": True, "value": 4}
    )
    assert ew.payload["args"]["path"] == "proj/out.txt"
    _, em = await _round_trip(
        local.move("a.txt", "b.txt"), sink, registry, {"ok": True, "value": None}
    )
    assert em.payload["args"] == {"src": "proj/a.txt", "dst": "proj/b.txt"}


async def test_scoped_list_prefixes_dir_and_strips_results():
    local, registry, sink = _make(base="proj")
    response = {
        "ok": True,
        "value": [
            {"path": "proj/src", "is_dir": True},
            {"path": "proj/src/main.py", "is_dir": False},
        ],
    }
    entries, event = await _round_trip(local.list(".", "*"), sink, registry, response)
    assert event.payload["args"]["directory"] == "proj"
    assert [(e.path, e.is_dir) for e in entries] == [
        ("src", True),
        ("src/main.py", False),
    ]


async def test_scoped_index_files_sends_base_and_strips():
    local, registry, sink = _make(base="proj")
    response = {
        "ok": True,
        "value": {"paths": ["proj/a.txt", "proj/sub/b.md"], "truncated": False},
    }
    (paths, _), event = await _round_trip(local.index_files(), sink, registry, response)
    assert event.payload["args"]["base"] == "proj"
    assert paths == ["a.txt", "sub/b.md"]


async def test_scoped_grep_prefixes_dir_and_strips_hits():
    local, registry, sink = _make(base="proj")
    response = {
        "ok": True,
        "value": {
            "hits": [{"path": "proj/a.py", "line_no": 3, "text": "x"}],
            "file_counts": [["proj/a.py", 1]],
            "total_matches": 1,
            "truncated": False,
        },
    }
    result, event = await _round_trip(local.grep(GrepQuery(pattern="x")), sink, registry, response)
    assert event.payload["args"]["directory"] == "proj"
    assert result.hits[0].path == "a.py"
    assert result.file_counts == [("a.py", 1)]


async def test_scoped_execute_sends_cwd_subpath():
    local, registry, sink = _make(base="proj")
    response = {
        "ok": True,
        "value": {
            "success": True,
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 1,
        },
    }
    _, event = await _round_trip(
        local.execute(ExecutionRequest(code="print(1)", language="python")),
        sink,
        registry,
        response,
    )
    assert event.payload["args"]["cwd"] == "proj"


async def test_unscoped_is_pure_passthrough():
    """base="" → no prefix / no strip (existing root-bound local projects unchanged)."""
    local, registry, sink = _make()
    _, read_ev = await _round_trip(local.read("a.txt"), sink, registry, {"ok": True, "value": "x"})
    assert read_ev.payload["args"]["path"] == "a.txt"
    response = {"ok": True, "value": {"paths": ["a.txt", "sub/b.md"], "truncated": False}}
    (paths, _), idx_ev = await _round_trip(local.index_files(), sink, registry, response)
    assert idx_ev.payload["args"]["base"] == "."
    assert paths == ["a.txt", "sub/b.md"]

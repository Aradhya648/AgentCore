"""Tests for the local-workspace op channel (双模式工作区 P2a).

Covers the three pieces that make "one agent loop, two execution platforms" work
for local mode, without an actual desktop:

  * ``InteractionRegistry`` — the in-process bridge: unknown / double / wrong-
    conversation resolves are refused; a matching resolve settles the Future.
  * ``WorkspaceChannel`` — suspends an op on a Future, emits a
    ``workspace_op_required`` event carrying the *full* args, and returns the
    desktop's value or re-raises the typed ``WorkspaceError`` (timeout → IO error).
  * ``LocalWorkspace`` — read/list/grep round-trip through the channel and parse
    back into the same typed shapes ``ServerWorkspace`` returns, and a mutating op
    flips ``dirty`` while a read-only op does not.

A fake "desktop" drives each round trip: it reads the emitted op event off the
sink to learn the ``request_id``, then settles the registry with a canned result.
"""

import asyncio

import pytest

from agentcore.runtime.events import EventSink, EventType, SSEEvent
from agentcore.runtime.interaction import InteractionKind, InteractionRegistry
from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.protocol import (
    AmbiguousMatch,
    GrepQuery,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceIOError,
)

pytestmark = pytest.mark.anyio

CONV = "conv-1"


# --- helpers ---------------------------------------------------------------


ROOT_ID = "root-abc"


def _make(
    timeout: float = 5.0, *, execute_slack: float = 15.0
) -> tuple[LocalWorkspace, InteractionRegistry, EventSink]:
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=timeout,
        root_id=ROOT_ID,
    )
    return (
        LocalWorkspace(channel, execute_timeout_slack=execute_slack),
        registry,
        sink,
    )


async def _await_request(sink: EventSink) -> SSEEvent:
    """Return the op event the channel just emitted (yielding so the op runs)."""
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001 - test-only inspection
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no workspace_op_required event emitted")


async def _round_trip(coro, sink: EventSink, registry: InteractionRegistry, response: dict):
    """Drive one op: start it, answer it as the desktop would, return (result, event)."""
    task = asyncio.create_task(coro)
    event = await _await_request(sink)
    assert registry.resolve(event.payload["request_id"], response, conversation_id=CONV)
    return await task, event


# --- LocalWorkspace read-only ops (the P2a "打通") --------------------------


async def test_read_round_trips_through_channel():
    local, registry, sink = _make()
    result, event = await _round_trip(
        local.read("a.txt"), sink, registry, {"ok": True, "value": "hello"}
    )
    assert result == "hello"
    assert event.type == EventType.WORKSPACE_OP_REQUIRED
    assert event.payload["op"] == WorkspaceOp.READ
    assert event.payload["args"] == {"path": "a.txt"}
    assert event.payload["conversation_id"] == CONV
    assert event.payload["root_id"] == ROOT_ID
    # A read must not mark the workspace dirty (no end-of-turn snapshot for it).
    assert local.dirty is False


async def test_list_parses_dir_entries():
    local, registry, sink = _make()
    response = {
        "ok": True,
        "value": [
            {"path": "src", "is_dir": True},
            {"path": "src/main.py", "is_dir": False},
        ],
    }
    entries, _ = await _round_trip(local.list(".", "*"), sink, registry, response)
    assert [(e.path, e.is_dir) for e in entries] == [
        ("src", True),
        ("src/main.py", False),
    ]


async def test_index_files_parses_paths_and_truncation():
    local, registry, sink = _make()
    response = {"ok": True, "value": {"paths": ["a.txt", "sub/b.md"], "truncated": True}}
    (paths, truncated), event = await _round_trip(
        local.index_files(order="recent"), sink, registry, response
    )
    assert event.payload["op"] == WorkspaceOp.INDEX_FILES
    assert event.payload["args"]["order"] == "recent"  # sort preference reaches desktop
    assert paths == ["a.txt", "sub/b.md"]
    assert truncated is True
    # Indexing is read-only — it must not schedule an end-of-turn snapshot.
    assert local.dirty is False


async def test_index_files_tolerates_empty_envelope():
    local, registry, sink = _make()
    # A not-yet-promoted / empty workspace answers with a bare ok — degrade to ([], False).
    (paths, truncated), _ = await _round_trip(local.index_files(), sink, registry, {"ok": True})
    assert paths == [] and truncated is False


async def test_grep_parses_result():
    local, registry, sink = _make()
    response = {
        "ok": True,
        "value": {
            "hits": [{"path": "a.py", "line_no": 3, "text": "import os"}],
            "file_counts": [["a.py", 1]],
            "total_matches": 1,
            "truncated": False,
        },
    }
    result, event = await _round_trip(
        local.grep(GrepQuery(pattern="import")), sink, registry, response
    )
    assert event.payload["op"] == WorkspaceOp.GREP
    assert result.total_matches == 1
    assert result.hits[0].path == "a.py"
    assert result.hits[0].line_no == 3
    assert result.file_counts == [("a.py", 1)]


# --- mutating ops route too (skeleton complete; dirty + full args) ----------


async def test_write_marks_dirty_and_sends_full_content():
    local, registry, sink = _make()
    big = "x" * 5000  # full payload, NOT a bounded preview like approvals
    result, event = await _round_trip(
        local.write("out.txt", big), sink, registry, {"ok": True, "value": 5000}
    )
    assert result == 5000
    assert event.payload["args"]["content"] == big
    assert local.dirty is True


async def test_execute_parses_result_and_marks_dirty():
    local, registry, sink = _make()
    response = {
        "ok": True,
        "value": {
            "success": True,
            "stdout": "hi\n",
            "stderr": "",
            "exit_code": 0,
            "duration_ms": 12,
        },
    }
    req = ExecutionRequest(code="print('hi')", language="python")
    result, event = await _round_trip(local.execute(req), sink, registry, response)
    assert event.payload["op"] == WorkspaceOp.EXECUTE
    assert result.success and result.stdout == "hi\n"
    assert local.dirty is True


async def test_execute_forwards_registry_env():
    local, registry, sink = _make()
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
    req = ExecutionRequest(
        code="print(1)",
        language="python",
        env={"NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/", "SECRET": "no"},
    )
    _result, event = await _round_trip(local.execute(req), sink, registry, response)
    assert event.payload["args"]["env"]["NPM_CONFIG_REGISTRY"].startswith("https://")
    assert event.payload["args"]["env"]["SECRET"] == "no"


# --- typed error mapping (the tool layer must see the same exceptions) ------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("PathNotFound", PathNotFound),
        ("OutsideWorkspace", OutsideWorkspace),
        ("WorkspaceIOError", WorkspaceIOError),
        ("SomethingUnknown", WorkspaceIOError),  # degrade unknown → generic IO
    ],
)
async def test_error_kind_maps_to_typed_exception(kind: str, expected: type):
    local, registry, sink = _make()
    response = {"ok": False, "error": {"kind": kind, "detail": "boom"}}
    with pytest.raises(expected):
        await _round_trip(local.read("x"), sink, registry, response)


async def test_ambiguous_match_carries_count():
    local, registry, sink = _make()
    response = {"ok": False, "error": {"kind": "AmbiguousMatch", "count": 4}}
    with pytest.raises(AmbiguousMatch) as ei:
        await _round_trip(local.replace("a.py", "x", "y", all_=False), sink, registry, response)
    assert ei.value.count == 4


async def test_malformed_envelope_raises_io_error():
    local, registry, sink = _make()
    with pytest.raises(WorkspaceIOError):
        await _round_trip(local.read("x"), sink, registry, {"unexpected": True})


# --- timeout (a dropped desktop never hangs the turn) ----------------------


async def test_timeout_raises_io_error():
    local, _registry, _sink = _make(timeout=0.05)
    # No desktop answers, so the op times out and surfaces as a WorkspaceIOError.
    with pytest.raises(WorkspaceIOError, match="活性挂起"):
        await local.read("never-answered.txt")


async def test_after_timeout_second_request_fail_fast():
    """Sticky channel-dead: a follow-up op must not wait another full deadline."""
    local, _registry, _sink = _make(timeout=2.0)
    with pytest.raises(WorkspaceIOError, match="活性挂起"):
        await local.read("never-answered.txt")

    t0 = asyncio.get_running_loop().time()
    with pytest.raises(WorkspaceIOError, match="channel dead.*活性挂起"):
        await local.read("also-never.txt")
    elapsed = asyncio.get_running_loop().time() - t0
    # Fail-fast: far shorter than the 2s channel timeout (no SSE / no suspend).
    assert elapsed < 0.2


async def test_probe_exec_timeout_does_not_sticky_dead_channel():
    """A1: language probe hang fail-closes advertise only — file channel stays alive."""
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=0.05,
        root_id=ROOT_ID,
    )
    with pytest.raises(WorkspaceIOError, match="probe_exec.*活性挂起"):
        await channel.request(WorkspaceOp.PROBE_EXEC, {})

    assert channel._dead is False  # noqa: SLF001
    # Drain the unanswered probe SSE so the next await sees the file op.
    while not sink._queue.empty():  # noqa: SLF001
        sink._queue.get_nowait()

    # A real file op must still emit SSE (not reject as channel dead).
    task = asyncio.create_task(channel.request(WorkspaceOp.READ, {"path": "a.txt"}))
    event = await _await_request(sink)
    assert event.payload["op"] == "read"
    assert registry.resolve(
        event.payload["request_id"],
        {"ok": True, "value": "alive"},
        conversation_id=CONV,
    )
    assert await task == "alive"


async def test_parallel_ops_one_timeout_fails_sibling_as_channel_dead():
    """First liveness hang settles same-channel inflight without burning deadline."""
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        # Floor is max(1.0, …) in derive_channel_timeout — use 1s vs 5s contrast.
        timeout_seconds=1.0,
        root_id=ROOT_ID,
    )
    # Short (channel default) vs long: A hangs first; B must not burn its 5s budget.
    t_a = asyncio.create_task(channel.request(WorkspaceOp.READ, {"path": "a.txt"}))
    t_b = asyncio.create_task(
        channel.request(WorkspaceOp.READ, {"path": "b.txt"}, timeout=5.0)
    )
    await _await_request(sink)
    await _await_request(sink)

    t0 = asyncio.get_running_loop().time()
    results = await asyncio.gather(t_a, t_b, return_exceptions=True)
    elapsed = asyncio.get_running_loop().time() - t0

    assert all(isinstance(r, WorkspaceIOError) for r in results)
    details = [str(r) for r in results]
    assert any("timed out" in d and "活性挂起" in d for d in details)
    assert any("channel dead" in d and "活性挂起" in d for d in details)
    # Sibling had a 5s budget — channel-dead settle must finish near A's 1s hang.
    assert elapsed < 2.0


async def test_channel_caps_concurrent_suspends():
    """At most max_inflight ops may be suspended; extras wait for a slot."""
    sink = EventSink()
    registry = InteractionRegistry()
    cap = 2
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=5.0,
        root_id=ROOT_ID,
        max_inflight=cap,
    )
    tasks = [
        asyncio.create_task(channel.request(WorkspaceOp.READ, {"path": f"{i}.txt"}))
        for i in range(cap + 2)
    ]
    # Pump until the first wave emits; the overflow must not emit yet.
    events: list[SSEEvent] = []
    for _ in range(200):
        while not sink._queue.empty():  # noqa: SLF001
            events.append(sink._queue.get_nowait())
        if len(events) >= cap:
            break
        await asyncio.sleep(0)
    assert len(events) == cap
    assert len(channel._inflight) == cap  # noqa: SLF001
    await asyncio.sleep(0)
    assert sink._queue.empty()  # noqa: SLF001

    # Release one slot → a parked waiter suspends and emits.
    assert registry.resolve(
        events[0].payload["request_id"], {"ok": True, "value": "a"}, conversation_id=CONV
    )
    third = await _await_request(sink)
    assert third.payload["args"]["path"] in {f"{i}.txt" for i in range(cap + 2)}

    # Settle every remaining suspended op (wave 1 leftover + newly admitted).
    to_settle = [events[1], third]
    for _ in range(100):
        while not sink._queue.empty():  # noqa: SLF001
            to_settle.append(sink._queue.get_nowait())
        progressed = False
        for ev in list(to_settle):
            if registry.resolve(
                ev.payload["request_id"], {"ok": True, "value": "x"}, conversation_id=CONV
            ):
                to_settle.remove(ev)
                progressed = True
        if all(t.done() for t in tasks):
            break
        if not progressed:
            await asyncio.sleep(0)
    results = await asyncio.gather(*tasks)
    assert len(results) == cap + 2
    assert all(r in ("a", "x") for r in results)


async def test_queued_waiter_fail_fast_after_channel_dead():
    """After sticky-dead, a queued waiter that obtains a slot fail-fasts (no SSE)."""
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=1.0,
        root_id=ROOT_ID,
        max_inflight=1,
    )
    # Fill the only slot; leave it hanging so the next caller queues.
    t_hold = asyncio.create_task(channel.request(WorkspaceOp.READ, {"path": "hold.txt"}))
    await _await_request(sink)
    t_queued = asyncio.create_task(channel.request(WorkspaceOp.READ, {"path": "queued.txt"}))
    # Queued task parks on the semaphore — no second SSE while hold is open.
    for _ in range(50):
        await asyncio.sleep(0)
    assert sink._queue.empty()  # noqa: SLF001

    t0 = asyncio.get_running_loop().time()
    results = await asyncio.gather(t_hold, t_queued, return_exceptions=True)
    elapsed = asyncio.get_running_loop().time() - t0

    assert all(isinstance(r, WorkspaceIOError) for r in results)
    details = [str(r) for r in results]
    assert any("timed out" in d and "活性挂起" in d for d in details)
    assert any("channel dead" in d and "活性挂起" in d for d in details)
    # Queued waiter fail-fasts after hold's ~1s hang — not another full deadline.
    assert elapsed < 2.0
    # No workspace_op_required for the queued op.
    assert sink._queue.empty()  # noqa: SLF001


# --- per-op transport deadline (执行门 timeout policy) ----------------------
#
# A code execution must NOT be cut off by the flat file-op deadline: its transport
# deadline is (the code's own timeout + slack), so the desktop's execution limit
# stays authoritative. File ops keep the flat channel deadline. We assert the exact
# deadline handed to asyncio.wait_for (spying on it inside the channel module).


def _spy_wait_for(monkeypatch) -> list[float]:
    """Record every timeout asyncio.wait_for is called with for an op.

    The create→emit→wait→discard suspend dance now lives in the unified
    InteractionRegistry (runtime.interaction), so the channel forwards its per-op
    deadline to ``registry.suspend`` which awaits there — patch that seam."""
    captured: list[float] = []
    real_wait_for = asyncio.wait_for

    async def spy(fut, timeout):  # noqa: ANN001 - duck-typed shim
        captured.append(timeout)
        return await real_wait_for(fut, timeout)

    monkeypatch.setattr("agentcore.runtime.interaction.asyncio.wait_for", spy)
    return captured


async def test_file_op_uses_flat_transport_deadline(monkeypatch):
    captured = _spy_wait_for(monkeypatch)
    local, registry, sink = _make(timeout=30.0, execute_slack=15.0)
    await _round_trip(local.read("a.txt"), sink, registry, {"ok": True, "value": "x"})
    # A read rides the channel-wide deadline, untouched by the execute slack.
    assert captured[-1] == 30.0


async def test_execute_extends_transport_deadline_past_code_timeout(monkeypatch):
    captured = _spy_wait_for(monkeypatch)
    local, registry, sink = _make(timeout=30.0, execute_slack=15.0)
    req = ExecutionRequest(code="print(1)", language="python", timeout_seconds=10)
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
    await _round_trip(local.execute(req), sink, registry, response)
    # code timeout (10) + slack (15) — NOT the flat 30s file-op deadline.
    assert captured[-1] == 25.0


# --- registry guards (defense in depth on the resolve endpoint) ------------


async def test_registry_refuses_unknown_and_double_and_wrong_conversation():
    registry = InteractionRegistry()
    fut = registry.create("req-1", CONV, kind=InteractionKind.CLIENT_TOOL)

    assert registry.resolve("nope", {"ok": True}, conversation_id=CONV) is False
    assert registry.resolve("req-1", {"ok": True}, conversation_id="other") is False
    assert fut.done() is False  # wrong conversation must not settle it

    assert registry.resolve("req-1", {"ok": True, "value": 1}, conversation_id=CONV) is True
    assert registry.resolve("req-1", {"ok": True}, conversation_id=CONV) is False  # double
    assert (await fut)["value"] == 1

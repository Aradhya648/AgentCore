"""Integration tests for the re-attach stream endpoint (执行与请求解耦 C1 · slice 1b).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers auth, ownership (IDOR), the 204 "nothing live" fallback, and the core
replay-then-tail behaviour against a stand-in detached run registered directly in
the ``TurnRunRegistry`` (the full SSE turn is exercised elsewhere) — so this
isolates the route + ``EventSink.take_over`` contract: a re-attaching client
replays the transcript so far, then follows new events live.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import uvicorn

from agentcore.main import app
from agentcore.runtime.events import EventSink, content_delta
from agentcore.runtime.turn_runs import turn_runs
from tests.integration.conftest import register_and_login


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _never() -> None:
    await asyncio.Event().wait()


async def _read_until(lines: AsyncIterator[str], needle: str, timeout: float = 3.0) -> str:
    """Accumulate SSE lines from a shared ``resp.aiter_lines()`` iterator until
    ``needle`` appears, or fail on timeout. Takes the iterator (not the response) so
    repeated calls keep draining the *same* stream — re-iterating a real network
    response raises httpx.StreamConsumed (the in-memory ASGITransport tolerates it)."""
    acc = ""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while needle not in acc:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for {needle!r}; got: {acc!r}")
        line = await asyncio.wait_for(lines.__anext__(), timeout=remaining)
        acc += f"{line}\n"
    return acc


@pytest_asyncio.fixture
async def live_server(session_factory):
    """A real uvicorn server on an ephemeral localhost port, sharing this test's event
    loop so ``session_factory``'s get_db override + its engine stay valid and the
    in-test ``EventSink`` queue lives on the same loop the request handler drains.

    Why a live server: the attach stream test needs a *real* TCP disconnect. The
    in-memory ASGITransport the other tests use never delivers http.disconnect, so
    leaving an infinite SSE tail there deadlocks the stream exit; closing a real socket
    makes uvicorn cancel the attach generator for real.

    ``lifespan="off"`` matches what every other integration test already gets — the
    ASGITransport ``client`` never runs lifespan either — and the attach route needs
    only routing + get_db + the in-memory registry, not the boot probes / sweep loops.
    Crucially it also avoids ``setup_logging()`` (lifespan's first line) re-binding
    structlog mid-suite, which would otherwise strand capsys-based logging assertions
    in later tests.
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    # serve() runs as a task on this loop, so don't let it install process signal
    # handlers (main-thread-only, and they'd fight pytest's own).
    server.install_signal_handlers = lambda: None
    serve_task = asyncio.create_task(server.serve())
    try:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 15.0
        while not server.started:
            if loop.time() > deadline:
                raise RuntimeError("live server did not start within 15s")
            await asyncio.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(serve_task, timeout=10.0)


@pytest_asyncio.fixture
async def live_client(live_server):
    """An httpx client bound to the live uvicorn server (real sockets, real
    disconnect), not the in-memory ASGITransport."""
    async with httpx.AsyncClient(base_url=live_server) as c:
        yield c


async def test_attach_requires_auth(client):
    cid = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/v1/conversations/{cid}/stream")).status_code == 401


async def test_attach_204_when_no_run(client):
    await register_and_login(client, "attachidle")
    conv = await _new_conversation(client, "idle")

    # No live run → 204, so the client falls back to the persisted transcript.
    r = await client.get(f"/v1/conversations/{conv}/stream")
    assert r.status_code == 204, r.text


# Runs against a real uvicorn live server (see ``live_server``) rather than the
# in-memory ASGITransport: this is the one attach case that needs a genuine TCP
# disconnect, which ASGITransport can't model (it never sends http.disconnect, so the
# infinite SSE tail would deadlock the stream exit). A real socket close lets uvicorn
# cancel the attach generator for real — the production path.
async def test_attach_replays_history_then_tails(live_client):
    await register_and_login(live_client, "attachlive")
    conv = await _new_conversation(live_client, "live")

    # Stand-in detached run with some transcript already accumulated.
    sink = EventSink()
    sink.emit(content_delta("ALPHA"))  # emitted before any consumer → replayed
    task = asyncio.create_task(_never())
    turn_runs.register(conversation_id=conv, task=task, sink=sink)
    try:
        async with live_client.stream("GET", f"/v1/conversations/{conv}/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = resp.aiter_lines()  # one shared iterator (real streams consume once)
            # Replay: the pre-attach transcript arrives first.
            await _read_until(lines, "ALPHA")
            # Tail: an event emitted after re-attach streams live to this consumer.
            sink.emit(content_delta("BRAVO"))
            await _read_until(lines, "BRAVO")
        # Exiting the stream closes the real TCP connection, so uvicorn delivers
        # http.disconnect and the attach generator detaches the sink — it never cancels
        # the run (that stays an explicit POST .../stop). This is the genuine disconnect
        # path the in-memory ASGITransport can't reproduce.
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    # Dropping the attach stream is a pure detach — it never cancelled the run via
    # this path (the registry slot was only cleared by our explicit cancel above).
    assert turn_runs.get(conv) is None


async def test_attach_rejects_non_owner(client, new_client):
    await register_and_login(client, "attachowner")
    conv = await _new_conversation(client, "mine")

    async with new_client() as other:
        await register_and_login(other, "attachintruder")
        assert (await other.get(f"/v1/conversations/{conv}/stream")).status_code == 404

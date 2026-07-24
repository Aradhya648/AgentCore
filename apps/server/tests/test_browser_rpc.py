"""D9 stdio JSON-RPC channel: codec + request/response matching + failure modes."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from agentcore.tools.sandbox.browser.rpc import (
    READY_ID,
    RpcChannelClosedError,
    RpcTimeoutError,
    StdioRpcChannel,
    decode_line,
    encode_request,
    extract_frame,
)


def test_encode_request_merges_args_at_top_level():
    line = encode_request(7, "navigate", {"url": "https://x/"})
    obj = json.loads(line)
    assert obj == {"id": 7, "cmd": "navigate", "url": "https://x/"}
    assert line.endswith(b"\n")


def test_decode_line_rejects_non_object():
    assert decode_line('{"id": 1}') == {"id": 1}
    with pytest.raises(Exception):
        decode_line("[1,2,3]")


def test_extract_frame_pops_and_decodes():
    raw = b"\xff\xd8jpeg-bytes"
    resp = {"id": 1, "ok": True, "frame_b64": base64.b64encode(raw).decode()}
    frame = extract_frame(resp)
    assert frame == raw
    assert "frame_b64" not in resp  # popped so it never bloats the model-facing data
    assert extract_frame({"id": 1, "ok": True}) is None


class _EchoTransport:
    """Fake stdio: replies to each request with a matching-id OK line; pre-queues ready."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[bytes] = asyncio.Queue()
        self.written: list[bytes] = []
        self.inbox.put_nowait(b'{"id": 0, "event": "ready", "ok": true}\n')

    async def write(self, data: bytes) -> None:
        self.written.append(data)
        req = json.loads(data)
        await self.inbox.put(
            (json.dumps({"id": req["id"], "ok": True, "echo": req["cmd"]}) + "\n").encode()
        )

    async def readline(self) -> bytes:
        return await self.inbox.get()


@pytest.mark.asyncio
async def test_ready_then_request_roundtrip():
    t = _EchoTransport()
    ch = StdioRpcChannel(write=t.write, readline=t.readline)
    ch.start()
    ready = await ch.wait_ready(timeout=1)
    assert ready["event"] == "ready" and ready.get("id") == READY_ID
    resp = await ch.request("navigate", {"url": "https://x/"}, timeout=1)
    assert resp["ok"] is True and resp["echo"] == "navigate"
    await ch.aclose()


@pytest.mark.asyncio
async def test_concurrent_requests_match_by_id():
    t = _EchoTransport()
    ch = StdioRpcChannel(write=t.write, readline=t.readline)
    ch.start()
    await ch.wait_ready(timeout=1)
    results = await asyncio.gather(
        ch.request("navigate", {}, timeout=1),
        ch.request("snapshot", {}, timeout=1),
        ch.request("screenshot", {}, timeout=1),
    )
    assert sorted(r["echo"] for r in results) == ["navigate", "screenshot", "snapshot"]
    await ch.aclose()


@pytest.mark.asyncio
async def test_eof_fails_pending_with_channel_closed():
    inbox: asyncio.Queue[bytes] = asyncio.Queue()
    inbox.put_nowait(b'{"id": 0, "event": "ready"}\n')

    async def readline() -> bytes:
        return await inbox.get()

    async def write(_data: bytes) -> None:
        await inbox.put(b"")  # EOF right after the request is sent

    ch = StdioRpcChannel(write=write, readline=readline)
    ch.start()
    await ch.wait_ready(timeout=1)
    with pytest.raises(RpcChannelClosedError):
        await ch.request("navigate", {}, timeout=1)


@pytest.mark.asyncio
async def test_request_times_out_when_no_reply():
    inbox: asyncio.Queue[bytes] = asyncio.Queue()
    inbox.put_nowait(b'{"id": 0, "event": "ready"}\n')

    async def readline() -> bytes:
        return await inbox.get()

    async def write(_data: bytes) -> None:
        pass  # driver wedged: never replies

    ch = StdioRpcChannel(write=write, readline=readline)
    ch.start()
    await ch.wait_ready(timeout=1)
    with pytest.raises(RpcTimeoutError):
        await ch.request("navigate", {}, timeout=0.05)
    await ch.aclose()


# -- M1 (D14): driver-initiated event lines (live_frame) route to a handler ------------


@pytest.mark.asyncio
async def test_driver_event_routes_to_handler_and_reply_still_matches():
    """A ``live_frame`` event line goes to on_event; the id-matched reply still resolves."""
    inbox: asyncio.Queue[bytes] = asyncio.Queue()
    inbox.put_nowait(b'{"id": 0, "event": "ready", "ok": true}\n')
    got = asyncio.Event()
    events: list[dict] = []

    def on_event(msg: dict) -> None:
        events.append(msg)
        got.set()

    async def readline() -> bytes:
        return await inbox.get()

    async def write(data: bytes) -> None:
        req = json.loads(data)
        # Interleave a driver event BEFORE the matching reply — both must be handled.
        await inbox.put(b'{"event": "live_frame", "frame_b64": "Zg==", "width": 10, "height": 20}\n')
        await inbox.put((json.dumps({"id": req["id"], "ok": True, "echo": req["cmd"]}) + "\n").encode())

    ch = StdioRpcChannel(write=write, readline=readline, on_event=on_event)
    ch.start()
    await ch.wait_ready(timeout=1)
    resp = await ch.request("navigate", {}, timeout=1)
    await asyncio.wait_for(got.wait(), 1)
    assert resp["ok"] is True and resp["echo"] == "navigate"
    assert events and events[0]["event"] == "live_frame" and events[0]["frame_b64"] == "Zg=="
    await ch.aclose()


@pytest.mark.asyncio
async def test_ready_never_reaches_the_event_handler():
    """The ``ready`` handshake resolves wait_ready and must NOT be delivered as an event."""
    inbox: asyncio.Queue[bytes] = asyncio.Queue()
    inbox.put_nowait(b'{"id": 0, "event": "ready", "ok": true}\n')
    events: list[dict] = []

    async def readline() -> bytes:
        return await inbox.get()

    async def write(_data: bytes) -> None:
        pass

    ch = StdioRpcChannel(write=write, readline=readline, on_event=events.append)
    ch.start()
    await ch.wait_ready(timeout=1)
    await asyncio.sleep(0.02)
    assert events == []
    await ch.aclose()


@pytest.mark.asyncio
async def test_event_handler_error_does_not_break_the_channel():
    """A raising on_event must not desync / kill the read loop — later replies still work."""
    inbox: asyncio.Queue[bytes] = asyncio.Queue()
    inbox.put_nowait(b'{"id": 0, "event": "ready", "ok": true}\n')

    def boom(_msg: dict) -> None:
        raise RuntimeError("handler blew up")

    async def readline() -> bytes:
        return await inbox.get()

    async def write(data: bytes) -> None:
        req = json.loads(data)
        await inbox.put(b'{"event": "live_frame", "frame_b64": "x"}\n')  # triggers boom
        await inbox.put((json.dumps({"id": req["id"], "ok": True}) + "\n").encode())

    ch = StdioRpcChannel(write=write, readline=readline, on_event=boom)
    ch.start()
    await ch.wait_ready(timeout=1)
    resp = await ch.request("ping", {}, timeout=1)
    assert resp["ok"] is True
    await ch.aclose()

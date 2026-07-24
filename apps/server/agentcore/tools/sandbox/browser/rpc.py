"""Newline-delimited JSON-RPC over the sandbox's stdio (D9 control channel).

Split into a pure codec (testable without I/O) and an async channel that owns the
request-id matching, the ``ready`` handshake, per-command timeouts, and
channel-death detection. The channel talks to any ``readline`` / ``write`` pair —
in production the runsc process's stdout/stdin streams, in tests an in-memory
fake — so the whole protocol layer is unit-testable off Linux / without gVisor.

Frames (base64 jpeg keyframes) ride the same line as their JSON reply, so the
stream reader must be created with a large line limit (see ``gvisor_session``).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import Awaitable, Callable

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# Sentinel id the driver emits once on startup before accepting commands.
READY_ID = 0


class RpcError(Exception):
    """Base for RPC transport failures."""


class RpcChannelClosedError(RpcError):
    """The underlying stdio stream hit EOF / broke — every pending call fails with this."""


class RpcTimeoutError(RpcError):
    """A command did not get its reply within the deadline (driver wedged)."""


def encode_request(rid: int, action: str, args: dict | None) -> bytes:
    """One request line: ``{"id","cmd",...args}\\n`` (args merged at top level)."""
    payload = {"id": rid, "cmd": action, **(args or {})}
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def decode_line(line: str | bytes) -> dict:
    """Parse one response line into a dict (raise ``RpcError`` on non-object JSON)."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    obj = json.loads(line)
    if not isinstance(obj, dict):
        raise RpcError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


def extract_frame(response: dict) -> bytes | None:
    """Pop a base64 ``frame_b64`` from a decoded response into raw jpeg bytes."""
    b64 = response.pop("frame_b64", None)
    if not b64 or not isinstance(b64, str):
        return None
    try:
        return base64.b64decode(b64)
    except (ValueError, TypeError):
        return None


class StdioRpcChannel:
    """Async request/response over a line-oriented stdio pair.

    ``write`` sends raw bytes (a full request line); ``readline`` returns the next
    response line (empty bytes ⇒ EOF). A single background reader dispatches each
    line to the waiting call by ``id``; the ``ready`` line resolves the handshake.
    """

    def __init__(
        self,
        *,
        write: Callable[[bytes], Awaitable[None]],
        readline: Callable[[], Awaitable[bytes]],
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self._write = write
        self._readline = readline
        # Driver-INITIATED event lines (``{"event": ...}`` with no matching request id,
        # e.g. M1 ``live_frame``) are routed here instead of being dropped. The ``ready``
        # handshake is handled separately and never reaches this callback.
        self._on_event = on_event
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._ready: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._reader_task: asyncio.Task | None = None
        self._closed = False

    def set_event_handler(self, on_event: Callable[[dict], None] | None) -> None:
        """Set/replace the driver-event sink (used to wire live frames post-construction)."""
        self._on_event = on_event

    def start(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._readline()
                if not line:
                    break
                if isinstance(line, bytes):
                    text = line.decode("utf-8", errors="replace").strip()
                else:
                    text = line.strip()
                if not text:
                    continue
                try:
                    msg = decode_line(text)
                except (json.JSONDecodeError, RpcError):
                    # Non-JSON chatter must never desync the channel; drop it.
                    logger.debug("browser.rpc_nonjson", preview=text[:120])
                    continue
                self._dispatch(msg)
        finally:
            self._fail_all(RpcChannelClosedError("driver stdio channel closed"))

    def _dispatch(self, msg: dict) -> None:
        event = msg.get("event")
        if event == "ready":
            if not self._ready.done():
                self._ready.set_result(msg)
            return
        if event is not None:
            # A driver-initiated event (not a reply to a request): route to the handler.
            # A handler error must never desync / kill the read loop.
            if self._on_event is not None:
                try:
                    self._on_event(msg)
                except Exception:  # noqa: BLE001 - observation must not break the channel
                    logger.warning("browser.rpc_event_handler_error", driver_event=str(event))
            return
        rid = msg.get("id")
        fut = self._pending.pop(rid, None) if isinstance(rid, int) else None
        if fut is not None and not fut.done():
            fut.set_result(msg)

    def _fail_all(self, exc: Exception) -> None:
        self._closed = True
        if not self._ready.done():
            self._ready.set_exception(exc)
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def wait_ready(self, timeout: float) -> dict:
        try:
            return await asyncio.wait_for(asyncio.shield(self._ready), timeout)
        except TimeoutError as exc:
            raise RpcTimeoutError("driver did not signal ready in time") from exc

    async def request(self, action: str, args: dict | None, *, timeout: float) -> dict:
        if self._closed:
            raise RpcChannelClosedError("channel already closed")
        rid = self._next_id
        self._next_id += 1
        fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._write(encode_request(rid, action, args))
        except Exception as exc:  # noqa: BLE001 - a write failure is a dead channel
            self._pending.pop(rid, None)
            raise RpcChannelClosedError(f"write failed: {exc}") from exc
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as exc:
            self._pending.pop(rid, None)
            raise RpcTimeoutError(f"command '{action}' timed out after {timeout:g}s") from exc

    async def aclose(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
        self._fail_all(RpcChannelClosedError("channel closed"))

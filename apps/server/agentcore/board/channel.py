"""BoardChannel — route a batch of board ops to the desktop and await the result.

The board counterpart of ``workspace/channel.py``. ``board_ops`` (the server tool)
can't touch the user's whiteboard canvas directly — the canvas lives in the desktop
renderer — so it hands a structured op batch to this channel, which suspends the run
on the unified interaction bridge, emits a ``board_op_required`` SSE event, and awaits
the desktop's reply. The bound desktop converts ops → scene elements, applies them to
the open board, autosaves (CAS), and POSTs the result to the ops-resolve endpoint,
which settles the future.

State is in-process (single-worker posture, same as the approval gate / workspace
channel); front with Redis to scale to multiple workers. A reply the desktop never
delivers fails as a :class:`BoardOpError` after the timeout, so a dropped / closed
canvas never hangs the turn — the tool maps that to an error result the model can
recover from (tell the user, retry, or proceed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.events import EventSink, board_op_required, board_read_required
from agentcore.runtime.events.client_tool_reattach import (
    CHANNEL_BOARD,
    CHANNEL_BOARD_READ,
    client_tool_payload,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.interaction import InteractionKind
from agentcore.runtime.ports import ClientRequestBridge

logger = get_logger(__name__)


class BoardOpError(Exception):
    """A board-op batch failed to apply (desktop error, drop, or timeout).

    Carried back to ``BoardOpsTool``, which turns it into a failed ``ToolResult`` so the
    model learns the ops did NOT land (and can inform the user / retry) rather than
    assuming success.
    """


class BoardReadError(Exception):
    """A board read (rasterize) failed (desktop error, drop, or timeout).

    The read counterpart of :class:`BoardOpError`. Carried back to ``BoardReadTool``,
    which maps it to a failed ``ToolResult`` so the model learns it did NOT get an image
    (and can fall back / retry) instead of inventing what the drawing said.
    """


@dataclass
class BoardChannel:
    """Suspends one board-op batch until the bound desktop applies it.

    One channel per board-bound turn, constructed where the sink + interaction bridge
    are available and bound to one ``board_id``. ``request`` applies an op batch (used by
    ``BoardOpsTool``); ``read`` rasterizes a subset of elements to a PNG (used by
    ``BoardReadTool``, §九). Both ride the same suspend / emit / await mechanism on the
    shared bridge — the tool layer only builds the JSON-safe input and reads the value.
    """

    sink: EventSink
    conversation_id: str
    board_id: str
    registry: ClientRequestBridge
    timeout_seconds: float

    async def request(self, ops: list[dict[str, Any]], *, summary: str = "") -> dict[str, Any]:
        """Emit the op batch, await the desktop's result, and return its ``value``.

        Returns the desktop's structured result (e.g. ``{"applied": n, "created":
        [...ids], "version": v}``) on success. Raises :class:`BoardOpError` on a desktop
        failure, a malformed envelope, or a timeout — never hangs and never leaks an
        untyped error, so the tool's ``except BoardOpError`` is sufficient.
        """
        request_id = new_id()
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_BOARD,
                    EventType.BOARD_OP_REQUIRED.value,
                    params={
                        "board_id": self.board_id,
                        "ops": ops,
                        "summary": summary,
                    },
                ),
                timeout=self.timeout_seconds,
                on_suspended=lambda: self.sink.emit(
                    board_op_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        board_id=self.board_id,
                        ops=ops,
                        summary=summary,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info("board.op_timeout", board_id=self.board_id, request_id=request_id)
            raise BoardOpError("board op batch timed out (画布未响应)") from e

        if not isinstance(result, dict) or not result.get("ok"):
            detail = ""
            if isinstance(result, dict):
                err = result.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("detail", "") or "")
                elif err:
                    detail = str(err)
            raise BoardOpError(detail or "board op batch failed (画布应用失败)")
        value = result.get("value")
        return value if isinstance(value, dict) else {}

    async def read(self, ids: list[str]) -> dict[str, Any]:
        """Ask the desktop to rasterize ``ids`` to a PNG; return its ``value`` (§九).

        Returns the desktop's result (``{"pngBase64": str, "w": int, "h": int}``) on
        success. Raises :class:`BoardReadError` on a desktop failure, a malformed
        envelope, or a timeout — the same never-hang / typed-error contract as
        :meth:`request`, so ``BoardReadTool``'s ``except BoardReadError`` is sufficient.
        """
        request_id = new_id()
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_BOARD_READ,
                    EventType.BOARD_READ_REQUIRED.value,
                    params={"board_id": self.board_id, "ids": ids},
                ),
                timeout=self.timeout_seconds,
                on_suspended=lambda: self.sink.emit(
                    board_read_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        board_id=self.board_id,
                        ids=ids,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info("board.read_timeout", board_id=self.board_id, request_id=request_id)
            raise BoardReadError("board read timed out (画布未响应)") from e

        if not isinstance(result, dict) or not result.get("ok"):
            detail = ""
            if isinstance(result, dict):
                err = result.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("detail", "") or "")
                elif err:
                    detail = str(err)
            raise BoardReadError(detail or "board read failed (画布读取失败)")
        value = result.get("value")
        return value if isinstance(value, dict) else {}

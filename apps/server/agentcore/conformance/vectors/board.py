"""AI collaborative whiteboard (board_ops) conformance scenarios."""

from __future__ import annotations

from collections.abc import Callable

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    board_op_required,
    content_delta,
    message_end,
    message_start,
    reasoning_delta,
    tool_use_end,
    tool_use_start,
)

from ._common import _CONV, _COST

_BOARD_ID = "board_demo"
_REQ_ID = "board-req-1"


def _board_ops_applied() -> list[SSEEvent]:
    """白板会话：CEO 调 board_ops → board_op_required 运输事件 → 工具成功 → 回合收尾。

    ``board_op_required`` is transport-only (desktop applies + settles); it does not
    pause the turn or alter ``ProjectedTurn`` — same no-op fold as ``workspace_op_required``.
    The ``board_ops`` tool step still lands on the captain process timeline."""
    ops = [{"op": "add_node", "ref": "a", "kind": "sticky", "text": "目标"}]
    return [
        message_start("m1", conversation_id=_CONV),
        reasoning_delta("先在白板上摆一个目标便签。"),
        tool_use_start("tc1", "board_ops", {"ops": ops}),
        board_op_required(
            request_id=_REQ_ID,
            conversation_id=_CONV,
            board_id=_BOARD_ID,
            ops=ops,
            summary="已添加目标便签",
        ),
        tool_use_end(
            "tc1",
            "board_ops",
            success=True,
            output='{"applied": 1, "created": ["el-1"], "version": 2}',
        ),
        content_delta("已在白板上添加目标便签。"),
        message_end(FinishReason.END_TURN, input_tokens=1100, output_tokens=120, cost=_COST),
    ]


def _board_ops_tool_failed() -> list[SSEEvent]:
    """白板会话：board_ops 因画布未打开失败 — 工具步仍落在时间线，回合照常收尾。"""
    ops = [{"op": "add_node", "ref": "a", "text": "Hi"}]
    return [
        message_start("m1", conversation_id=_CONV),
        tool_use_start("tc1", "board_ops", {"ops": ops}),
        board_op_required(
            request_id=_REQ_ID,
            conversation_id=_CONV,
            board_id=_BOARD_ID,
            ops=ops,
            summary="",
        ),
        tool_use_end(
            "tc1",
            "board_ops",
            success=False,
            output="画布未打开",
        ),
        content_delta("当前画布未打开，无法作画。"),
        message_end(FinishReason.END_TURN, input_tokens=800, output_tokens=60, cost=_COST),
    ]


VECTORS: dict[str, tuple[str, Callable[[], list[SSEEvent]]]] = {
    "board_ops_applied": (
        "白板：board_ops 成功（board_op_required 运输 + 工具步 + end_turn）",
        _board_ops_applied,
    ),
    "board_ops_tool_failed": (
        "白板：board_ops 画布未打开失败（工具步失败 + 回合仍收尾）",
        _board_ops_tool_failed,
    ),
}

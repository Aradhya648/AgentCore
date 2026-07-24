"""Workspace / whiteboard / desktop client-tool SSE payload wire models
(factories: ``runtime/events/workspace.py`` / ``board.py`` / ``desktop.py``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from agentcore.runtime.events.payloads._base import WirePayload, absent


class WorkspaceOpRequiredPayload(WirePayload):
    """Transport-only client-tool request: apply a workspace file op on the bound
    desktop and POST the result back. NOT journaled."""

    request_id: str
    conversation_id: str
    root_id: str
    op: str
    args: dict[str, Any]


class BoardOp(WirePayload):
    """One structured whiteboard op (AI协作白板 M2). The closed verb set is shared with
    the server tool + the desktop applier; fields beyond `op` are op-specific."""

    op: Literal["add_node", "connect", "move", "set_text", "delete", "group"]
    ref: str | None = absent()
    id: str | None = absent()
    kind: Literal["sticky", "rectangle", "ellipse", "diamond", "text"] | None = absent()
    text: str | None = absent()
    x: float | None = absent()
    y: float | None = absent()
    width: float | None = absent()
    height: float | None = absent()
    color: str | None = absent()
    from_: str | None = Field(
        default=None, alias="from", json_schema_extra={"ts": "absent"}
    )
    to: str | None = absent()
    label: str | None = absent()
    members: list[str] | None = absent()


class BoardOpRequiredPayload(WirePayload):
    """Transport-only client-tool request: apply a batch of board ops to the open
    whiteboard canvas (`board_id`). The board counterpart of `workspace_op_required`;
    NOT journaled."""

    request_id: str
    conversation_id: str
    board_id: str
    ops: list[BoardOp]
    summary: str


class BoardReadRequiredPayload(WirePayload):
    """Transport-only client-tool request: rasterize board elements (`ids`) to a PNG and
    POST it back so the vision reader can read it. NOT journaled."""

    request_id: str
    conversation_id: str
    board_id: str
    ids: list[str]


class DesktopNotifyRequiredPayload(WirePayload):
    """Transport-only client-tool request: show an OS notification on the bound desktop
    (`desktop_notify` worker tool). NOT journaled."""

    request_id: str
    conversation_id: str
    title: str
    body: str | None = absent()


class HandoffSnapshotDonePayload(WirePayload):
    snapshot_id: str
    conversation_id: str
    size_bytes: int


class HandoffJobStartedPayload(WirePayload):
    job_id: str
    conversation_id: str
    job_conversation_id: str


class HandoffApplyResult(WirePayload):
    path: str
    status: Literal["applied", "skipped", "conflict", "error"]
    change_type: Literal["added", "modified", "deleted"] | None
    detail: str


class HandoffApplyDonePayload(WirePayload):
    job_id: str
    conversation_id: str
    results: list[HandoffApplyResult]
    applied: int
    skipped: int
    conflicts: int
    errors: int

"""WorkspaceChannel — route a LocalWorkspace op to the desktop and await it.

This is the generalized form of the tool-approval mechanism (``runtime/
approvals.py``): the server suspends on an ``asyncio.Future`` and a separate HTTP
request settles it. Approvals carry a one-shot *decision*; this channel carries a
full *request → response* op exchange so a server-side ``LocalWorkspace`` can run
file / execution ops on the user's real machine without the engine ever touching
a ``Path``.

Flow (one op):

1. ``LocalWorkspace`` calls ``WorkspaceChannel.request(op, args)``.
2. The channel registers a Future, emits a ``workspace_op_required`` SSE event,
   and awaits the Future (bounded by ``timeout_seconds``).
3. The bound desktop client runs the op against the local directory and POSTs the
   structured result to the ops resolve endpoint, which settles the Future.
4. The channel returns the op's ``value`` on success, or re-raises the original
   ``WorkspaceError`` subclass on failure — so the (unchanged) tool layer maps it
   to the same user-facing message it does for ``ServerWorkspace``.

State is in-process (single-worker posture, same as the approval gate); front
with Redis to scale to multiple workers (see ``config.py``). A result the client
never delivers fails as a ``WorkspaceIOError`` after the timeout, so a dropped
desktop never hangs the turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.events import EventSink, workspace_op_required
from agentcore.runtime.events.client_tool_reattach import (
    CHANNEL_WORKSPACE,
    client_tool_payload,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.interaction import InteractionKind
from agentcore.runtime.ports import ClientRequestBridge
from agentcore.workspace.protocol import (
    AlreadyExists,
    AmbiguousMatch,
    NoMatch,
    NotADirectory,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceError,
    WorkspaceIOError,
)

logger = get_logger(__name__)


class WorkspaceOp(StrEnum):
    """The op names exchanged over the channel (one per ``WorkspaceBackend`` method).

    Shared by ``LocalWorkspace`` (which sends them) and the desktop handler (which
    dispatches on them); kept as one closed set so the two ends can never drift.
    """

    READ = "read"
    WRITE = "write"
    APPEND = "append"
    READ_BYTES = "read_bytes"
    WRITE_BYTES = "write_bytes"
    LIST = "list"
    READ_LINES = "read_lines"
    LIST_TREE = "list_tree"
    INDEX_FILES = "index_files"
    MKDIR = "mkdir"
    DELETE = "delete"
    COPY = "copy"
    MOVE = "move"
    REPLACE = "replace"
    GREP = "grep"
    EXECUTE = "execute"
    # Probe which code_execute languages have a usable launcher on the user's
    # machine (PATH / Git Bash). Not a WorkspaceBackend method — issued at turn
    # prepare so the tool schema can drop unavailable languages (e.g. broken WSL
    # bash trampoline) before the model ever sees them.
    PROBE_EXEC = "probe_exec"
    # Local→云 handoff (双模式工作区 P2e / e1): pack the whole bound local root into
    # one archive (respecting ignore rules) so the server can stage + snapshot it.
    # NOT a WorkspaceBackend method — issued directly by the handoff orchestrator
    # (workspace/handoff.py), not by the engine/tools.
    ARCHIVE = "archive"
    # Background process ops (双模式工作区 §四): spawn / read / stop / list long-lived
    # processes held by the desktop main process. NOT WorkspaceBackend methods — issued by
    # the worker-only ``terminal`` tool over the same channel (LocalWorkspace + sidecar).
    PROCESS_START = "process_start"
    PROCESS_READ = "process_read"
    PROCESS_STOP = "process_stop"
    PROCESS_LIST = "process_list"


# Map a serialized error ``kind`` back to its WorkspaceError subclass, so a remote
# failure re-raises as the exact type the tool layer already catches. Anything
# unrecognized degrades to WorkspaceIOError (a generic I/O failure) rather than
# leaking as an unhandled exception.
_ERROR_KINDS: dict[str, type[WorkspaceError]] = {
    "OutsideWorkspace": OutsideWorkspace,
    "PathNotFound": PathNotFound,
    "NotAFile": NotAFile,
    "NotADirectory": NotADirectory,
    "AlreadyExists": AlreadyExists,
    "NotUTF8": NotUTF8,
    "NoMatch": NoMatch,
    "WorkspaceIOError": WorkspaceIOError,
}


def raise_op_error(error: dict[str, Any]) -> NoReturn:
    """Re-raise a serialized desktop op failure as its typed ``WorkspaceError``.

    ``AmbiguousMatch`` carries a ``count`` (used in the str_replace message), so it
    is reconstructed specially; every other kind maps by name.
    """
    kind = str(error.get("kind", ""))
    detail = str(error.get("detail", "") or "")
    if kind == "AmbiguousMatch":
        try:
            count = int(error.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        raise AmbiguousMatch(count, detail)
    cls = _ERROR_KINDS.get(kind, WorkspaceIOError)
    raise cls(detail)


@dataclass
class WorkspaceChannel:
    """Suspends one LocalWorkspace op until the bound desktop runs it.

    One channel per local-mode turn (constructed where the sink is available),
    bound to one desktop FS ``root_id``. ``request`` is the only entry point;
    ``LocalWorkspace`` builds the JSON-safe ``args`` and interprets the returned
    ``value`` per op.
    """

    sink: EventSink
    conversation_id: str
    registry: ClientRequestBridge
    timeout_seconds: float
    root_id: str = ""  # which desktop FS root this workspace is bound to (P2d)

    async def request(
        self,
        op: WorkspaceOp | str,
        args: dict[str, Any],
        *,
        timeout: float | None = None,
        root_id: str | None = None,
    ) -> Any:
        """Emit the op, await the desktop's result, and return it (or raise).

        Returns the op's ``value`` on success. Raises the typed ``WorkspaceError``
        the desktop reported on failure, or ``WorkspaceIOError`` on timeout / a
        malformed result envelope — never hangs and never leaks an untyped error,
        so the tool layer's existing ``except WorkspaceError`` keeps working.

        ``timeout`` overrides the channel-wide ``timeout_seconds`` for this one op.
        A long-running ``execute`` passes its own (code timeout + slack) so the
        desktop's execution limit stays authoritative and a legal long run is not
        cut off by the flat file-op deadline (双模式工作区 P2d 执行门).

        ``root_id`` overrides the channel's bound root for this one op (W3 session
        read-only mounts under ``external/<alias>/``); omit to use the workspace
        binding root. Does not change the conversation workspace binding contract.
        """
        op_name = str(op)
        request_id = new_id()
        deadline = self.timeout_seconds if timeout is None else timeout
        rid = self.root_id if root_id is None else root_id
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_WORKSPACE,
                    EventType.WORKSPACE_OP_REQUIRED.value,
                    params={"root_id": rid, "op": op_name, "args": args},
                ),
                timeout=deadline,
                on_suspended=lambda: self.sink.emit(
                    workspace_op_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        root_id=rid,
                        op=op_name,
                        args=args,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info("workspace.op_timeout", op=op_name, request_id=request_id)
            raise WorkspaceIOError(f"local workspace op '{op_name}' timed out") from e

        if not isinstance(result, dict) or not result.get("ok"):
            error = result.get("error") if isinstance(result, dict) else None
            raise_op_error(error or {"kind": "WorkspaceIOError", "detail": "malformed op result"})
        return result.get("value")

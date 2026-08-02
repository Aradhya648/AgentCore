"""SidecarServer core: transport dispatch and outbound I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentcore.conversation.store.outbox import OutboxStore
from agentcore.core.logging import get_logger
from agentcore.core.types import DEFAULT_PERMISSION_AXES, PermissionAxes
from agentcore.llm.credentials import (
    INFERENCE_CONVERSATION_HEADER,
    INFERENCE_TRACE_HEADER,
    LLMCredentials,
)
from agentcore.runtime.suspension import TurnSuspension
from agentcore.sidecar import protocol
from agentcore.sidecar.paused_store import LocalPausedTurnStore
from agentcore.sidecar.server_pkg.handlers import HandlerMixin
from agentcore.sidecar.server_pkg.turns import TurnExecutionMixin
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

logger = get_logger(__name__)


class SidecarServer(HandlerMixin, TurnExecutionMixin):
    """Routes inbound JSON-RPC lines to the engine and streams events back out."""

    def __init__(self, write_line: Callable[[str], Awaitable[None]]) -> None:
        self._write_line = write_line
        # Set by ``initialize``; until then every turn-bearing method is refused.
        self._initialized = False
        self._user_id = ""
        self._root: Path | None = None
        self._creds: LLMCredentials | None = None
        self._approvals_enabled = True
        # Conversation permission axes. Sidecar has no conversation DB — the desktop
        # sends ``permissionAxes`` on initialize and refreshes them per turn.
        self._permission_axes: PermissionAxes = DEFAULT_PERMISSION_AXES
        # The local durable-pause store (§8.6 paused-turn port, local impl), set from
        # ``initialize``'s ``dataDir``. ``None`` ⇒ no data dir ⇒ pauses stay in-memory.
        self._paused_store: LocalPausedTurnStore | None = None
        # Progressive outbox (as-built: 双模式工作区 §10.3): sibling of paused under dataDir.
        # ``None`` ⇒ no data dir ⇒ no local outbox (dev without durable write-back).
        self._outbox_store: OutboxStore | None = None
        # turn_id → running task, so ``cancel`` can reach an in-flight turn. A resume
        # registers under its message_id, so a cancel during resume reaches it too.
        self._turns: dict[str, asyncio.Task[None]] = {}
        # turn_id → conversation_id (cancel cascades coordination without FE always
        # repeating conversationId; cleared with ``_turns``).
        self._turn_conversations: dict[str, str] = {}
        # Fire-and-forget sends spawned during cancellation; kept referenced so
        # they are not garbage-collected before they flush.
        self._pending_sends: set[asyncio.Task[None]] = set()
        # Flipped by ``shutdown`` so the process loop can exit cleanly.
        self.shutdown_requested = asyncio.Event()

    def _register_turn(
        self, turn_id: str, task: asyncio.Task[None], *, conversation_id: str
    ) -> None:
        self._turns[turn_id] = task
        cid = (conversation_id or "").strip()
        if cid:
            self._turn_conversations[turn_id] = cid

    def _unregister_turn(self, turn_id: str) -> None:
        self._turns.pop(turn_id, None)
        self._turn_conversations.pop(turn_id, None)

    async def handle_line(self, line: str) -> None:
        """Parse and dispatch one inbound line. Never raises (loop-safe)."""
        line = line.strip()
        if not line:
            return
        try:
            message = protocol.decode_line(line)
        except protocol.ProtocolError as e:
            await self._send(protocol.make_error(None, protocol.PARSE_ERROR, str(e)))
            return

        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(method, str):
            # A response/notification we did not expect, or a malformed request.
            if request_id is not None:
                await self._send(
                    protocol.make_error(request_id, protocol.INVALID_REQUEST, "missing method")
                )
            return

        try:
            await self._dispatch(request_id, method, params)
        except Exception as e:  # a dispatch bug must not kill the read loop
            logger.error("sidecar.dispatch_failed", method=method, error=str(e), exc_info=True)
            if request_id is not None:
                await self._send(protocol.make_error(request_id, protocol.INTERNAL_ERROR, str(e)))

    async def _dispatch(self, request_id: Any, method: str, params: dict[str, Any]) -> None:
        if method == "initialize":
            await self._on_initialize(request_id, params)
        elif method == "startTurn":
            await self._on_start_turn(request_id, params)
        elif method == "respond":
            await self._on_respond(request_id, params)
        elif method == "resume":
            await self._on_resume(request_id, params)
        elif method == "listPaused":
            await self._on_list_paused(request_id, params)
        elif method == "cancel":
            await self._on_cancel(request_id, params)
        elif method == "runRedirect":
            await self._on_run_redirect(request_id, params)
        elif method == "debateSteer":
            await self._on_debate_steer(request_id, params)
        elif method == "turnFilesDiff":
            await self._on_turn_files_diff(request_id, params)
        elif method == "listBrowserSessions":
            await self._on_list_browser_sessions(request_id, params)
        elif method == "restoreTurnBaseline":
            await self._on_restore_turn_baseline(request_id, params)
        elif method == "shutdown":
            from agentcore.demo_tape.recorder import uninstall_recorder

            uninstall_recorder()
            self.shutdown_requested.set()
            await self._reply(request_id, {"ok": True})
        else:
            await self._send(
                protocol.make_error(
                    request_id, protocol.METHOD_NOT_FOUND, f"unknown method: {method}"
                )
            )

    def _make_backend(
        self, *, external_mounts: list | dict | None = None
    ) -> ServerWorkspace:
        """Build the local-disk workspace backend for a turn / resume.

        The sidecar runs ON the user's machine and this root IS their real disk →
        ``location="local"``, so the engine gates a delegated worker's machine-touching
        tools (file_write / code_execute) behind the user's consent, just like cloud
        local mode. Without this the gate stays off (workers un-gated) even with
        approvals enabled, since the default backend reports "server".

        ``external_mounts`` (W3) are session read-only dirs under ``external/<alias>/``.
        """
        assert self._root is not None  # guarded by callers
        backend = ServerWorkspace(
            root=self._root,
            sandbox=SubprocessSandbox(),
            root_label=self._root.name or "workspace",
            location="local",
        )
        if external_mounts:
            from agentcore.workspace.external_mounts import ExternalMount

            items: list[dict] = []
            if isinstance(external_mounts, list):
                items = [m for m in external_mounts if isinstance(m, dict)]
            elif isinstance(external_mounts, dict):
                items = [
                    {"alias": a, **m} if isinstance(m, dict) else {"alias": a}
                    for a, m in external_mounts.items()
                ]
            mounts: dict[str, ExternalMount] = {}
            for m in items:
                alias = str(m.get("alias") or "").strip()
                abs_path = str(m.get("absPath") or m.get("abs_path") or "").strip()
                if not alias or not abs_path:
                    continue
                mounts[alias] = ExternalMount(
                    alias=alias,
                    root_id=str(m.get("rootId") or m.get("root_id") or ""),
                    label=str(m.get("label") or alias),
                    abs_path=abs_path,
                    mode=(
                        "organize"
                        if str(m.get("mode") or "").strip().lower() == "organize"
                        else "readonly"
                    ),
                )
            if mounts:
                backend.attach_external_mounts(mounts)
        backend.start_code_index_maintenance()
        return backend

    def _suspension_hooks(
        self,
    ) -> tuple[
        Callable[[TurnSuspension], Awaitable[None]] | None,
        Callable[[str], Awaitable[None]] | None,
    ]:
        """The (saver, deleter) closures the pipeline wires into delegate / ask_user.

        Backed by the local paused-turn store so a pause persists before its wait and
        drops after a live resolve. ``(None, None)`` when no store ⇒ in-memory pause.
        """
        store = self._paused_store
        if store is None:
            return None, None
        return store.save, store.delete

    def _creds_for(
        self, conversation_id: str, trace_id: str = "", message_id: str = ""
    ) -> LLMCredentials | None:
        """Session creds + this turn's conversation/trace/message headers for the cloud
        inference proxy (Slice 4a), so spend attributes to the right conversation,
        every proxied LLM call joins this turn's trace (the write-back reuses the same
        id → ONE trace end-to-end, 打通气泡↔日志), and in-turn proxy rows carry the
        assistant ``message_id`` for daily-request quota (distinct from off-turn background
        rows that intentionally leave message_id NULL).

        Per-turn (one sidecar serves many conversations), so the session creds get a
        fresh per-turn copy. None creds (dev platform-fallback, no proxy) stay None.
        ``trace_id`` / ``message_id`` empty (untraced caller) ⇒ the header is omitted,
        not blank.
        """
        if self._creds is None:
            return None
        from agentcore.llm.credentials import INFERENCE_MESSAGE_HEADER

        extra = {
            **(self._creds.extra_headers or {}),
            INFERENCE_CONVERSATION_HEADER: conversation_id,
        }
        if trace_id:
            extra[INFERENCE_TRACE_HEADER] = trace_id
        if message_id:
            extra[INFERENCE_MESSAGE_HEADER] = message_id
        return replace(self._creds, extra_headers=extra)

    async def _send(self, message: dict[str, Any]) -> None:
        await self._write_line(protocol.encode_line(message))

    def _send_soon(self, message: dict[str, Any]) -> None:
        """Schedule a send on an independent task (for use during cancellation)."""
        task = asyncio.create_task(self._send(message))
        self._pending_sends.add(task)
        task.add_done_callback(self._pending_sends.discard)

    async def _reply(self, request_id: Any, result: Any) -> None:
        """Send a success response, unless the message was a notification (no id)."""
        if request_id is not None:
            await self._send(protocol.make_result(request_id, result))

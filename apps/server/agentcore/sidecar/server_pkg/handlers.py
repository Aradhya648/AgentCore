"""Sidecar JSON-RPC method handlers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError

from agentcore.api.schemas.messages import ResolveInteractionRequest, interaction_result_from_body
from agentcore.conversation.store.outbox import OutboxStore
from agentcore.core.logging import get_logger
from agentcore.core.types import PermissionPreset, preset_to_autonomy
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import PLATFORM_MODEL_FLASH
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.sidecar import protocol
from agentcore.sidecar.identity import resolve_sidecar_user_id
from agentcore.sidecar.paused_store import LocalPausedTurnStore
from agentcore.sidecar.server_pkg.result import parse_decision

logger = get_logger(__name__)

_RESOLVE_ADAPTER: TypeAdapter[ResolveInteractionRequest] = TypeAdapter(
    Annotated[ResolveInteractionRequest, Field(discriminator="kind")]
)


class HandlerMixin:
    async def _on_initialize(self, request_id: Any, params: dict[str, Any]) -> None:
        root_raw = str(params.get("workspaceRoot") or "").strip()
        root = Path(root_raw)
        if not root_raw or not root.is_dir():
            await self._send(
                protocol.make_error(
                    request_id,
                    protocol.INVALID_PARAMS,
                    f"workspaceRoot is not an existing directory: {root_raw!r}",
                )
            )
            return

        raw_user = params.get("userId")
        self._user_id = resolve_sidecar_user_id(
            None if raw_user is None else str(raw_user)
        )
        self._root = root.resolve()
        self._creds = self._parse_inference(params.get("inference"))
        self._approvals_enabled = bool(params.get("approvalsEnabled", True))
        self._permission_preset = (
            self._parse_permission_preset(params.get("permissionPreset"))
            or PermissionPreset.WORKSPACE
        )
        self._autonomy_policy = preset_to_autonomy(self._permission_preset)
        data_dir = str(params.get("dataDir") or "").strip()
        self._paused_store = self._build_paused_store(data_dir)
        self._outbox_store = self._build_outbox_store(data_dir)
        if self._outbox_store is not None:
            from agentcore.conversation.store import set_conversation_store

            # Swap the process-wide ConversationStore so EventSink checkpoints +
            # TurnJournalWriter appends land in the local outbox (not CloudStore).
            set_conversation_store(self._outbox_store)
        # Same DEMO_TAPE_RECORD_ENABLED gate as cloud lifespan; land under
        # ``<dataDir>/recordings`` (sibling of paused/outbox) — never repo demos/.
        self._install_recorder_if_enabled(data_dir)
        self._initialized = True
        logger.info(
            "sidecar.initialized",
            user_id=self._user_id,
            root_label=self._root.name,
            inference="cloud-proxy" if self._creds else "platform-fallback",
            approvals=self._approvals_enabled,
            permission_preset=self._permission_preset.value,
            durable_pause=self._paused_store is not None,
            outbox=self._outbox_store is not None,
        )
        await self._reply(
            request_id,
            {
                "ok": True,
                "protocolVersion": protocol.PROTOCOL_VERSION,
                "capabilities": {
                    "turns": True,
                    "interactions": True,
                    "cancel": True,
                    # durable plan_review / ask_user resume across a process restart,
                    # gated on a usable local data dir.
                    "durablePause": self._paused_store is not None,
                    "outbox": self._outbox_store is not None,
                },
            },
        )

    @staticmethod
    def _install_recorder_if_enabled(data_dir: str) -> None:
        """Arm the process-wide EventSink emit tap when recording is enabled.

        Switch reaches the sidecar via the same env / ``apps/server/.env`` channel
        as the cloud (``DEMO_TAPE_RECORD_ENABLED`` → ``settings.demo_tape_record_enabled``);
        no initialize-contract change. Requires ``dataDir`` so recordings land next
        to paused/outbox under ``<userData>/sidecar/recordings/``.
        """
        from agentcore.config import settings

        if not settings.demo_tape_record_enabled:
            return
        if not data_dir:
            logger.warning(
                "demo_tape.sidecar_record_skipped",
                reason="no_data_dir",
            )
            return
        from agentcore.demo_tape.recorder import install_recorder

        install_recorder(path=Path(data_dir) / "recordings")

    @staticmethod
    def _build_paused_store(data_dir: str) -> LocalPausedTurnStore | None:
        """Build the local durable-pause store from ``initialize``'s ``dataDir``.

        ``dataDir`` is the desktop's per-app data dir (e.g. ``<userData>/sidecar``);
        frames land under ``<dataDir>/paused``. Absent / blank ⇒ ``None`` ⇒ pauses
        stay in-memory (process-lifetime), the pre-durable behaviour.
        ``outbox_base`` is wired so D3 stale-claim recovery can adjudicate by journal.
        """
        if not data_dir:
            return None
        root = Path(data_dir)
        return LocalPausedTurnStore(root / "paused", outbox_base=root / "outbox")

    @staticmethod
    def _build_outbox_store(data_dir: str) -> OutboxStore | None:
        """Build the progressive outbox store (sibling of paused under dataDir).

        Pause/outbox split (as-built: 双模式工作区 §10.4): pause and outbox share
        the dataDir root but are separate stores / processors — never one state machine.
        """
        if not data_dir:
            return None
        return OutboxStore(Path(data_dir) / "outbox")

    @staticmethod
    def _parse_inference(raw: Any) -> LLMCredentials | None:
        """Build the per-turn cloud-proxy credentials from ``initialize`` params.

        ``inference = {baseUrl, apiKey, model?}`` points the engine's ``build_provider`` at
        the cloud inference proxy (so the platform key never lands on the user's
        machine). ``model`` is server-resolved at token mint and echoed here so the
        local engine logs / profiles match the proxy's upstream model.
        ``None`` / missing falls back to the sidecar's own server config
        (a dev convenience — never the production posture).
        """
        if not isinstance(raw, dict):
            return None
        base_url = str(raw.get("baseUrl") or "").strip()
        api_key = str(raw.get("apiKey") or "").strip()
        model = str(raw.get("model") or "").strip()
        if not base_url or not api_key:
            return None
        return LLMCredentials(
            api_key=api_key,
            base_url=base_url,
            default_model=model or PLATFORM_MODEL_FLASH,
        )

    def _refresh_creds(self, params: dict[str, Any]) -> None:
        """Refresh session creds from a per-turn ``inference`` block when present.

        A sidecar is long-lived (one per root, until app quit) but the cloud-proxy
        token rotates (2h TTL), so the desktop re-sends the current ``inference`` on
        every startTurn / resume — this keeps a day-long session from 401-ing once the
        initialize-time token expires. Absent ⇒ keep the initialize-time creds (e.g.
        the dev platform-fallback).
        """
        if "inference" in params:
            self._creds = self._parse_inference(params.get("inference"))

    @staticmethod
    def _parse_permission_preset(raw: Any) -> PermissionPreset | None:
        """Coerce the desktop's permissionPreset string; unknown / missing ⇒ ``None``."""
        try:
            return PermissionPreset(str(raw or "").strip())
        except ValueError:
            return None

    def _refresh_permission_preset(self, params: dict[str, Any]) -> None:
        """Adopt the conversation's CURRENT permission mode from per-turn params.

        Sidecar has no conversation DB — the desktop re-sends ``permissionPreset`` on
        every startTurn / resume so a mid-session switch applies to the next turn.
        Absent / invalid ⇒ keep the current value.
        """
        parsed = self._parse_permission_preset(params.get("permissionPreset"))
        if parsed is not None:
            self._permission_preset = parsed
            self._autonomy_policy = preset_to_autonomy(parsed)

    async def _on_start_turn(self, request_id: Any, params: dict[str, Any]) -> None:
        if not self._initialized or self._root is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.NOT_INITIALIZED, "initialize must be called first"
                )
            )
            return
        turn_id = str(params.get("turnId") or "").strip()
        if not turn_id:
            await self._send(
                protocol.make_error(request_id, protocol.INVALID_PARAMS, "turnId is required")
            )
            return
        if turn_id in self._turns:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, f"turn already running: {turn_id}"
                )
            )
            return

        # Tape bindings live on the cloud process. A local/sidecar turn never sees
        # them — historically this silently became a normal AI reply. When replay
        # is armed, refuse so the operator gets an explicit error instead.
        conversation_id = str(params.get("conversationId") or turn_id)
        if await self._reject_if_tape_bound_local(request_id, conversation_id):
            return

        # Adopt this turn's cloud-proxy token before it runs (refreshes a rotated TTL).
        self._refresh_creds(params)
        self._refresh_permission_preset(params)

        # The response to startTurn is DEFERRED until the turn completes (it carries
        # the final result); the live events flow as ``turn/event`` notifications in
        # the meantime. Spawning a task lets ``respond`` / ``cancel`` be serviced by
        # the read loop while the turn runs.
        task = asyncio.create_task(self._run_turn(request_id, turn_id, params))
        self._register_turn(turn_id, task, conversation_id=conversation_id)

    async def _reject_if_tape_bound_local(
        self, request_id: Any, conversation_id: str
    ) -> bool:
        """Return True when the startTurn RPC was rejected (caller must return)."""
        from agentcore.demo_tape.binding import LOCAL_SESSION_BOUND_MSG, resolve_binding

        binding = resolve_binding(conversation_id)
        if binding is None:
            return False
        logger.error(
            "demo_tape.sidecar_local_session_bound",
            conversation_id=conversation_id,
            tape=str(binding.tape_path),
            speed=binding.speed,
        )
        await self._send(
            protocol.make_error(
                request_id,
                protocol.INVALID_PARAMS,
                f"{LOCAL_SESSION_BOUND_MSG} tape={binding.tape_path.name}",
            )
        )
        return True

    async def _on_respond(self, request_id: Any, params: dict[str, Any]) -> None:
        interaction_id = str(params.get("requestId") or "")
        conversation_id = str(params.get("conversationId") or "")
        try:
            body = _RESOLVE_ADAPTER.validate_python(params.get("result"))
        except ValidationError as e:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, f"invalid respond result: {e}"
                )
            )
            return

        # Mirror the cloud resolve route's guards (routes/conversations.py): refuse a
        # stale / cross-conversation / kind-mismatched settle, and build the kind's
        # typed result via the SHARED projection — so an approval resolves with an
        # ApprovalDecision enum (the gate compares it by identity), a client_tool with
        # its op envelope, etc., exactly as in cloud mode. ask_user / plan_review are no
        # longer resolvable here (挂起即收口 ②, Phase 3 — they finalize and resume cold).
        registry = default_interaction_registry()
        pending = registry.get(interaction_id)
        if (
            pending is None
            or pending.conversation_id != conversation_id
            or pending.kind != body.kind
        ):
            await self._reply(request_id, {"resolved": False})
            return
        resolved = registry.resolve(
            interaction_id,
            interaction_result_from_body(body),
            conversation_id=conversation_id,
        )
        await self._reply(request_id, {"resolved": bool(resolved)})

    async def _on_resume(self, request_id: Any, params: dict[str, Any]) -> None:
        """Continue a durably-paused turn on a fresh process (结构化挂起 2b resume).

        Mirrors the cloud ``POST .../resume`` route: claim the local frame (atomic,
        so a turn never resumes twice) then drive the rest of the turn on a fresh
        sink, replying with the same final-result shape as ``startTurn``. The
        message_id doubles as the event-routing turn id (one durable pause per turn).
        """
        if not self._initialized or self._root is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.NOT_INITIALIZED, "initialize must be called first"
                )
            )
            return
        message_id = str(params.get("messageId") or "").strip()
        conversation_id = str(params.get("conversationId") or "").strip()
        if not message_id or not conversation_id:
            await self._send(
                protocol.make_error(
                    request_id,
                    protocol.INVALID_PARAMS,
                    "messageId and conversationId are required",
                )
            )
            return
        if message_id in self._turns:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, f"turn already running: {message_id}"
                )
            )
            return
        if self._paused_store is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, "durable pause is not enabled"
                )
            )
            return
        suspension = await self._paused_store.claim(message_id, conversation_id=conversation_id)
        if suspension is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.PAUSED_TURN_NOT_FOUND, "挂起的回合不存在或已处理"
                )
            )
            return

        decision = parse_decision(params.get("decision"))
        note = str(params.get("note") or "")
        selected = [str(s) for s in (params.get("selected") or [])]
        style_id = str(params.get("styleId") or params.get("style_id") or "").strip()
        # Per-turn trace_id (mirrors startTurn): ties this continuation's proxied LLM
        # calls to its write-back so the resumed reply is greppable as one trace.
        trace_id = str(params.get("traceId") or "")
        user_message_id = str(params.get("userMessageId") or "").strip()
        # Adopt this turn's cloud-proxy token before it runs (refreshes a rotated TTL).
        self._refresh_creds(params)
        self._refresh_permission_preset(params)
        task = asyncio.create_task(
            self._run_resume(
                request_id,
                suspension,
                decision,
                note,
                selected,
                trace_id,
                user_message_id,
                params.get("externalMounts"),
                style_id=style_id or None,
            )
        )
        self._register_turn(message_id, task, conversation_id=conversation_id)

    async def _on_list_paused(self, request_id: Any, params: dict[str, Any]) -> None:
        """A conversation's pending durable pauses, as resume-card summaries.

        Read-only (does not claim); ``resume`` claims. Mirrors the cloud recovery
        snapshot's ``paused`` summaries (``GET .../recovery``) so the desktop renders
        the same resume cards.
        """
        conversation_id = str(params.get("conversationId") or "").strip()
        if self._paused_store is None or not conversation_id:
            await self._reply(request_id, {"data": []})
            return
        summaries = await self._paused_store.list_summaries(conversation_id)
        await self._reply(request_id, {"data": summaries})

    async def _on_cancel(self, request_id: Any, params: dict[str, Any]) -> None:
        """Explicit user stop — same cascade semantics as cloud ``POST …/stop``.

        Marks coordination ``user_stopped`` and cancels the drive / in-flight workers
        *before* ``task.cancel()``, so ``release_turn_coordination`` clears instead of
        detach-and-continue. SSE disconnect must NOT use this path.
        """
        turn_id = str(params.get("turnId") or "")
        conversation_id = (
            str(params.get("conversationId") or "").strip()
            or self._turn_conversations.get(turn_id, "")
        )
        cascaded = False
        if conversation_id:
            from agentcore.runtime.coordination.session import (
                cancel_coordination_on_user_stop,
            )

            cascaded = cancel_coordination_on_user_stop(conversation_id)
        task = self._turns.get(turn_id)
        if task is not None and not task.done():
            task.cancel()
            await self._reply(request_id, {"cancelled": True})
        else:
            await self._reply(request_id, {"cancelled": cascaded})

    async def _on_run_redirect(self, request_id: Any, params: dict[str, Any]) -> None:
        from agentcore.runtime.runs.redirect_queue import enqueue_redirect, peek_redirect_count

        execution_id = str(params.get("executionId") or "").strip()
        run_id = str(params.get("runId") or "").strip()
        feedback = str(params.get("feedback") or "").strip()
        conversation_id = str(params.get("conversationId") or "").strip()
        if not execution_id or not run_id or not feedback or not conversation_id:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, "runRedirect requires executionId, runId, feedback, conversationId"
                )
            )
            return
        enqueue_redirect(
            execution_id=execution_id,
            run_id=run_id,
            feedback=feedback,
            conversation_id=conversation_id,
        )
        await self._reply(request_id, {"ok": True, "queued": peek_redirect_count(execution_id)})

    async def _on_debate_steer(self, request_id: Any, params: dict[str, Any]) -> None:
        from agentcore.runtime.debate.steer_queue import enqueue_steer, peek_steer_count

        execution_id = str(params.get("executionId") or "").strip()
        conversation_id = str(params.get("conversationId") or "").strip()
        decision = str(params.get("decision") or "continue").strip()
        focus = str(params.get("focus") or "").strip()
        ask = str(params.get("ask") or "").strip()
        ask_target = str(params.get("askTarget") or "").strip()
        if not execution_id or not conversation_id or decision not in ("continue", "conclude"):
            await self._send(
                protocol.make_error(
                    request_id,
                    protocol.INVALID_PARAMS,
                    "debateSteer requires executionId, conversationId, decision∈continue|conclude",
                )
            )
            return
        enqueue_steer(
            execution_id=execution_id,
            conversation_id=conversation_id,
            decision=decision,  # type: ignore[arg-type]
            focus=focus,
            ask=ask,
            ask_target=ask_target,
        )
        await self._reply(request_id, {"ok": True, "queued": peek_steer_count(execution_id)})

    async def _on_turn_files_diff(self, request_id: Any, params: dict[str, Any]) -> None:
        """A1+ local: baseline zip vs live workspace (read-only; no cloud path)."""
        if self._root is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_REQUEST, "sidecar not initialized"
                )
            )
            return
        message_id = str(params.get("messageId") or "").strip()
        if not message_id:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, "turnFilesDiff requires messageId"
                )
            )
            return
        baseline_raw = params.get("baselineSnapshotId")
        baseline_id = (
            str(baseline_raw).strip() if baseline_raw is not None and str(baseline_raw).strip() else None
        )
        from agentcore.workspace.turn_diff import compute_local_turn_files_diff

        try:
            result = await compute_local_turn_files_diff(
                workspace_root=self._root,
                message_id=message_id,
                baseline_snapshot_id=baseline_id,
            )
        except Exception as e:
            logger.warning("sidecar.turn_files_diff_failed", error=str(e), exc_info=True)
            await self._reply(
                request_id,
                {
                    "message_id": message_id,
                    "baseline_snapshot_id": baseline_id,
                    "available": False,
                    "data": [],
                    "total": 0,
                    "added": 0,
                    "modified": 0,
                    "deleted": 0,
                },
            )
            return

        rows = [
            {
                "path": c.path,
                "change_type": c.change_type,
                "base_sha": c.base_sha,
                "result_sha": c.result_sha,
                "is_binary": c.is_binary,
                "content": c.content,
                "size_bytes": c.size_bytes,
                "base_content": c.base_content,
            }
            for c in result.changes
        ]
        added = sum(1 for r in rows if r["change_type"] == "added")
        modified = sum(1 for r in rows if r["change_type"] == "modified")
        deleted = sum(1 for r in rows if r["change_type"] == "deleted")
        await self._reply(
            request_id,
            {
                "message_id": result.message_id,
                "baseline_snapshot_id": result.baseline_snapshot_id,
                "available": result.available,
                "data": rows,
                "total": len(rows),
                "added": added,
                "modified": modified,
                "deleted": deleted,
            },
        )

    async def _on_restore_turn_baseline(self, request_id: Any, params: dict[str, Any]) -> None:
        """A2′ local: unzip baseline over workspace (never cloud restoreSnapshot)."""
        if self._root is None:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_REQUEST, "sidecar not initialized"
                )
            )
            return
        snapshot_id = str(
            params.get("snapshotId") or params.get("baselineSnapshotId") or ""
        ).strip()
        if not snapshot_id:
            await self._send(
                protocol.make_error(
                    request_id,
                    protocol.INVALID_PARAMS,
                    "restoreTurnBaseline requires snapshotId",
                )
            )
            return
        from agentcore.workspace.turn_diff import restore_local_turn_baseline

        try:
            await restore_local_turn_baseline(
                workspace_root=self._root, snapshot_id=snapshot_id
            )
        except FileNotFoundError:
            await self._send(
                protocol.make_error(
                    request_id, protocol.INVALID_PARAMS, f"baseline not found: {snapshot_id}"
                )
            )
            return
        except Exception as e:
            logger.warning("sidecar.restore_turn_baseline_failed", error=str(e), exc_info=True)
            await self._send(
                protocol.make_error(request_id, protocol.INTERNAL_ERROR, str(e))
            )
            return
        await self._reply(request_id, {"ok": True, "snapshot_id": snapshot_id})

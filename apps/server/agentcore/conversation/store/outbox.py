"""Sidecar OutboxStore — progressive local turn persistence (as-built: 双模式工作区 §10.3).

Each method serializes into a per-turn outbox record under ``<dataDir>/outbox/``
(sibling of ``paused/``). The Electron main-process writebacker drains ``ready``
records via ``POST .../local-turns`` → ``CloudStore.finalize(mode="local")``.

Record lifecycle: ``open`` (begin + checkpoints + journal) → ``ready`` (finalize /
salvage) → deleted after cloud ack. Idempotent: begin is create-once; checkpoint
is content-monotonic; journal appends dedupe on ``seq``; finalize is once.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from agentcore.conversation.store.merge import (
    MESSAGE_STATUS_COMPLETE,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_INCOMPLETE,
    MESSAGE_STATUS_RUNNING,
    pick_merged_content,
    pick_monotonic_content,
)
from agentcore.core.logging import get_logger
from agentcore.db.repositories.stream_state import resolve_stream_upsert

logger = get_logger(__name__)

SCHEMA_VERSION = 1
PHASE_OPEN = "open"
PHASE_READY = "ready"

# Mirror StreamCheckpointer channel ids (avoid store → runtime import).
_CHANNEL_CAPTAIN_CONTENT = "captain:content"
_CHANNEL_CAPTAIN_REASONING = "captain:reasoning"


def _is_safe_id(value: str) -> bool:
    if not value or ".." in value:
        return False
    return "/" not in value and "\\" not in value


def _is_transient_replace_error(exc: BaseException) -> bool:
    """Windows file-lock noise on ``os.replace`` (AV / writebacker holding ``.json``).

    WinError 5 (ACCESS_DENIED) and 32 (SHARING_VIOLATION) are the observed forms;
    POSIX cousins ``EACCES`` / ``EPERM`` / ``EBUSY`` get the same treatment.
    """
    if not isinstance(exc, OSError):
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror in (5, 32):
        return True
    if isinstance(exc, PermissionError):
        return True
    transient_errnos = {errno.EACCES, errno.EPERM}
    if hasattr(errno, "EBUSY"):
        transient_errnos.add(errno.EBUSY)
    return getattr(exc, "errno", None) in transient_errnos


# Backoff between replace attempts when the destination is briefly locked.
_REPLACE_RETRY_DELAYS_S = (0.0, 0.05, 0.15, 0.35, 0.75)


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """``os.replace`` with limited retry for transient Windows locks; re-raises if exhausted."""
    last: OSError | None = None
    for attempt, delay in enumerate(_REPLACE_RETRY_DELAYS_S):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, target)
            if attempt > 0:
                logger.warning(
                    "sidecar.outbox_replace_recovered",
                    target=str(target),
                    attempts=attempt + 1,
                )
            return
        except OSError as e:
            if not _is_transient_replace_error(e):
                raise
            last = e
            logger.warning(
                "sidecar.outbox_replace_retry",
                target=str(target),
                attempt=attempt + 1,
                max_attempts=len(_REPLACE_RETRY_DELAYS_S),
                error=str(e),
            )
    assert last is not None
    raise last


class OutboxStore:
    """ConversationStore that appends progressive outbox records to local disk.

    Does **not** talk to Postgres or the cloud API — durability is the file; the
    main-process writebacker is the sole cloud delivery path.
    """

    def __init__(self, base: Path) -> None:
        self._base = base
        # Per-turn context bound by the sidecar host before begin_turn (user message
        # + idempotency anchor are not on the Protocol begin_turn signature).
        self._ctx: dict[str, Any] | None = None
        # user_message_id → asyncio.Lock for serialized read-modify-write.
        self._locks: dict[str, asyncio.Lock] = {}

    def bind_turn(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        user_message: str,
        message_id: str,
        trace_id: str,
    ) -> None:
        """Pin the active turn's idempotency keys before begin_turn / pipeline."""
        self._ctx = {
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "user_message": user_message,
            "message_id": message_id,
            "trace_id": trace_id,
        }

    def clear_turn(self) -> None:
        self._ctx = None

    def _lock_for(self, user_message_id: str) -> asyncio.Lock:
        lock = self._locks.get(user_message_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_message_id] = lock
        return lock

    def _path(self, user_message_id: str) -> Path:
        return self._base / f"{user_message_id}.json"

    def _empty_record(self, *, user_message_id: str, **fields: Any) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "user_message_id": user_message_id,
            "conversation_id": fields.get("conversation_id", ""),
            "message_id": fields.get("message_id"),
            "trace_id": fields.get("trace_id", ""),
            "user_message": fields.get("user_message", ""),
            "content": "",
            "reasoning_content": None,
            "citations": [],
            "evidence_ledger": [],
            "runs": None,
            "journal": {},  # seq(str) → entry — idempotent append
            # channel → {text, generation} — StreamCheckpointer mid-stream snapshots (D6)
            "stream_segments": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "rounds": 0,
            "finish_reason": None,
            "phase": PHASE_OPEN,
            "updated_at": time.time(),
            "ops": [],
        }

    def _read_sync(self, user_message_id: str) -> dict[str, Any] | None:
        path = self._path(user_message_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write_sync(self, user_message_id: str, record: dict[str, Any]) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        target = self._path(user_message_id)
        tmp = target.with_suffix(".json.tmp")
        record["updated_at"] = time.time()
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        # Electron writebacker / AV may briefly hold the destination on Windows
        # (WinError 5) — retry, then let ``_mutate`` log ``outbox_write_failed``.
        _replace_with_retry(tmp, target)

    async def _mutate(
        self,
        user_message_id: str,
        mutator: Any,
    ) -> None:
        if not _is_safe_id(user_message_id):
            return
        async with self._lock_for(user_message_id):
            try:
                await asyncio.to_thread(self._mutate_sync, user_message_id, mutator)
            except Exception as e:  # noqa: BLE001 — outbox must never break the turn
                logger.error(
                    "sidecar.outbox_write_failed",
                    user_message_id=user_message_id,
                    error=str(e),
                )

    def _mutate_sync(self, user_message_id: str, mutator: Any) -> None:
        record = self._read_sync(user_message_id)
        if record is None:
            record = self._empty_record(user_message_id=user_message_id)
        mutator(record)
        self._write_sync(user_message_id, record)

    async def begin_turn(
        self,
        *,
        conversation_id: str,
        message_id: str,
        trace_id: str,
    ) -> None:
        ctx = self._ctx or {}
        user_message_id = str(ctx.get("user_message_id") or message_id)
        user_message = str(ctx.get("user_message") or "")

        def mutate(record: dict[str, Any]) -> None:
            if "begin_turn" in record.get("ops", []):
                return  # idempotent
            record["conversation_id"] = conversation_id
            record["message_id"] = message_id
            record["trace_id"] = trace_id
            record["user_message_id"] = user_message_id
            if user_message:
                record["user_message"] = user_message
            record["phase"] = PHASE_OPEN
            record.setdefault("ops", []).append("begin_turn")

        await self._mutate(user_message_id, mutate)

    async def checkpoint(
        self,
        *,
        conversation_id: str,
        message_id: str,
        content: str,
    ) -> None:
        ctx = self._ctx or {}
        user_message_id = str(ctx.get("user_message_id") or message_id)

        def mutate(record: dict[str, Any]) -> None:
            if record.get("phase") == PHASE_READY:
                return  # finalize already sealed
            record["conversation_id"] = conversation_id or record.get("conversation_id")
            record["message_id"] = message_id or record.get("message_id")
            record["content"] = pick_monotonic_content(record.get("content"), content)
            ops = record.setdefault("ops", [])
            if "checkpoint" not in ops:
                ops.append("checkpoint")

        await self._mutate(user_message_id, mutate)

    async def append_journal(
        self,
        *,
        turn_id: str,
        seq: int | None,
        conversation_id: str,
        trace_id: str | None,
        entry: dict[str, Any],
    ) -> int | None:
        ctx = self._ctx or {}
        user_message_id = str(ctx.get("user_message_id") or turn_id)
        allocated: list[int | None] = [None]

        def mutate(record: dict[str, Any]) -> None:
            if record.get("phase") == PHASE_READY:
                return
            record["conversation_id"] = conversation_id or record.get("conversation_id")
            record["message_id"] = turn_id or record.get("message_id")
            if trace_id:
                record["trace_id"] = trace_id
            journal = record.setdefault("journal", {})
            # Live seq=None：本地 outbox 用 max+1 分配；merge 显式 seq 幂等。
            if seq is None:
                existing = [int(k) for k in journal if str(k).lstrip("-").isdigit()]
                next_seq = (max(existing) + 1) if existing else 0
                key = str(next_seq)
            else:
                key = str(seq)
            if key not in journal:  # seq-idempotent
                journal[key] = entry
                allocated[0] = int(key)
            ops = record.setdefault("ops", [])
            if "journal_append" not in ops:
                ops.append("journal_append")

        await self._mutate(user_message_id, mutate)
        return allocated[0]

    async def append_journal_durable(
        self,
        *,
        turn_id: str,
        conversation_id: str,
        trace_id: str | None,
        entry: dict[str, Any],
        user_message_id: str,
    ) -> int:
        """Settlement prewrite: append one journal entry and **raise** on failure.

        Unlike :meth:`append_journal` (best-effort, never breaks the turn), D1
        settlement must be durable before the paused frame is consumed — a silent
        swallow would leave「已授权」without a journal fact.
        """
        if not _is_safe_id(user_message_id):
            raise ValueError(f"unsafe outbox user_message_id: {user_message_id!r}")
        allocated: list[int] = [-1]

        def mutate(record: dict[str, Any]) -> None:
            # Settlement may land while phase is still open; also allow a ready
            # record that is being continued (idempotent re-prewrite no-ops via seq).
            record["conversation_id"] = conversation_id or record.get("conversation_id")
            record["message_id"] = turn_id or record.get("message_id")
            if trace_id:
                record["trace_id"] = trace_id
            if not record.get("user_message_id"):
                record["user_message_id"] = user_message_id
            journal = record.setdefault("journal", {})
            existing = [int(k) for k in journal if str(k).lstrip("-").isdigit()]
            next_seq = (max(existing) + 1) if existing else 0
            # Dedupe by settlement identity (kind + checkpoint_id) so retries don't fan out.
            kind = str(entry.get("kind") or "")
            payload = dict(entry.get("payload") or {})
            cid = str(payload.get("checkpoint_id") or "")
            if kind and cid:
                for existing_entry in journal.values():
                    if not isinstance(existing_entry, dict):
                        continue
                    if str(existing_entry.get("kind") or "") != kind:
                        continue
                    ep = dict(existing_entry.get("payload") or {})
                    if str(ep.get("checkpoint_id") or "") == cid:
                        allocated[0] = next(
                            (
                                int(k)
                                for k, v in journal.items()
                                if v is existing_entry and str(k).lstrip("-").isdigit()
                            ),
                            next_seq,
                        )
                        return
            key = str(next_seq)
            journal[key] = entry
            allocated[0] = next_seq
            ops = record.setdefault("ops", [])
            if "journal_append" not in ops:
                ops.append("journal_append")
            if "settlement_prewrite" not in ops:
                ops.append("settlement_prewrite")

        async with self._lock_for(user_message_id):
            await asyncio.to_thread(self._mutate_sync, user_message_id, mutate)
        if allocated[0] < 0:
            raise RuntimeError("settlement prewrite did not allocate a journal seq")
        return allocated[0]

    def find_record_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        """Read-only lookup of an outbox record by assistant ``message_id``."""
        if not message_id:
            return None
        for record in list_outbox_records(self._base):
            if str(record.get("message_id") or "") == message_id:
                return record
        return None

    async def finalize(
        self,
        *,
        mode: Literal["cloud", "local"] = "local",
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        del mode  # outbox only ever stages local write-back
        user_message_id = str(kwargs.get("user_message_id") or "")
        if not user_message_id:
            ctx = self._ctx or {}
            user_message_id = str(ctx.get("user_message_id") or "")
        if not user_message_id:
            logger.warning("sidecar.outbox_finalize_missing_user_message_id")
            return None

        def mutate(record: dict[str, Any]) -> None:
            if record.get("phase") == PHASE_READY and "finalize" in record.get("ops", []):
                return  # already sealed — idempotent
            record["conversation_id"] = kwargs.get("conversation_id") or record.get(
                "conversation_id"
            )
            record["user_message"] = kwargs.get("user_message") or record.get("user_message")
            record["user_message_id"] = user_message_id
            record["message_id"] = kwargs.get("message_id") or record.get("message_id")
            record["trace_id"] = kwargs.get("trace_id") or record.get("trace_id")
            content = kwargs.get("assistant_content")
            if content is not None:
                finish = kwargs.get("finish_reason")
                if finish == "cancelled":
                    status = MESSAGE_STATUS_INCOMPLETE
                elif finish == "error":
                    status = MESSAGE_STATUS_FAILED
                elif finish == "paused":
                    status = MESSAGE_STATUS_RUNNING
                else:
                    # Happy-path / missing finish_reason: treat as complete delivery.
                    status = MESSAGE_STATUS_COMPLETE
                record["content"] = pick_merged_content(
                    record.get("content"),
                    content,
                    incoming_status=status,
                )
            if "assistant_reasoning" in kwargs:
                record["reasoning_content"] = kwargs.get("assistant_reasoning")
            if kwargs.get("citations") is not None:
                record["citations"] = list(kwargs["citations"] or [])
            if kwargs.get("evidence_ledger") is not None:
                record["evidence_ledger"] = list(kwargs["evidence_ledger"] or [])
            if kwargs.get("runs") is not None:
                record["runs"] = kwargs["runs"]
            for key in (
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cache_hit_tokens",
                "cache_miss_tokens",
                "rounds",
            ):
                if key in kwargs and kwargs[key] is not None:
                    record[key] = int(kwargs[key] or 0)
            if kwargs.get("finish_reason") is not None:
                record["finish_reason"] = kwargs["finish_reason"]
            record["phase"] = PHASE_READY
            ops = record.setdefault("ops", [])
            if "finalize" not in ops:
                ops.append("finalize")

        await self._mutate(user_message_id, mutate)
        # Local ack shape (cloud ids arrive after main-process writeback).
        return {
            "user_message_id": user_message_id,
            "assistant_message_id": kwargs.get("message_id"),
            "title": None,
        }

    async def salvage(
        self,
        *,
        journal: list[dict[str, Any]],
        content: str,
        conversation_id: str,
        trace_id: str,
        message_id: str | None,
    ) -> None:
        ctx = self._ctx or {}
        user_message_id = str(ctx.get("user_message_id") or message_id or "")
        if not user_message_id:
            return

        def mutate(record: dict[str, Any]) -> None:
            if record.get("phase") == PHASE_READY:
                return
            record["conversation_id"] = conversation_id or record.get("conversation_id")
            record["message_id"] = message_id or record.get("message_id")
            record["trace_id"] = trace_id or record.get("trace_id")
            record["content"] = pick_monotonic_content(record.get("content"), content)
            journal_map = record.setdefault("journal", {})
            for i, entry in enumerate(journal or []):
                # Salvage journal may lack seq — use enumerate offset past existing keys.
                key = str(entry.get("seq", i))
                if key not in journal_map:
                    journal_map[key] = entry
            # User stop / cancel = normal incomplete end: seal cancelled + READY so
            # writeback can project the produced journal. No frameless retain-open.
            record["finish_reason"] = "cancelled"
            record["phase"] = PHASE_READY
            ops = record.setdefault("ops", [])
            if "salvage" not in ops:
                ops.append("salvage")

        await self._mutate(user_message_id, mutate)

    def _user_message_id_for_turn(self, turn_id: str) -> str | None:
        """Resolve outbox file key for a stream-segment turn_id (assistant message_id)."""
        ctx = self._ctx or {}
        user_message_id = str(ctx.get("user_message_id") or "")
        if not user_message_id:
            return None
        ctx_mid = ctx.get("message_id")
        if ctx_mid and str(ctx_mid) != turn_id:
            return None
        return user_message_id

    async def upsert_stream_segments(
        self,
        *,
        turn_id: str,
        segments: Sequence[tuple[str, str, int]],
    ) -> None:
        """Persist StreamCheckpointer flushes into the open outbox record (D6).

        Write cadence matches the checkpointer (3s / 4KB / semantic) — callers must
        not invoke this per delta. Read-side overlay stays out of scope
        (``list_stream_segments`` remains empty).
        """
        if not segments:
            return
        user_message_id = self._user_message_id_for_turn(turn_id)
        if not user_message_id:
            return

        def mutate(record: dict[str, Any]) -> None:
            if record.get("phase") == PHASE_READY:
                return
            if turn_id and not record.get("message_id"):
                record["message_id"] = turn_id
            segs: dict[str, Any] = record.setdefault("stream_segments", {})
            if not isinstance(segs, dict):
                segs = {}
                record["stream_segments"] = segs
            for channel, text, generation in segments:
                if not channel:
                    continue
                existing = segs.get(channel) if isinstance(segs.get(channel), dict) else {}
                resolved = resolve_stream_upsert(
                    existing_text=existing.get("text") if existing else None,
                    existing_generation=(
                        int(existing["generation"])
                        if existing and existing.get("generation") is not None
                        else None
                    ),
                    incoming_text=text if isinstance(text, str) else str(text or ""),
                    incoming_generation=int(generation or 0),
                )
                if resolved is None:
                    continue
                new_text, new_gen = resolved
                segs[channel] = {"text": new_text, "generation": new_gen}
            ops = record.setdefault("ops", [])
            if "stream_segments" not in ops:
                ops.append("stream_segments")

        await self._mutate(user_message_id, mutate)

    async def list_stream_segments(
        self,
        *,
        turn_id: str,
    ) -> list[dict[str, Any]]:
        # Local mid-stream overlay is out of scope — desktop salvage reads the
        # outbox JSON directly; cloud overlay stays on CloudStore.
        del turn_id
        return []

    async def list_stream_segments_map(
        self,
        *,
        turn_ids: Sequence[str],
    ) -> dict[str, list[dict[str, Any]]]:
        del turn_ids
        return {}

    async def clear_stream_segments(
        self,
        *,
        turn_id: str,
    ) -> None:
        user_message_id = self._user_message_id_for_turn(turn_id)
        if not user_message_id:
            return

        def mutate(record: dict[str, Any]) -> None:
            record["stream_segments"] = {}

        await self._mutate(user_message_id, mutate)


def captain_text_from_stream_segments(
    stream_segments: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Extract captain content / reasoning snapshots from an outbox ``stream_segments`` map."""
    if not stream_segments or not isinstance(stream_segments, dict):
        return "", None
    content = ""
    reasoning: str | None = None
    content_entry = stream_segments.get(_CHANNEL_CAPTAIN_CONTENT)
    if isinstance(content_entry, dict):
        content = str(content_entry.get("text") or "")
    reasoning_entry = stream_segments.get(_CHANNEL_CAPTAIN_REASONING)
    if isinstance(reasoning_entry, dict):
        text = str(reasoning_entry.get("text") or "")
        reasoning = text if text else None
    return content, reasoning


def journal_entries_from_map(journal: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Sort an outbox ``journal`` map (seq → entry) into a list for ``RecordTurnRequest``."""
    if not journal:
        return None

    def _seq_key(key: str) -> tuple[int, str]:
        try:
            return (0, f"{int(key):020d}")
        except (TypeError, ValueError):
            return (1, str(key))

    entries = [journal[k] for k in sorted(journal.keys(), key=_seq_key)]
    return entries or None


def list_outbox_records(base: Path) -> list[dict[str, Any]]:
    """Read all outbox JSON records (best-effort; skips torn files)."""
    if not base.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("user_message_id"):
            records.append(data)
    return records


def delete_outbox_record(base: Path, user_message_id: str) -> None:
    """Drop a synced outbox file (best-effort)."""
    if not _is_safe_id(user_message_id):
        return
    path = base / f"{user_message_id}.json"
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(
            "sidecar.outbox_delete_failed",
            user_message_id=user_message_id,
            error=str(e),
        )


def to_record_turn_body(record: dict[str, Any]) -> dict[str, Any]:
    """Project an outbox record into the ``RecordTurnRequest`` wire shape."""
    body: dict[str, Any] = {
        "user_message": record.get("user_message") or "",
        "user_message_id": record["user_message_id"],
        "content": record.get("content") or "",
        "reasoning_content": record.get("reasoning_content"),
        "citations": record.get("citations") or [],
        "evidence_ledger": record.get("evidence_ledger") or [],
        "runs": record.get("runs"),
        "message_id": record.get("message_id"),
        "input_tokens": int(record.get("input_tokens") or 0),
        "output_tokens": int(record.get("output_tokens") or 0),
        "reasoning_tokens": int(record.get("reasoning_tokens") or 0),
        "cache_hit_tokens": int(record.get("cache_hit_tokens") or 0),
        "cache_miss_tokens": int(record.get("cache_miss_tokens") or 0),
        "rounds": int(record.get("rounds") or 0),
        "trace_id": record.get("trace_id") or "",
        "finish_reason": record.get("finish_reason"),
    }
    journal = journal_entries_from_map(record.get("journal"))
    if journal is not None:
        body["journal"] = journal
    return body

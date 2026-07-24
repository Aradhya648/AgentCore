"""At-least-once durable queue for ``cost_calls`` + ``cost_events`` ledger writes.

Shared by inference ``proxy_spend`` (per-call + materialize per-run), cloud
in-process call metering (also materializes per-run), main-turn finalize
reconcile, and handoff job persistence. Request / finalize path may write
synchronously; on failure the caller enqueues here. A background drain writes
via the **telemetry** pool so spend never contends with content-write
connections (as-built: 成本配额 §三).

Idempotency: call details use stable ``call_id``; run aggregates use ``run_id``.
``CostEventRepository`` uses ``ON CONFLICT DO NOTHING`` (orphan finalize rows)
or ``DO UPDATE`` (call materialize / message reconcile), so drain retries never
double-bill.

Deployment constraint (single-process):
    Queue files live under ``{data_dir}/telemetry/cost_ledger_queue/``.
    Legacy ``proxy_spend_queue/`` leftovers are also drained once.
    **Before multi-worker / multi-instance deployment, migrate this queue to
    Redis or a DB outbox** — a process-local disk queue would otherwise drop
    or double-consume across workers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentcore.config import settings
from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.core.types import new_id

logger = get_logger(__name__)

_QUEUE_SUBDIR = Path("telemetry") / "cost_ledger_queue"
_LEGACY_PROXY_SUBDIR = Path("telemetry") / "proxy_spend_queue"
_DRAIN_IDLE_WAIT_S = 0.05
_DRAIN_RETRY_BACKOFF_S = 0.05


def _queue_dir() -> Path:
    return Path(settings.data_dir) / _QUEUE_SUBDIR


def _legacy_proxy_dir() -> Path:
    return Path(settings.data_dir) / _LEGACY_PROXY_SUBDIR


def _record_path(record_id: str) -> Path:
    return _queue_dir() / f"{record_id}.json"


class CostLedgerQueue:
    """Process-local durable queue + single drain consumer for ledger writes."""

    def __init__(self) -> None:
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def enqueue_runs(
        self,
        *,
        user_id: str,
        conversation_id: str,
        runs: list[dict[str, Any]],
        message_id: str | None = None,
        trace_id: str | None = None,
        source: str = "turn",
    ) -> str | None:
        """Persist priced run aggregates to disk and wake the drain. Returns record id.

        ``runs`` must already carry stable ``run_id`` keys (asdict(RunCost) shape)
        so retries reuse the same idempotency key. Returns ``None`` when there is
        no conversation or no runs (cannot satisfy ledger constraints).
        """
        return self._enqueue(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            trace_id=trace_id,
            source=source,
            runs=runs,
            calls=None,
            materialize_runs=False,
        )

    def enqueue_calls(
        self,
        *,
        user_id: str,
        conversation_id: str,
        calls: list[dict[str, Any]],
        message_id: str | None = None,
        trace_id: str | None = None,
        source: str = "proxy_spend",
        materialize_runs: bool = True,
    ) -> str | None:
        """Persist priced call details (and optionally materialize per-run aggregates).

        ``calls`` must carry stable ``call_id`` keys so drain retries never
        double-insert. When ``materialize_runs`` is true the drain re-aggregates
        ``cost_events`` from ``cost_calls`` for the touched run ids (proxy path).
        """
        return self._enqueue(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            trace_id=trace_id,
            source=source,
            runs=None,
            calls=calls,
            materialize_runs=materialize_runs,
        )

    def _enqueue(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_id: str | None,
        trace_id: str | None,
        source: str,
        runs: list[dict[str, Any]] | None,
        calls: list[dict[str, Any]] | None,
        materialize_runs: bool,
    ) -> str | None:
        if not conversation_id:
            logger.warning(
                "cost.ledger_enqueue_no_conversation",
                user_id=user_id,
                source=source,
            )
            return None
        if not runs and not calls:
            return None

        record_id = new_id()
        payload: dict[str, Any] = {
            "id": record_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "trace_id": trace_id,
            "source": source,
            "runs": runs or [],
            "calls": calls or [],
            "materialize_runs": materialize_runs,
            "enqueued_at": datetime.now(UTC).isoformat(),
        }
        path = _record_path(record_id)
        tmp = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            logger.error(
                "cost.ledger_enqueue_failed",
                user_id=user_id,
                conversation_id=conversation_id,
                source=source,
                error=str(e),
            )
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                logger.error(
                    "cost.ledger_enqueue_tmp_cleanup_failed",
                    path=str(tmp),
                )
            return None

        run_id = None
        if runs:
            run_id = (runs[0] or {}).get("run_id")
        elif calls:
            run_id = (calls[0] or {}).get("run_id")
        logger.info(
            "cost.ledger_enqueued",
            record_id=record_id,
            run_id=run_id,
            conversation_id=conversation_id,
            source=source,
            run_count=len(runs or []),
            call_count=len(calls or []),
        )
        self._wake.set()
        return record_id

    def start(self) -> None:
        """Start the background drain (idempotent). Call from app lifespan."""
        if self.running:
            return
        self._stopping = False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("cost.ledger_drainer_no_loop")
            return
        self._task = loop.create_task(self._drain_loop(), name="cost_ledger_drain")
        self._wake.set()  # pick up leftover files from a prior process exit
        logger.debug("cost.ledger_drainer_started", queue_dir=str(_queue_dir()))

    async def stop(self) -> None:
        """Drain remaining files once, then cancel the loop (app shutdown)."""
        self._stopping = True
        self._wake.set()
        if self._task is None:
            await self.drain_once()
            return
        try:
            await self.drain_once()
        finally:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.debug("cost.ledger_drainer_stopped")

    def _pending_paths(self) -> list[Path]:
        paths: list[Path] = []
        for directory in (_queue_dir(), _legacy_proxy_dir()):
            if directory.exists():
                paths.extend(sorted(directory.glob("*.json")))
        return paths

    async def drain_once(self) -> int:
        """Process every pending file once. Returns successful write count.

        Failed writes leave the file in place for the next attempt (at-least-once).
        """
        written = 0
        for path in self._pending_paths():
            ok = await self._drain_file(path)
            if ok:
                written += 1
        return written

    async def _drain_loop(self) -> None:
        while not self._stopping:
            try:
                written = await self.drain_once()
            except Exception:  # noqa: BLE001 — loop must survive; next wake retries
                logger.exception("cost.ledger_drain_loop_error")
                written = 0
            if written == 0:
                self._wake.clear()
                if self._pending_paths():
                    continue
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=_DRAIN_IDLE_WAIT_S)
                except TimeoutError:
                    continue
            else:
                await asyncio.sleep(0)

    async def _drain_file(self, path: Path) -> bool:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(
                "cost.ledger_record_corrupt",
                path=str(path),
                error=str(e),
            )
            poison = path.with_suffix(".corrupt")
            try:
                os.replace(path, poison)
            except OSError:
                logger.error(
                    "cost.ledger_corrupt_quarantine_failed",
                    path=str(path),
                )
            return False

        user_id = payload.get("user_id")
        conversation_id = payload.get("conversation_id")
        runs = payload.get("runs") or []
        calls = payload.get("calls") or []
        if not user_id or not conversation_id or (not runs and not calls):
            logger.error(
                "cost.ledger_record_invalid",
                path=str(path),
                record_id=payload.get("id"),
            )
            poison = path.with_suffix(".corrupt")
            try:
                os.replace(path, poison)
            except OSError:
                logger.error(
                    "cost.ledger_corrupt_quarantine_failed",
                    path=str(path),
                )
            return False

        trace_id = payload.get("trace_id")
        message_id = payload.get("message_id")
        source = payload.get("source") or "unknown"
        materialize_runs = bool(payload.get("materialize_runs"))
        with log_context(trace_id=trace_id, conversation_id=conversation_id):
            try:
                from agentcore.db.base import telemetry_session_factory
                from agentcore.db.repositories import CostEventRepository

                async with telemetry_session_factory() as session:
                    repo = CostEventRepository(session)
                    if calls:
                        await repo.record_calls(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=message_id,
                            calls=calls,
                            trace_id=trace_id,
                            materialize_runs=materialize_runs,
                        )
                    if runs:
                        await repo.record_runs(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=message_id,
                            runs=runs,
                            trace_id=trace_id,
                        )
            except Exception as e:
                run_id = None
                if runs:
                    run_id = (runs[0] or {}).get("run_id")
                elif calls:
                    run_id = (calls[0] or {}).get("run_id")
                logger.warning(
                    "cost.ledger_drain_failed",
                    user_id=user_id,
                    conversation_id=conversation_id,
                    record_id=payload.get("id"),
                    run_id=run_id,
                    source=source,
                    error=str(e),
                )
                await asyncio.sleep(_DRAIN_RETRY_BACKOFF_S)
                return False

        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.error(
                "cost.ledger_ack_failed",
                path=str(path),
                record_id=payload.get("id"),
                error=str(e),
            )
            return True

        run_id = None
        if runs:
            run_id = (runs[0] or {}).get("run_id")
        elif calls:
            run_id = (calls[0] or {}).get("run_id")
        logger.info(
            "cost.ledger_drained",
            record_id=payload.get("id"),
            run_id=run_id,
            conversation_id=conversation_id,
            source=source,
            run_count=len(runs),
            call_count=len(calls),
        )
        return True


_default_queue: CostLedgerQueue | None = None


def get_cost_ledger_queue() -> CostLedgerQueue:
    """Process-wide queue singleton (created lazily)."""
    global _default_queue
    if _default_queue is None:
        _default_queue = CostLedgerQueue()
    return _default_queue


def reset_cost_ledger_queue_for_tests() -> CostLedgerQueue:
    """Replace the singleton (tests only)."""
    global _default_queue
    _default_queue = CostLedgerQueue()
    return _default_queue

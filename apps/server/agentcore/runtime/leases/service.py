"""Process-local lease helpers: owner id, acquire / heartbeat / release."""

from __future__ import annotations

import asyncio
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.db.base import async_session_factory
from agentcore.runtime.leases.repo import TurnLeaseRepository

logger = get_logger(__name__)

# Minted once per process — durable leases identify this worker.
_OWNER_ID: str = new_id()


def lease_owner_id() -> str:
    """This process's lease owner id (stable for the process lifetime)."""
    return _OWNER_ID


async def acquire_turn_lease(
    *,
    message_id: str,
    conversation_id: str,
    user_id: str,
    phase: str = "running",
    meta: dict[str, Any] | None = None,
) -> str:
    """Write / refresh the durable RUNNING lease; returns owner_id."""
    owner = _OWNER_ID
    try:
        async with async_session_factory() as session:
            await TurnLeaseRepository(session).upsert(
                message_id=message_id,
                conversation_id=conversation_id,
                user_id=user_id,
                owner_id=owner,
                phase=phase,
                meta=meta,
            )
    except Exception as e:  # noqa: BLE001 — lease must never block the turn
        logger.warning(
            "turn_lease.acquire_failed",
            message_id=message_id,
            error=str(e),
        )
    return owner


async def heartbeat_turn_lease(
    message_id: str,
    *,
    owner_id: str | None = None,
    phase: str | None = None,
) -> bool:
    """Bump the lease heartbeat; returns False if ownership was lost."""
    owner = owner_id or _OWNER_ID
    try:
        async with async_session_factory() as session:
            return await TurnLeaseRepository(session).heartbeat(
                message_id, owner_id=owner, phase=phase
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "turn_lease.heartbeat_failed",
            message_id=message_id,
            error=str(e),
        )
        return False


async def release_turn_lease(
    message_id: str,
    *,
    owner_id: str | None = None,
) -> None:
    """Clear the durable lease (terminal / pause / stop)."""
    owner = owner_id or _OWNER_ID
    try:
        async with async_session_factory() as session:
            await TurnLeaseRepository(session).release(message_id, owner_id=owner)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "turn_lease.release_failed",
            message_id=message_id,
            error=str(e),
        )


async def orphan_turn_lease(
    message_id: str,
    *,
    owner_id: str | None = None,
) -> None:
    """Keep the lease as a sweeper crime-scene after true hard kill / crash.

    Unlike :func:`release_turn_lease`, this must not delete the row — a hard kill
    without lifespan salvage (SIGKILL / crash) otherwise leaves no expired lease
    for recover. Graceful lifespan shutdown must not call this — it interrupt-closes
    and :func:`release_turn_lease` instead.
    """
    owner = owner_id or _OWNER_ID
    try:
        async with async_session_factory() as session:
            ok = await TurnLeaseRepository(session).mark_orphaned(
                message_id, owner_id=owner
            )
        if ok:
            logger.info("turn_lease.orphaned", message_id=message_id, owner_id=owner)
        else:
            logger.warning(
                "turn_lease.orphan_miss",
                message_id=message_id,
                owner_id=owner,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "turn_lease.orphan_failed",
            message_id=message_id,
            error=str(e),
        )


async def lease_heartbeat_loop(
    message_id: str,
    *,
    owner_id: str,
    interval_seconds: float,
    stop: asyncio.Event,
    phase: str = "running",
) -> None:
    """Background heartbeat until ``stop`` is set (cancelled cleanly on shutdown)."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            return
        except TimeoutError:
            ok = await heartbeat_turn_lease(message_id, owner_id=owner_id, phase=phase)
            if not ok:
                logger.warning(
                    "turn_lease.ownership_lost",
                    message_id=message_id,
                    owner_id=owner_id,
                )
                return

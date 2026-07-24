"""``turn_stream_state`` repository (流式回复持久化 §3.1 · P0 契约 / P1 writer).

UPSERT store for in-flight stream-channel snapshots. Same-generation text is
monotonic (length only grows); a higher ``generation`` may clear and restart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models.runs import TurnStreamStateRow


def resolve_stream_upsert(
    *,
    existing_text: str | None,
    existing_generation: int | None,
    incoming_text: str,
    incoming_generation: int,
) -> tuple[str, int] | None:
    """Decide the stored ``(text, generation)`` after an upsert attempt.

    Returns ``None`` when the incoming snapshot must be rejected (stale generation,
    or same-generation shorter text). A higher generation always wins (reset may
    clear to empty). Mirrors the SQL ``ON CONFLICT … WHERE`` gate in
    :meth:`TurnStreamStateRepository.upsert`.
    """
    if existing_generation is None:
        return incoming_text, incoming_generation
    if incoming_generation > existing_generation:
        return incoming_text, incoming_generation
    if incoming_generation < existing_generation:
        return None
    if len(incoming_text) >= len(existing_text or ""):
        return incoming_text, incoming_generation
    return None


class TurnStreamStateRepository:
    """Durable in-flight stream-channel snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _upsert_one(
        self,
        *,
        turn_id: str,
        channel: str,
        text: str,
        generation: int,
        now: datetime,
    ) -> bool:
        insert_stmt = pg_insert(TurnStreamStateRow).values(
            turn_id=turn_id,
            channel=channel,
            text=text,
            generation=generation,
            updated_at=now,
        )
        excluded = insert_stmt.excluded
        accept = or_(
            excluded.generation > TurnStreamStateRow.generation,
            and_(
                excluded.generation == TurnStreamStateRow.generation,
                func.length(excluded.text) >= func.length(TurnStreamStateRow.text),
            ),
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["turn_id", "channel"],
            set_={
                "text": excluded.text,
                "generation": excluded.generation,
                "updated_at": now,
            },
            where=accept,
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0

    async def upsert(
        self,
        *,
        turn_id: str,
        channel: str,
        text: str,
        generation: int = 0,
    ) -> bool:
        """UPSERT one channel snapshot under monotonic / generation-reset rules.

        Returns ``True`` when a row was inserted or updated, ``False`` when the
        incoming snapshot was rejected (stale generation or same-gen shorter text).
        """
        now = datetime.now(UTC)
        accepted = await self._upsert_one(
            turn_id=turn_id,
            channel=channel,
            text=text,
            generation=generation,
            now=now,
        )
        await self._session.commit()
        return accepted

    async def upsert_many(
        self,
        *,
        turn_id: str,
        segments: Sequence[tuple[str, str, int]],
    ) -> int:
        """UPSERT many channels for one turn in a single transaction.

        Each segment is ``(channel, text, generation)``. Returns the number of
        accepted inserts/updates (rejected shorter/stale gens are skipped).
        """
        if not segments:
            return 0
        now = datetime.now(UTC)
        accepted = 0
        for channel, text, generation in segments:
            if await self._upsert_one(
                turn_id=turn_id,
                channel=channel,
                text=text,
                generation=generation,
                now=now,
            ):
                accepted += 1
        await self._session.commit()
        return accepted

    async def list_for_turn(self, turn_id: str) -> Sequence[TurnStreamStateRow]:
        """All channel snapshots for a turn (empty when none / already cleared)."""
        result = await self._session.execute(
            select(TurnStreamStateRow)
            .where(TurnStreamStateRow.turn_id == turn_id)
            .order_by(TurnStreamStateRow.channel.asc())
        )
        return result.scalars().all()

    async def list_for_turns(
        self, turn_ids: Sequence[str]
    ) -> dict[str, list[TurnStreamStateRow]]:
        """Batch-load channel snapshots keyed by ``turn_id`` (empty lists omitted)."""
        if not turn_ids:
            return {}
        result = await self._session.execute(
            select(TurnStreamStateRow)
            .where(TurnStreamStateRow.turn_id.in_(list(turn_ids)))
            .order_by(TurnStreamStateRow.turn_id.asc(), TurnStreamStateRow.channel.asc())
        )
        out: dict[str, list[TurnStreamStateRow]] = {}
        for row in result.scalars().all():
            out.setdefault(row.turn_id, []).append(row)
        return out

    async def delete_for_turn(self, turn_id: str) -> int:
        """Drop every channel row for ``turn_id`` (post-finalize / salvage / pause).

        Call only after the terminal / pause snapshot has been written successfully
        (时序不变量 §3.1). Returns the number of rows removed.
        """
        result = await self._session.execute(
            delete(TurnStreamStateRow).where(TurnStreamStateRow.turn_id == turn_id)
        )
        await self._session.commit()
        return result.rowcount or 0

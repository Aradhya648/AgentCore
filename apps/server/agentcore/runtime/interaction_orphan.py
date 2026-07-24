"""Orphan 热路 pending 交互（提问确认交互统一 P1 · D6）.

四触发点：
1. turn 结束 finally（防御性）
2. lease sweeper / 启动恢复（先 orphan 再 recover）
3. resolve 端点兜底（journal 有 required、无 Future → 410）
4. regenerate / retry-failed / stop

规则：只 orphan 热路四 kind；``awaiting=ceo`` 不 orphan；断连 Future 存活不 orphan。
"""

from __future__ import annotations

from typing import Any

from agentcore.core.logging import get_logger
from agentcore.runtime.events import interaction_orphaned
from agentcore.runtime.interaction import InteractionKind, default_interaction_registry
from agentcore.runtime.journal.pending_interactions import (
    PendingInteraction,
    fold_pending_interactions,
)
from agentcore.runtime.settlement import prewrite_settlement, prewrite_settlement_direct

logger = get_logger(__name__)

HOT_ORPHAN_KINDS: frozenset[str] = frozenset(
    {
        InteractionKind.APPROVAL.value,
        InteractionKind.DELEGATION_AUTHORIZATION.value,
        InteractionKind.ESCALATION.value,
    }
)


def _should_orphan_pending(pending: PendingInteraction) -> bool:
    if pending.kind not in HOT_ORPHAN_KINDS:
        return False
    return not (
        pending.kind == InteractionKind.ESCALATION.value
        and pending.payload.get("awaiting") == "ceo"
    )


async def emit_orphan_fact(
    *,
    interaction_id: str,
    kind: str,
    turn_id: str | None = None,
    conversation_id: str | None = None,
    trace_id: str | None = None,
    prefer_direct: bool = False,
    reason: str | None = None,
) -> None:
    """Write ``interaction_orphaned`` (settlement 预写路径；失败只记日志不抛)."""
    event = interaction_orphaned(
        interaction_id=interaction_id, kind=kind, reason=reason
    )
    try:
        if prefer_direct and turn_id and conversation_id:
            await prewrite_settlement_direct(
                turn_id=turn_id,
                conversation_id=conversation_id,
                trace_id=trace_id,
                event=event,
            )
            return
        written = await prewrite_settlement(event)
        if not written and turn_id and conversation_id:
            await prewrite_settlement_direct(
                turn_id=turn_id,
                conversation_id=conversation_id,
                trace_id=trace_id,
                event=event,
            )
    except Exception as e:  # noqa: BLE001 — orphan 不得阻断主路径
        logger.warning(
            "interaction.orphan_write_failed",
            interaction_id=interaction_id,
            kind=kind,
            error=str(e),
        )


async def orphan_registry_pending(
    conversation_id: str,
    *,
    turn_id: str | None = None,
    trace_id: str | None = None,
) -> list[str]:
    """Orphan in-process hot pending for a conversation (turn-end / stop).

    Discards registry entries after writing orphan facts. Returns orphaned ids.
    Does NOT cancel Futures with a result — callers that stop the turn cancel the
    task; this only marks journal + clears registry so recovery won't show fake cards.
    """
    registry = default_interaction_registry()
    orphaned: list[str] = []
    for req in list(registry.list_pending(conversation_id)):
        kind = req.kind.value
        if kind not in HOT_ORPHAN_KINDS:
            continue
        if kind == InteractionKind.ESCALATION.value and (req.payload or {}).get(
            "awaiting"
        ) == "ceo":
            continue
        await emit_orphan_fact(
            interaction_id=req.id,
            kind=kind,
            turn_id=turn_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
        )
        # Cancel unsettled future so awaiters don't hang if turn teardown is slow.
        if not req.future.done():
            req.future.cancel()
        registry.discard(req.id)
        orphaned.append(req.id)
    if orphaned:
        logger.info(
            "interaction.orphaned_registry",
            conversation_id=conversation_id,
            count=len(orphaned),
            ids=orphaned,
        )
    return orphaned


async def orphan_journal_pending(
    *,
    turn_id: str,
    conversation_id: str,
    entries: list[dict[str, Any]],
    trace_id: str | None = None,
) -> list[str]:
    """Orphan journal-fold pending for a turn (lease recover / resolve兜底)."""
    pending = fold_pending_interactions(entries, message_id=turn_id)
    orphaned: list[str] = []
    for item in pending:
        if not _should_orphan_pending(item):
            continue
        # Future 仍在 → 断连≠失效，跳过
        registry = default_interaction_registry()
        live = registry.get(item.id)
        if live is not None and not live.future.done():
            continue
        await emit_orphan_fact(
            interaction_id=item.id,
            kind=item.kind,
            turn_id=turn_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            prefer_direct=True,
        )
        orphaned.append(item.id)
    if orphaned:
        logger.info(
            "interaction.orphaned_journal",
            turn_id=turn_id,
            count=len(orphaned),
            ids=orphaned,
        )
    return orphaned


async def orphan_turn_before_recover(
    *,
    turn_id: str,
    conversation_id: str,
    trace_id: str | None = None,
) -> list[str]:
    """Lease sweeper 入口：先 orphan 该 turn 热路 pending，再由调用方 recover."""
    from agentcore.db.base import async_session_factory
    from agentcore.db.repositories import TurnJournalRepository

    async with async_session_factory() as db:
        entries = await TurnJournalRepository(db).load(turn_id)
    return await orphan_journal_pending(
        turn_id=turn_id,
        conversation_id=conversation_id,
        entries=entries,
        trace_id=trace_id,
    )

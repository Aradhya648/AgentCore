"""跨回合同图追加：复用既有 execution_id，生长事件续写宿主 turn journal。

与同回合二次 ``delegate``（协调 session merge）正交。跨回合时宿主协调会话
通常已收口（异步团队模型下 teardown 只清 idle session；仍活跃的后台 drive 由
detached finally 收口，见 ``coordination/session.py``）——若追加时宿主 session
仍活跃，``try_start_coordination`` 走 merge 路径复用之；否则本模块负责
(1) 解析宿主助手消息、(2) 合并旧计划、(3) 把生长类 DURABLE 事件 divert 到
宿主 ``turn_id`` journal。

``continue_from_run_id``（唤回 worker 会话记忆）与本机制正交，互不改写。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.runtime.events.types import EventType
from agentcore.runtime.journal.writer import TurnJournalWriter

logger = get_logger(__name__)

# execution_id → host assistant message_id（进程内；首张 run_plan 登记，DB 冷查兜底）
_host_by_execution: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class GraphAppendRedirect:
    """Active divert: growth DURABLE facts append to the host turn's journal."""

    execution_id: str
    host_message_id: str
    append_message_id: str
    host_writer: TurnJournalWriter


current_graph_append_redirect: ContextVar[GraphAppendRedirect | None] = ContextVar(
    "current_graph_append_redirect", default=None
)

# DURABLE kinds that belong on the host graph journal during an append divert.
_GROWTH_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.RUN_PLAN,
        EventType.RUN_STARTED,
        EventType.RUN_CONTEXT,
        EventType.RUN_COMPLETED,
        EventType.RUN_FAILED,
        EventType.RUN_CANCELLED,
        EventType.RUN_SKIPPED,
        EventType.RUN_PROGRESS,
        EventType.BATCH_METRICS,
        EventType.PLAN_REVISED,
        EventType.TEAM_NOTE_POSTED,
        EventType.TEAM_SYNTHESIS_PREVIEW,
        EventType.DELIVERY_STATUS,
        EventType.RUN_ESCALATION,
        EventType.ESCALATION_REQUIRED,
        EventType.ESCALATION_RESOLVED,
        EventType.USER_INTERJECTION,
        EventType.EXECUTION_DETACHED,
        EventType.EXECUTION_COMPLETED,
        # 批 A2：辩论新幕生长时逐轮/收场 DURABLE 续写宿主 journal（契约形状不变）。
        EventType.DEBATE_ROUND_STARTED,
        EventType.DEBATE_ROUND,
        EventType.DEBATE_RESULT,
        EventType.DEBATE_PRETRIAL_STARTED,
        EventType.DEBATE_PRETRIAL_ORDERS,
        EventType.DEBATE_PRETRIAL_PROGRESS,
        EventType.DEBATE_PRETRIAL_COMPLETED,
    }
)


def register_graph_host(execution_id: str, host_message_id: str) -> None:
    """Remember which assistant message owns ``execution_id`` (first run_plan wins)."""
    eid = (execution_id or "").strip()
    mid = (host_message_id or "").strip()
    if not eid or not mid:
        return
    _host_by_execution.setdefault(eid, mid)


def clear_graph_host_registry() -> None:
    """Test helper: drop the process-local host map."""
    _host_by_execution.clear()


def peek_graph_host(execution_id: str) -> str | None:
    eid = (execution_id or "").strip()
    return _host_by_execution.get(eid) if eid else None


def is_graph_growth_event(event_type: EventType, payload: dict[str, Any]) -> bool:
    """True when this DURABLE fact should divert to the host journal under redirect."""
    if event_type is EventType.GRAPH_APPEND:
        return False
    if event_type in (EventType.TOOL_USE_START, EventType.TOOL_USE_END):
        # Worker-scoped tools ride the host graph; CEO orchestration tools stay on the
        # appending turn (anchor / tool card).
        return bool(payload.get("run_id"))
    return event_type in _GROWTH_EVENT_TYPES


async def resolve_host_message_id(
    *,
    conversation_id: str,
    execution_id: str,
) -> str | None:
    """Resolve the assistant message that owns ``execution_id``.

    Order: process-local registry → Postgres ``turn_journal`` scan.
    """
    cached = peek_graph_host(execution_id)
    if cached:
        return cached
    eid = (execution_id or "").strip()
    cid = (conversation_id or "").strip()
    if not eid or not cid:
        return None
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            found = await repo.find_turn_id_for_execution(
                conversation_id=cid, execution_id=eid
            )
            if found:
                register_graph_host(eid, found)
            return found
    except Exception as exc:  # noqa: BLE001 — resolve miss is a soft reject for CEO
        logger.warning(
            "graph_append.host_resolve_failed",
            execution_id=eid,
            conversation_id=cid,
            error=str(exc),
        )
        return None


async def resolve_latest_appendable_execution(
    *,
    conversation_id: str,
    exclude_message_id: str | None = None,
) -> str | None:
    """Resolve ``append_to_execution_id="latest"``: the conversation's newest appendable graph.

    可追加 = 本对话内、``plan_type='multi_agent'`` 的团队协作图（辩论图不可追加）；宿主消息
    可解析、plan_snapshot 可合并等深校验仍由既有精确-id 追加路径把关。``exclude_message_id``
    排除当前回合（同回合合并无需本参数）。``None`` = 无候选或查询失败——调用方必须把失败
    显式回给 CEO，禁止静默新建图。
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            resolved = await repo.find_latest_multi_agent_execution(
                conversation_id=cid,
                exclude_turn_id=(exclude_message_id or "").strip() or None,
            )
        logger.info(
            "delegate.graph_append_latest",
            conversation_id=cid,
            resolved=resolved,
        )
        return resolved
    except Exception as exc:  # noqa: BLE001 — resolve miss → None；tool 层自动降级新建
        logger.warning(
            "delegate.graph_append_latest",
            conversation_id=cid,
            resolved=None,
            error=str(exc),
        )
        return None


async def resolve_latest_mlr_execution(*, conversation_id: str) -> str | None:
    """Newest MLR-shaped ``multi_agent`` execution (含 ``synthesizer`` run) in the conversation.

    批 A2 辩论进宿主图专用：不排除当前回合（同回合 MLR→开辩须命中本回合宿主）。
    分层：SQL synthesizer 形态优先 → 与 ``graph_append_latest`` 同池的 multi_agent
    候选再经 journal ``synthesizer_run_id`` 复核（对齐两套宿主查找，避免「appendable
    找得到、MLR 找不到」）。
    ``None`` = 无候选或查询失败——调用方回落独立辩论图。
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository
        from agentcore.runtime.kickoff.debate_host import synthesizer_run_id

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            resolved = await repo.find_latest_mlr_execution(conversation_id=cid)
            via = "mlr_sql"
            if not resolved:
                # 与 appendable 同池：最近 multi_agent 图 + journal 汇总员形态复核。
                candidate = await repo.find_latest_multi_agent_execution(
                    conversation_id=cid
                )
                if candidate:
                    host_mid = await resolve_host_message_id(
                        conversation_id=cid, execution_id=candidate
                    )
                    if host_mid:
                        entries = await repo.load(host_mid)
                        if synthesizer_run_id(entries):
                            resolved = candidate
                            via = "appendable_journal"
        logger.info(
            "debate.mlr_host_resolve",
            conversation_id=cid,
            resolved=resolved,
            via=via if resolved else "none",
        )
        return resolved
    except Exception as exc:  # noqa: BLE001 — miss → independent debate graph
        logger.warning(
            "debate.mlr_host_resolve",
            conversation_id=cid,
            resolved=None,
            error=str(exc),
        )
        return None


async def load_host_journal_entries(host_message_id: str) -> list[dict[str, Any]]:
    """Load host turn journal entries (``[]`` on miss / no DB)."""
    mid = (host_message_id or "").strip()
    if not mid:
        return []
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            return await repo.load(mid)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_append.host_journal_load_failed",
            host_message_id=mid,
            error=str(exc),
        )
        return []


# CEO-only volatile-tail note (跨回合可见回显通道): history replays only user/assistant
# text, so the tool-result echo alone would be dropped next turn. This block rides the
# CEO system prompt's volatile tail (assemble.py) — never the shared worker base.
_RECENT_GRAPH_TEMPLATE = """<recent_team_graph>
本对话最近一张协作图（团队执行）execution_id=`{execution_id}`。用户显式要求往这支团队继续加人 / \
接着干时，delegate 可传 append_to_execution_id="latest"（引擎自动解析到它）或直接传上述精确 id\
（多图并存时以显式 id 优先）；新任务默认仍新建图。
</recent_team_graph>"""


async def build_recent_graph_context(
    *,
    conversation_id: str,
    exclude_message_id: str | None = None,
) -> str:
    """The ``<recent_team_graph>`` prompt note, or ``""`` when the conversation has no graph."""
    execution_id = await resolve_latest_appendable_execution(
        conversation_id=conversation_id,
        exclude_message_id=exclude_message_id,
    )
    if not execution_id:
        return ""
    return _RECENT_GRAPH_TEMPLATE.format(execution_id=execution_id)


async def open_host_journal_writer(
    *,
    host_message_id: str,
    conversation_id: str,
    trace_id: str | None,
) -> TurnJournalWriter:
    """Mint a writer that continues appending to an already-finished host turn."""
    initial_seq = 0
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            max_seq = await repo.max_seq(host_message_id)
            if max_seq is not None:
                initial_seq = max_seq + 1
    except Exception as exc:  # noqa: BLE001 — tests / no DB: soft seq from 0
        logger.info(
            "graph_append.host_writer_seq_fallback",
            host_message_id=host_message_id,
            error=str(exc),
        )
    return TurnJournalWriter(
        turn_id=host_message_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
        initial_seq=initial_seq,
    )


async def load_host_plan_and_completed(
    host_message_id: str,
) -> tuple[Any | None, dict[str, Any]]:
    """Load host ``RunPlan`` + completed seed from the host turn journal."""
    from agentcore.runtime.journal.fold import completed_from_journal, plan_from_journal

    entries: list[dict[str, Any]] = []
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository

        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            entries = await repo.load(host_message_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_append.host_journal_load_failed",
            host_message_id=host_message_id,
            error=str(exc),
        )
        return None, {}
    plan = plan_from_journal(entries)
    completed = completed_from_journal(entries)
    return plan, completed


def bind_redirect(redirect: GraphAppendRedirect) -> Any:
    """Bind divert for the current task (and asyncio children created after)."""
    return current_graph_append_redirect.set(redirect)


def reset_redirect(token: Any) -> None:
    current_graph_append_redirect.reset(token)

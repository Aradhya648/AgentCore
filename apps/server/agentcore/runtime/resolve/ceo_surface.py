"""CEO orchestration tool surface: idle vs coordination gating.

Injection aligns with the coordination tools' execution gate
(``active_coordination``): idle chat omits replan / coordination suite;
``delegate`` + ``ask_user`` + ``debate`` stay always-on. Mid-turn promotion
(coordination starts or supervised wave yield) registers the gated tools in
place — one-time prefix-cache miss is acceptable.

Also owns COST-004 tools-surface observation (JSON chars / approx tokens) and
the coordination-period hint shown in CEO event briefs.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.tools.protocol import tool_schema_to_openai_format

if TYPE_CHECKING:
    from agentcore.tools.builtin.delegate import DelegateTool
    from agentcore.tools.registry import ToolRegistry

logger = get_logger(__name__)

COORDINATION_GATED_TOOLS: frozenset[str] = frozenset(
    {
        "replan",
        "wait",
        "update_synthesis",
        "cancel_worker",
        "resolve_escalation",
        "queue_user_message",
    }
)

COORDINATION_PERIOD_HINT = (
    "【协调期】团队正在后台执行：无需处置时调 wait（或空响应）——禁止用 delegate "
    "占位等待（同构再派会被拒绝）。可用 delegate 追加【全新角色/任务】队员"
    "（不传 append_to 即自动并入当前协作图）；确需强制追加传 force=true。"
    "其它工具：cancel_worker / update_synthesis / resolve_escalation / "
    "queue_user_message / ask_user；『计划已让出』波边界才用 replan(add=…)。"
    "全部完成后做最终合成（正文），然后退出协调。"
)

_CHARS_PER_TOKEN = 4


def coordination_surface_active(*, execution_id: str | None = None) -> bool:
    """True iff a live coordination session exists (same gate as coord tool execute)."""
    from agentcore.runtime.coordination.session import active_coordination

    session = active_coordination(execution_id)
    return session is not None and bool(session.active)


def register_coordination_surface(
    chat_tools: ToolRegistry,
    *,
    delegate_tool: DelegateTool,
    sink: Any,
    include: bool,
) -> None:
    """Register replan + coord suite when ``include`` is True."""
    if not include:
        return
    from agentcore.runtime.coordination.tools import (
        CancelWorkerTool,
        QueueUserMessageTool,
        ResolveEscalationTool,
        UpdateSynthesisTool,
        WaitTool,
    )
    from agentcore.tools.builtin.replan import ReplanTool

    if chat_tools.get_optional("replan") is None:
        chat_tools.register(ReplanTool(delegate=delegate_tool))
    if chat_tools.get_optional("wait") is None:
        chat_tools.register(WaitTool())
    if chat_tools.get_optional("update_synthesis") is None:
        chat_tools.register(UpdateSynthesisTool(sink=sink))
    if chat_tools.get_optional("cancel_worker") is None:
        chat_tools.register(CancelWorkerTool())
    if chat_tools.get_optional("resolve_escalation") is None:
        chat_tools.register(ResolveEscalationTool())
    if chat_tools.get_optional("queue_user_message") is None:
        chat_tools.register(QueueUserMessageTool(sink=sink))


def promote_coordination_surface_if_needed(chat_tools: ToolRegistry) -> bool:
    """Mid-turn: add gated tools when coordination is live or replan is executable.

    Returns True when OpenAI tool defs must be refreshed.
    """
    delegate = chat_tools.get_optional("delegate")
    if delegate is None:
        return False

    supervised = getattr(delegate, "_supervised", None) is not None
    coord = coordination_surface_active()
    if not coord and not supervised:
        return False

    from agentcore.runtime.coordination.tools import (
        CancelWorkerTool,
        QueueUserMessageTool,
        ResolveEscalationTool,
        UpdateSynthesisTool,
        WaitTool,
    )
    from agentcore.tools.builtin.replan import ReplanTool

    added: list[str] = []
    sink = getattr(delegate, "_sink", None)

    if chat_tools.get_optional("replan") is None:
        chat_tools.register(ReplanTool(delegate=delegate))  # type: ignore[arg-type]
        added.append("replan")

    if coord and sink is not None:
        if chat_tools.get_optional("wait") is None:
            chat_tools.register(WaitTool())
            added.append("wait")
        if chat_tools.get_optional("update_synthesis") is None:
            chat_tools.register(UpdateSynthesisTool(sink=sink))
            added.append("update_synthesis")
        if chat_tools.get_optional("cancel_worker") is None:
            chat_tools.register(CancelWorkerTool())
            added.append("cancel_worker")
        if chat_tools.get_optional("resolve_escalation") is None:
            chat_tools.register(ResolveEscalationTool())
            added.append("resolve_escalation")
        if chat_tools.get_optional("queue_user_message") is None:
            chat_tools.register(QueueUserMessageTool(sink=sink))
            added.append("queue_user_message")

    if added:
        logger.info(
            "ceo.tool_surface.promoted",
            added=added,
            coordination=coord,
            supervised=supervised,
        )
    return bool(added)


def observe_tools_offered(
    tools: ToolRegistry,
    *,
    scope: str,
    tool_defs: list[dict] | None = None,
) -> None:
    """COST-004: log tools-surface JSON size (observe-only; no SSE / API fields)."""
    defs = tool_defs
    if defs is None:
        defs = tools.get_openai_definitions() if tools.count > 0 else []
    if not defs:
        logger.info(
            "cost.tools_offered",
            scope=scope,
            tool_count=0,
            total_chars=0,
            approx_tokens=0,
            per_tool={},
        )
        return
    per_tool: dict[str, int] = {}
    total = 0
    for d in defs:
        name = (d.get("function") or {}).get("name") or d.get("name") or "?"
        raw = json.dumps(d, ensure_ascii=False)
        n = len(raw)
        per_tool[str(name)] = n
        total += n
    logger.info(
        "cost.tools_offered",
        scope=scope,
        tool_count=len(defs),
        total_chars=total,
        approx_tokens=total // _CHARS_PER_TOKEN,
        per_tool=per_tool,
    )


def measure_openai_tool_chars(schema: Any) -> int:
    """OpenAI-format JSON char length of one schema (tests / probes)."""
    return len(json.dumps(tool_schema_to_openai_format(schema), ensure_ascii=False))

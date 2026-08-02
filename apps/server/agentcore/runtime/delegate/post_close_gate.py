"""收口后冷开整团重派硬闸（与同图 replan 补跑闸分轨，共用 MAX_GAP_FILL_ADDS）。

检测本回合用户消息 ``origin=execution_harvest``（或工具上等价戳记）。
冷开 substantial 批：须全员点名（replaces / continue_from），条数 ≤ min(|gaps|, MAX)；
force / 非 harvest / append·同图 merge（由调用方排除）放行。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunState

DelegateTool = Any

_USER_MESSAGE_ORIGIN: ContextVar[str] = ContextVar("user_message_origin", default="")

EXECUTION_HARVEST_ORIGIN = "execution_harvest"


def bind_user_message_origin(origin: str | None) -> object:
    """Bind turn-level message origin (harvest sets ``execution_harvest``)."""
    return _USER_MESSAGE_ORIGIN.set((origin or "").strip())


def reset_user_message_origin(token: object) -> None:
    _USER_MESSAGE_ORIGIN.reset(token)  # type: ignore[arg-type]


def current_user_message_origin() -> str:
    return _USER_MESSAGE_ORIGIN.get() or ""


def resolve_user_message_origin(tool: DelegateTool | None = None) -> str:
    """Prefer tool stamp (tests / capture-at-construct); else ContextVar."""
    if tool is not None:
        stamped = getattr(tool, "_user_message_origin", None)
        if isinstance(stamped, str) and stamped.strip():
            return stamped.strip()
    return current_user_message_origin()


def is_post_close_turn(tool: DelegateTool | None = None) -> bool:
    return resolve_user_message_origin(tool) == EXECUTION_HARVEST_ORIGIN


def _session_for_tool(tool: DelegateTool) -> Any | None:
    from agentcore.runtime.coordination.session import (
        active_coordination,
        active_coordination_for_conversation,
    )

    ctx = getattr(tool, "_base_tool_context", None)
    eid = getattr(ctx, "execution_id", None) if ctx is not None else None
    if eid:
        session = active_coordination(str(eid))
        if session is not None:
            return session
    cid = str(getattr(tool, "_conversation_id", None) or "").strip()
    if cid:
        return active_coordination_for_conversation(cid)
    return None


def _completed_snapshot_for_post_close(tool: DelegateTool) -> dict[str, RunState] | None:
    """Build a FAILED/SKIPPED/COMPLETED map from the (possibly inactive) session.

    ``None`` = no session (gaps unknown). Empty dict = known empty roster.
    """
    from agentcore.runtime.runs.types import RunPhase, RunState

    session = _session_for_tool(tool)
    if session is None:
        return None
    out: dict[str, RunState] = {}
    failed = set(getattr(session, "failed_run_ids", None) or ())
    cancelled = set(getattr(session, "cancel_ids", None) or ())
    for rid in set(getattr(session, "completed_run_ids", None) or ()):
        if rid in failed:
            out[rid] = RunState(phase=RunPhase.FAILED, error="failed")
        elif rid in cancelled:
            out[rid] = RunState(phase=RunPhase.SKIPPED)
        else:
            out[rid] = RunState(phase=RunPhase.COMPLETED, content="ok")
    return out


def _node_as_add(node: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "role": getattr(node, "role", None) or "",
        "task": getattr(node, "task", None) or "",
    }
    replaces = str(getattr(node, "replaces_run_id", None) or "").strip()
    continue_from = str(getattr(node, "continue_from_run_id", None) or "").strip()
    if replaces:
        item["replaces_run_id"] = replaces
    if continue_from:
        item["continue_from_run_id"] = continue_from
    return item


def post_close_cold_open_error(tool: DelegateTool, plan: RunPlan) -> str | None:
    """Return contract reject message, or ``None`` if the cold-open is allowed."""
    from agentcore.runtime.delegate.batch_shape import is_substantial_batch
    from agentcore.runtime.runs.constants import MAX_GAP_FILL_ADDS

    if not is_post_close_turn(tool):
        return None
    if bool(getattr(tool, "_delegate_force", False)):
        return None
    if int(getattr(tool, "_depth", 0) or 0) != 0:
        return None

    nodes = list(getattr(plan, "nodes", None) or [])
    has_deps = any(bool(getattr(n, "depends_on", None)) for n in nodes)
    if not is_substantial_batch(len(nodes), has_deps):
        return None

    named = [
        n
        for n in nodes
        if str(getattr(n, "replaces_run_id", None) or "").strip()
        or str(getattr(n, "continue_from_run_id", None) or "").strip()
    ]
    if len(named) < len(nodes):
        return (
            "收口后拒绝整团重派：无缺口大扇出或未按缺口点名补跑。"
            "请综合已有产出向老板交代；若有失败/跳过缺口，"
            "用 replaces_run_id / continue_from_run_id 点名补"
            f"（单次≤{MAX_GAP_FILL_ADDS}）；真新任务可 force=true。"
        )

    completed = _completed_snapshot_for_post_close(tool)
    adds = [_node_as_add(n) for n in nodes]
    if completed is not None:
        from agentcore.runtime.delegate.supervised import _gap_fill_add_errors

        gap_errors = _gap_fill_add_errors(adds, completed)
        if gap_errors:
            return gap_errors[0]
        # 点名续摊（continue 指向已成功）不进补跑闸：仍按 MAX 限流，勿新造第二常量。
        if len(named) > MAX_GAP_FILL_ADDS:
            return (
                f"补跑一次最多追加 {MAX_GAP_FILL_ADDS} 个点名节点"
                f"（上限 {MAX_GAP_FILL_ADDS}，收到 {len(named)}）；"
                "请只点名最关键节点，分批补跑，勿整团重开"
            )
        return None

    if len(named) > MAX_GAP_FILL_ADDS:
        return (
            f"补跑一次最多追加 {MAX_GAP_FILL_ADDS} 个点名节点"
            f"（上限 {MAX_GAP_FILL_ADDS}，收到 {len(named)}）；"
            "请只点名最关键节点，分批补跑，勿整团重开"
        )
    return None

"""Source 适配层 · legacy 例外（提案 §6 问题 9）。

存量 v1 磁带在 runtime 修掉 captain 工具 display/trace 拆分之前录制，CEO 自持
``tool_use_*`` 仍带 captain 自己的 ``run_id``。渲染契约（conformance
``single_agent`` 向量）要求 CEO 自持工具走 turn-level 内联（无 run_id），否则
协作图未出现时前端只显示「正在思考」、工具活动全隐藏。

适用范围
    仅旧磁带回放（SINK 准备路径集中调用）；新录制 / 新剪辑磁带天然不带此问题。

退役条件
    存量 v1 磁带退役（提案 §6 问题 1）时一并删除本模块，勿扩散成通用投影旁路。
"""

from __future__ import annotations

from typing import Any

from agentcore.demo_tape.schema import event_type

# CEO 自持工具事件类型（与历史 player 特判集合一致）。
_CAPTAIN_TOOL_TYPES = frozenset({"tool_use_start", "tool_use_end", "tool_use_progress"})


def captain_run_id_from_events(events: list[dict[str, Any]]) -> str:
    """Turn's captain run id = first ``run_started`` with ``payload.kind=captain``."""
    for ev in events:
        if event_type(ev) == "run_started":
            p = ev.get("payload") or {}
            if p.get("kind") == "captain":
                return str(p.get("run_id") or "")
    return ""


def apply_legacy_captain_tool_run_id_strip(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip ``run_id`` from captain self-tool events (legacy v1 tape exception).

    Untouched events are returned by reference; stripped events get a fresh payload
    dict so the caller's document is never mutated. No-op when there is no captain
    run or no matching tool events.
    """
    captain_run_id = captain_run_id_from_events(events)
    if not captain_run_id:
        return events

    out: list[dict[str, Any]] = []
    changed = False
    for ev in events:
        et = event_type(ev)
        payload = ev.get("payload")
        if (
            et in _CAPTAIN_TOOL_TYPES
            and isinstance(payload, dict)
            and payload.get("run_id") == captain_run_id
        ):
            minted = dict(payload)
            minted.pop("run_id", None)
            out.append({**ev, "payload": minted})
            changed = True
        else:
            out.append(ev)
    return out if changed else events

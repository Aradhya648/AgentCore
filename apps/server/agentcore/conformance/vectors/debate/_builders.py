"""Shared debate fixture builders for conformance vectors."""

from __future__ import annotations

from agentcore.runtime.events import (
    SSEEvent,
    run_completed,
    run_context,
    run_output_delta,
    run_started,
)

from .._common import _COST, _USAGE


def _side_continue(
    run_id: str,
    *,
    parent: str,
    continues_run_id: str,
    stance: str,
    round_no: int,
    context_blocks: list[dict],
    delta: str,
    output_summary: str,
    duration_ms: int,
    side_key: str | None = None,
) -> list[SSEEvent]:
    """One debate continue_run beat (陈词续轮 / 质询 / 结辩) as SSE events.

    ``continues_run_id`` = session root (星型); ``parent`` = true parent (moderator).
    ``side_key`` defaults to ``stance`` for正反辩论（pro/con）；圆桌须显式传入。
    """
    return [
        run_started(
            run_id,
            run_id,
            parent_run_id=parent,
            continues_run_id=continues_run_id,
            stance=stance,
            group="debate:debate",
            round_no=round_no,
            side_key=side_key or stance or None,
        ),
        run_context(run_id, run_id, context_blocks),
        run_output_delta(run_id, run_id, delta),
        run_completed(
            run_id,
            run_id,
            output_summary=output_summary,
            duration_ms=duration_ms,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
    ]


def _moderator_agents_runs(
    mod: str,
    cap: str,
    task: str,
) -> tuple[list[dict], list[dict]]:
    """Host (moderator) agent + run plan entry — identical shape across debate vectors."""
    agents = [
        {
            "id": mod,
            "role": "主持人",
            "thinking": False,
        },
    ]
    runs = [
        {
            "id": mod,
            "agent_id": mod,
            "task": task,
            "depends_on": [],
            "parent_run_id": cap,
        },
    ]
    return agents, runs


def _pro_con_debater_agents() -> list[dict]:
    """Standard pro/con debater agent pair."""
    return [
        {"id": "d_pro", "role": "支持方", "thinking": True},
        {"id": "d_con", "role": "反对方", "thinking": True},
    ]


def _pro_con_debater_runs(
    mod: str,
    pro_run: str,
    con_run: str,
    *,
    pro_task: str,
    con_task: str,
    round_no: int = 1,
    group: str = "debate:debate",
) -> list[dict]:
    """Pro/con debater run plan entries under a moderator."""
    return [
        {
            "id": pro_run,
            "agent_id": "d_pro",
            "task": pro_task,
            "depends_on": [],
            "parent_run_id": mod,
            "stance": "pro",
            "group": group,
            "round": round_no,
        },
        {
            "id": con_run,
            "agent_id": "d_con",
            "task": con_task,
            "depends_on": [],
            "parent_run_id": mod,
            "stance": "con",
            "group": group,
            "round": round_no,
        },
    ]

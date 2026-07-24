"""Shared plan/agent fixtures for multi-agent conformance vectors."""

from __future__ import annotations


def _researcher_writer_agents() -> list[dict]:
    """Standard 研究员 + 撰写员 agent pair used across multi-agent vectors."""
    return [
        {"id": "w1", "role": "研究员", "thinking": True},
        {"id": "w2", "role": "撰写员", "thinking": True},
    ]


def _blocking_escalate_team() -> tuple[list[dict], list[dict]]:
    """The shared 2-worker plan: r1 (研究员) escalates; r2 (撰写员) depends on r1."""
    agents = _researcher_writer_agents()
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研选型", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写建议", "depends_on": ["r1"]},
    ]
    return agents, plan_runs

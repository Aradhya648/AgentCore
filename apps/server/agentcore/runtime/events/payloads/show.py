"""`sim.show.*` SSE wire payloads (恋综 / 节目模式)."""

from __future__ import annotations

from typing import Any

from agentcore.runtime.events.payloads._base import WirePayload


class SimShowHeartPickPayload(WirePayload):
    run_id: str
    tick: int
    from_agent_id: str
    to_agent_id: str
    public: bool
    meta: dict[str, Any] | None = None


class SimShowPairFormedPayload(WirePayload):
    run_id: str
    tick: int
    agent_a_id: str
    agent_b_id: str
    meta: dict[str, Any] | None = None


class SimShowAffectionShiftPayload(WirePayload):
    run_id: str
    tick: int
    from_agent_id: str
    to_agent_id: str
    kind: str | None = None
    note: str | None = None
    meta: dict[str, Any] | None = None


class SimShowZeroVoteAlertPayload(WirePayload):
    run_id: str
    tick: int
    agent_id: str
    streak: int | None = None
    meta: dict[str, Any] | None = None


class SimShowDeparturePayload(WirePayload):
    run_id: str
    tick: int
    agent_id: str
    reason: str | None = None
    meta: dict[str, Any] | None = None


class SimShowRevealPayload(WirePayload):
    run_id: str
    tick: int
    who_agent_id: str
    pick_agent_id: str
    note: str | None = None
    meta: dict[str, Any] | None = None


class SimShowEpisodeGatePayload(WirePayload):
    run_id: str
    tick: int
    gate: str
    phase: str | None = None
    meta: dict[str, Any] | None = None

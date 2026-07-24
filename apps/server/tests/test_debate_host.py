"""批 A2：辩论进宿主图 — 判据 / 幕序号 / 回落独立图 / 进宿主图接线。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agentcore.runtime.debate.events import debate_act_payload, moderator_plan_event
from agentcore.runtime.events import EventType
from agentcore.runtime.kickoff.debate_host import (
    DebateHostAttach,
    is_mlr_synthesizer_id,
    next_act_id,
    research_chain_evidence,
    resolve_debate_host_attach,
    synthesizer_completed,
    synthesizer_run_id,
)


def test_research_chain_evidence_mirrors_research_first_inverse():
    assert research_chain_evidence([]) is False
    assert research_chain_evidence([], has_research_artifacts=True) is True
    entries = [
        {
            "kind": "tool_call",
            "payload": {
                "name": "delegate",
                "arguments": '{"playbook": "multi_lens_research"}',
                "success": True,
            },
        }
    ]
    assert research_chain_evidence(entries) is True


def test_next_act_id_defaults_and_increments():
    assert next_act_id([]) == "act-2"
    assert next_act_id(None) == "act-2"
    entries = [
        {
            "kind": "run_plan",
            "payload": {"act": {"act_id": "act-1", "kind": "multi_agent"}},
        },
        {
            "kind": "run_plan",
            "payload": {"act": {"act_id": "act-2", "kind": "debate"}},
        },
    ]
    assert next_act_id(entries) == "act-3"


def test_is_mlr_synthesizer_id_raw_and_namespaced():
    assert is_mlr_synthesizer_id("synthesizer")
    assert is_mlr_synthesizer_id("del_2468005e-cf60-4032-84e4-9eca57633098_synthesizer")
    assert is_mlr_synthesizer_id(None, "add_abc_synthesizer")
    assert not is_mlr_synthesizer_id("del_x_lens_0")
    assert not is_mlr_synthesizer_id("synthesizer_helper")  # 非后缀


def test_synthesizer_run_id_and_completed():
    entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "runs": [
                    {"id": "lens_0", "agent_id": "lens_0"},
                    {"id": "synthesizer", "agent_id": "synthesizer"},
                ],
            },
        },
        {"kind": "run_completed", "payload": {"run_id": "synthesizer"}},
    ]
    assert synthesizer_run_id(entries) == "synthesizer"
    assert synthesizer_completed(entries, "synthesizer") is True
    failed = [
        *entries[:-1],
        {"kind": "run_failed", "payload": {"run_id": "synthesizer"}},
    ]
    assert synthesizer_completed(failed, "synthesizer") is False


def test_synthesizer_run_id_matches_dag_namespaced():
    """真跑实证：DAG 铸造 del_<uuid>_synthesizer，精确匹配会漏挂宿主。"""
    rid = "del_2468005e-cf60-4032-84e4-9eca57633098_synthesizer"
    entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "execution_id": "exec_mlr",
                "runs": [
                    {
                        "id": "del_2468005e-cf60-4032-84e4-9eca57633098_lens_0",
                        "agent_id": "del_2468005e-cf60-4032-84e4-9eca57633098_lens_0",
                    },
                    {"id": rid, "agent_id": rid},
                ],
            },
        },
        {"kind": "run_completed", "payload": {"run_id": rid}},
    ]
    assert synthesizer_run_id(entries) == rid
    assert synthesizer_completed(entries, rid) is True


@pytest.mark.asyncio
async def test_resolve_debate_host_attach_fallback_no_mlr(monkeypatch):
    async def _none(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_mlr_execution",
        _none,
    )
    got = await resolve_debate_host_attach(
        conversation_id="c1",
        append_message_id="m2",
        has_research_artifacts=True,
    )
    assert got is None


@pytest.mark.asyncio
async def test_resolve_debate_host_attach_success(monkeypatch):
    host_entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "execution_id": "exec1",
                "act": {"act_id": "act-1", "kind": "multi_agent"},
                "runs": [{"id": "synthesizer", "agent_id": "synthesizer"}],
            },
        },
        {"kind": "run_completed", "payload": {"run_id": "synthesizer"}},
    ]

    async def _eid(**_kwargs: Any) -> str:
        return "exec1"

    async def _mid(**_kwargs: Any) -> str:
        return "m1"

    async def _load(_mid: str) -> list:
        return host_entries

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_mlr_execution",
        _eid,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        _mid,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_journal_entries",
        _load,
    )
    got = await resolve_debate_host_attach(
        conversation_id="c1",
        append_message_id="m2",
        has_research_artifacts=True,
    )
    assert got == DebateHostAttach(
        execution_id="exec1",
        host_message_id="m1",
        anchor_run_id="synthesizer",
        act_id="act-2",
        same_turn=False,
    )


@pytest.mark.asyncio
async def test_resolve_debate_host_attach_fallback_incomplete_synthesizer(monkeypatch):
    host_entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "runs": [{"id": "synthesizer", "agent_id": "synthesizer"}],
            },
        },
        # no run_completed
    ]

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_mlr_execution",
        AsyncMock(return_value="exec1"),
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        AsyncMock(return_value="m1"),
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_journal_entries",
        AsyncMock(return_value=host_entries),
    )
    got = await resolve_debate_host_attach(
        conversation_id="c1",
        append_message_id="m2",
        has_research_artifacts=True,
    )
    assert got is None


@pytest.mark.asyncio
async def test_resolve_debate_host_attach_namespaced_synthesizer(monkeypatch):
    """口头开辩 fallback：namespaced synthesizer 仍须附着幕1 宿主。"""
    rid = "del_2468005e-cf60-4032-84e4-9eca57633098_synthesizer"
    host_entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "execution_id": "exec1",
                "act": {"act_id": "act-1", "kind": "multi_agent"},
                "runs": [{"id": rid, "agent_id": rid}],
            },
        },
        {"kind": "run_completed", "payload": {"run_id": rid}},
    ]

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_mlr_execution",
        AsyncMock(return_value="exec1"),
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        AsyncMock(return_value="m1"),
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_journal_entries",
        AsyncMock(return_value=host_entries),
    )
    got = await resolve_debate_host_attach(
        conversation_id="c1",
        append_message_id="m2",
        has_research_artifacts=True,
    )
    assert got == DebateHostAttach(
        execution_id="exec1",
        host_message_id="m1",
        anchor_run_id=rid,
        act_id="act-2",
        same_turn=False,
    )


@pytest.mark.asyncio
async def test_resolve_latest_mlr_falls_back_to_appendable_journal(monkeypatch):
    """两套查找对齐：MLR SQL 漏检时，appendable + journal synthesizer 复核仍命中。"""
    from agentcore.runtime.delegate import graph_append as ga

    rid = "del_abc_synthesizer"
    host_entries = [
        {
            "kind": "run_plan",
            "payload": {
                "plan_type": "multi_agent",
                "execution_id": "exec_ma",
                "runs": [{"id": rid, "agent_id": rid}],
            },
        },
        {"kind": "run_completed", "payload": {"run_id": rid}},
    ]

    class _Repo:
        async def find_latest_mlr_execution(self, *, conversation_id: str):
            return None

        async def find_latest_multi_agent_execution(self, *, conversation_id: str):
            return "exec_ma"

        async def load(self, mid: str):
            assert mid == "m_host"
            return host_entries

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_a):
            return False

    import agentcore.db.base as base_mod
    import agentcore.db.repositories as repos_mod

    monkeypatch.setattr(base_mod, "async_session_factory", lambda: _CM())
    monkeypatch.setattr(repos_mod, "TurnJournalRepository", lambda _s: _Repo())
    monkeypatch.setattr(
        ga, "resolve_host_message_id", AsyncMock(return_value="m_host")
    )

    got = await ga.resolve_latest_mlr_execution(conversation_id="c1")
    assert got == "exec_ma"



def test_moderator_plan_event_independent_act_1():
    from agentcore.runtime.debate.types import DebateForm

    tool = SimpleNamespace(
        _captain_run_id="cap",
        _debate_act_id="act-1",
        _debate_act_title=None,
        _debate_anchor_run_id=None,
        _debate_host_message_id=None,
        _debate_graph_parent_run_id=None,
    )
    cfg = SimpleNamespace(form=DebateForm.DEBATE, motion="是否采用方案 A")
    ev = moderator_plan_event(tool, "e-new", "mod-1", cfg)  # type: ignore[arg-type]
    assert ev.payload["act"] == {"act_id": "act-1", "kind": "debate"}
    assert "host_message_id" not in ev.payload
    assert ev.payload["runs"][0]["parent_run_id"] == "cap"


def test_moderator_plan_event_host_act_2():
    from agentcore.runtime.debate.types import DebateForm

    tool = SimpleNamespace(
        _captain_run_id="cap",
        _debate_act_id="act-2",
        _debate_act_title="正反辩论对抗",
        _debate_anchor_run_id="synthesizer",
        _debate_host_message_id="m1",
        _debate_graph_parent_run_id="synthesizer",
    )
    cfg = SimpleNamespace(form=DebateForm.DEBATE, motion="命题")
    ev = moderator_plan_event(tool, "exec_host", "mod-1", cfg)  # type: ignore[arg-type]
    assert ev.payload["execution_id"] == "exec_host"
    assert ev.payload["host_message_id"] == "m1"
    assert ev.payload["act"] == {
        "act_id": "act-2",
        "kind": "debate",
        "title": "正反辩论对抗",
        "anchor_run_id": "synthesizer",
    }
    assert ev.payload["runs"][0]["parent_run_id"] == "synthesizer"


def test_debate_act_payload_defaults():
    tool = SimpleNamespace()
    assert debate_act_payload(tool) == {"act_id": "act-1", "kind": "debate"}


def test_is_graph_growth_includes_debate_events():
    from agentcore.runtime.delegate.graph_append import is_graph_growth_event

    assert is_graph_growth_event(EventType.DEBATE_RESULT, {"execution_id": "e"})
    assert is_graph_growth_event(EventType.DEBATE_ROUND, {"execution_id": "e"})
    assert is_graph_growth_event(EventType.DEBATE_ROUND_STARTED, {"execution_id": "e"})


def test_project_turn_mlr_debate_acts_vector():
    from agentcore.conformance.projection import project_turn
    from agentcore.conformance.vectors.multi_agent.mlr_debate_acts import (
        _multi_agent_mlr_debate_acts,
    )

    wire = [
        {"type": e.type.value, "payload": e.payload}
        for e in _multi_agent_mlr_debate_acts()
    ]
    projected = project_turn(wire)
    acts = projected.get("acts") or []
    assert len(acts) == 2
    assert acts[0]["actId"] == "act-1"
    assert acts[0]["kind"] == "multi_agent"
    assert acts[1]["actId"] == "act-2"
    assert acts[1]["kind"] == "debate"
    assert acts[1]["anchorRunId"] == "synthesizer"
    runs = {r["id"]: r for r in projected.get("runs") or []}
    assert runs["debate_mod_act2_r1_pro"]["actId"] == "act-2"
    assert runs["debate_mod_act2_r1_con"]["actId"] == "act-2"
    assert runs["synthesizer"]["actId"] == "act-1"

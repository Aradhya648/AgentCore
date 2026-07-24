"""庭前取证阶段单测：点单降级、预算对称、台账汇流、fast 档秒过。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.runtime.debate.evidence_ledger import (
    EvidenceLedger,
    preregister_turn_research_entries,
)
from agentcore.runtime.debate.pretrial import (
    SideOrder,
    auto_order_sheet,
    collect_order_sheets,
    investigator_delivery_notes,
    investigator_delivery_ok,
    investigator_task_payload,
    pad_orders_for_symmetry,
    parse_order_tasks,
    run_pretrial_phase,
    symmetric_investigator_count,
)
from agentcore.runtime.debate.types import (
    DebateConfig,
    DebateForm,
    DebateSide,
    RoundPolicy,
)
from agentcore.runtime.runs.types import RunPhase, RunState


def _config(*, thorough: bool = True) -> DebateConfig:
    return DebateConfig(
        motion="是否采用方案 A",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="支持方", stance="支持采用方案 A"),
            DebateSide(key="con", name="反对方", stance="反对采用方案 A"),
        ],
        policy=RoundPolicy(thorough=thorough, max_rounds=1 if not thorough else 5),
    )


def test_parse_order_tasks_caps_and_filters():
    tasks = parse_order_tasks(
        [
            {"query": "q1", "purpose": "p1"},
            "q2",
            {"query": ""},
            {"query": "q3"},
            {"query": "q4"},
            {"query": "q5"},
        ]
    )
    assert [t.query for t in tasks] == ["q1", "q2", "q3"]
    assert tasks[0].purpose == "p1"


def test_auto_order_sheet_uses_stance():
    side = DebateSide(key="pro", name="正方", stance="应推广")
    tasks = auto_order_sheet(side, "四天工作制")
    assert len(tasks) == 2
    assert "应推广" in tasks[0].query
    assert "四天工作制" in tasks[0].query


def test_symmetric_investigator_count_and_pad():
    orders = [
        SideOrder(side_key="pro", tasks=parse_order_tasks(["a", "b", "c"]), source="debater"),
        SideOrder(side_key="con", tasks=parse_order_tasks(["x"]), source="debater"),
    ]
    n = symmetric_investigator_count(orders)
    assert n == 2  # clamp max 2
    padded = pad_orders_for_symmetry(orders, n=n, config=_config())
    assert all(len(o.tasks) == 2 for o in padded)


def test_symmetric_count_empty_is_zero():
    orders = [
        SideOrder(side_key="pro", tasks=[], source="empty"),
        SideOrder(side_key="con", tasks=[], source="empty"),
    ]
    assert symmetric_investigator_count(orders) == 0


@pytest.mark.asyncio
async def test_collect_order_sheets_degrades_on_bad_json():
    async def bad_complete(_s: str, _u: str, _step: str) -> dict:
        return {}

    orders = await collect_order_sheets(bad_complete, _config())
    assert len(orders) == 2
    assert all(o.source == "auto" for o in orders)
    assert all(len(o.tasks) == 2 for o in orders)


@pytest.mark.asyncio
async def test_collect_order_sheets_accepts_empty_when_valid():
    async def empty_orders(_s: str, _u: str, _step: str) -> dict:
        return {"orders": {"pro": [], "con": []}}

    orders = await collect_order_sheets(empty_orders, _config())
    assert all(o.source == "empty" for o in orders)
    assert all(o.tasks == [] for o in orders)


def test_preregister_turn_research_entries_maps_r_to_e():
    led = EvidenceLedger()
    eids = preregister_turn_research_entries(
        led,
        [
            {"id": "#r1", "url": "https://a.example", "title": "A"},
            {"id": "#r2", "url": "https://b.example", "title": "B"},
            {"id": "#e9", "url": "https://skip", "title": "skip"},  # ignore
        ],
    )
    assert eids == ["#e1", "#e2"]
    assert led.get("#e1")["origin_id"] == "#r1"
    # idempotent
    eids2 = preregister_turn_research_entries(
        led, [{"id": "#r1", "url": "https://a.example", "title": "A"}]
    )
    assert eids2 == ["#e1"]
    assert len(led) == 2


@pytest.mark.asyncio
async def test_pretrial_fast_skips_without_investigators():
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0

    started: list[dict] = []
    completed: list[dict] = []

    async def on_started(p: dict) -> None:
        started.append(p)

    async def on_completed(p: dict) -> None:
        completed.append(p)

    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=_config(thorough=False),
        complete_json=AsyncMock(return_value={}),
        on_started=on_started,
        on_completed=on_completed,
    )
    assert result.skipped is True
    assert result.skip_reason == "fast"
    assert result.investigators == []
    assert started[0].get("skip_reason") == "fast"
    assert completed[0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_pretrial_dossier_sufficient_skips():
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0

    async def empty_orders(_s: str, _u: str, _step: str) -> dict:
        return {"orders": {"pro": [], "con": []}}

    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=_config(thorough=True),
        complete_json=empty_orders,
    )
    assert result.skipped is True
    assert result.skip_reason == "dossier_sufficient"
    assert result.investigators == []


@pytest.mark.asyncio
async def test_pretrial_budget_symmetry_pads_before_spawn(monkeypatch: pytest.MonkeyPatch):
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._tools = SimpleNamespace(list_all=lambda: [])
    tool._base_tool_context = SimpleNamespace(backend=MagicMock(), location="cloud")
    tool._acc = MagicMock()
    tool._llm = MagicMock()
    tool._profile_set = MagicMock()
    tool._system_prompt = ""
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    async def uneven(_s: str, _u: str, _step: str) -> dict:
        return {
            "orders": {
                "pro": [{"query": "a"}, {"query": "b"}, {"query": "c"}],
                "con": [{"query": "x"}],
            }
        }

    captured: dict = {}

    async def fake_investigators(*args, **kwargs):
        orders = kwargs["orders"]
        captured["counts"] = [len(o.tasks) for o in orders]
        captured["budget"] = kwargs["retrieval_budget"]
        from agentcore.runtime.debate.pretrial import InvestigatorOutcome

        return [
            InvestigatorOutcome(
                side_key=o.side_key,
                run_id=f"inv_{o.side_key}_{i}",
                parent_run_id=kwargs["debater_ids"][o.side_key],
                ok=False,
                task_query=t.query,
            )
            for o in orders
            for i, t in enumerate(o.tasks)
        ]

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.declare_debater_skeleton",
        lambda *a, **k: {"pro": "mod_r1_pro", "con": "mod_r1_con"},
    )

    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=_config(thorough=True),
        complete_json=uneven,
    )
    assert captured["counts"] == [2, 2]
    assert captured["budget"] == 6
    assert result.fallback_self_search is True
    assert result.evidence_ready is False


def test_investigator_delivery_accepts_handoff_summary_without_content():
    """正文空但 handoff summary 有值 → 有效交付（对齐 worker 契约）。"""
    empty = RunState(phase=RunPhase.COMPLETED, content="", debrief=None)
    assert investigator_delivery_ok(empty) is False
    assert investigator_delivery_notes(empty) == ""

    via_handoff = RunState(
        phase=RunPhase.COMPLETED,
        content="",
        debrief={"summary": "【证据笔记】判决书认定四叶花近似 LV 商标。"},
    )
    assert investigator_delivery_ok(via_handoff) is True
    assert "判决书" in investigator_delivery_notes(via_handoff)

    via_body = RunState(phase=RunPhase.COMPLETED, content="笔记正文", debrief=None)
    assert investigator_delivery_notes(via_body) == "笔记正文"


def test_investigator_task_teaches_body_notes_and_source_policy():
    cfg = _config()
    side = cfg.sides[0]
    payload = investigator_task_payload(
        config=cfg,
        side=side,
        task=parse_order_tasks(["查判决书"])[0],
        index=0,
        retrieval_budget=6,
    )
    task = payload["task"]
    assert "证据笔记写进正文交付" in task
    assert "判决书" in task or "裁判文书" in task
    assert "权威媒体" in task
    assert "词典" in task
    assert "不算证据" in task
    assert payload["group"] == f"pretrial:investigators:{side.key}"
    assert payload["search_policy"] == "debate_evidence"


@pytest.mark.asyncio
async def test_run_investigators_progress_fires_per_node_before_wave_end(
    monkeypatch: pytest.MonkeyPatch,
):
    """庭前 progress：每员完工即上报，不攒到整波结束。"""
    import asyncio

    from agentcore.runtime.debate import pretrial as pretrial_mod
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec

    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._tools = SimpleNamespace(
        list_all=lambda: [SimpleNamespace(name=n) for n in (
            "web_search", "read_url", "file_read", "file_list", "grep"
        )]
    )
    tool._base_tool_context = SimpleNamespace(
        backend=AsyncMock(), location="cloud"
    )
    tool._acc = MagicMock()
    tool._llm = MagicMock()
    tool._profile_set = MagicMock()
    tool._system_prompt = ""
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    progress_at: list[float] = []
    wave_done_at: list[float] = []

    async def on_progress(_p: dict) -> None:
        progress_at.append(asyncio.get_running_loop().time())

    # Build a tiny plan with 2 parallel nodes; slow second so first progress
    # lands before scheduler.run returns.
    async def fake_scheduler_run(self, plan, executor, **kwargs):
        on_node_done = kwargs.get("on_node_done")
        results = {}
        for i, node in enumerate(plan.nodes):
            await asyncio.sleep(0.01 if i == 0 else 0.05)
            state = RunState(
                phase=RunPhase.COMPLETED,
                content="" if i == 0 else "笔记",
                debrief={"summary": "handoff 摘要笔记"} if i == 0 else None,
            )
            results[node.run_id] = state
            if on_node_done is not None:
                await on_node_done(node.run_id, state)
        wave_done_at.append(asyncio.get_running_loop().time())
        return results

    monkeypatch.setattr(
        "agentcore.runtime.runs.wave.WaveScheduler.run",
        fake_scheduler_run,
    )

    # Avoid build_run_plan complexity: patch build pieces to yield 2 nodes.
    def fake_build_run_plan(tasks_raw, **kwargs):
        plan = RunPlan()
        for i, t in enumerate(tasks_raw):
            plan.add(
                RunSpec(
                    run_id=f"tmp_{i}",
                    task=str(t.get("task") or ""),
                    agent_id=f"tmp_{i}",
                    role=str(t.get("role") or "inv"),
                )
            )
        return plan, []

    monkeypatch.setattr(
        "agentcore.runtime.runs.build_run_plan", fake_build_run_plan
    )
    monkeypatch.setattr(
        "agentcore.runtime.runs.build_agent_executor", lambda **k: AsyncMock()
    )

    orders = [
        SideOrder(side_key="pro", tasks=parse_order_tasks(["q1"]), source="debater"),
        SideOrder(side_key="con", tasks=parse_order_tasks(["q2"]), source="debater"),
    ]
    outcomes = await pretrial_mod.run_investigators(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=_config(),
        orders=orders,
        debater_ids={"pro": "mod1_r1_pro", "con": "mod1_r1_con"},
        on_progress=on_progress,
    )
    assert len(progress_at) == 2
    assert wave_done_at and progress_at[0] < wave_done_at[0]
    assert all(o.ok for o in outcomes)
    # First investigator: empty content + handoff summary still ok + notes filled.
    assert outcomes[0].notes
    assert "handoff" in outcomes[0].notes or "摘要" in outcomes[0].notes

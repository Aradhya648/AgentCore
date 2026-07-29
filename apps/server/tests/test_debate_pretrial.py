"""庭前取证阶段单测：点单降级、预算对称、台账汇流、fast 档秒过、附件 Evidence Pack。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.runtime.debate.evidence_ledger import (
    EvidenceLedger,
    preregister_turn_research_entries,
)
from agentcore.runtime.debate.evidence_pack import (
    assemble_evidence_pack_from_host,
    parse_attached_file_sources,
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


_ATTACHED_TEXT_PROMPT = """
系统前缀…
<attached_files>
The user attached the following files as actionable inputs.

--- File: 合同.md (attachments/合同.md) ---
第一条 甲方应在签署后 30 日内支付首期款项。
第二条 争议提交仲裁委员会。
</attached_files>
"""

_ATTACHED_BINARY_ONLY_PROMPT = """
<attached_files>
--- File: report.xlsx (attachments/report.xlsx) [binary] ---
This is a binary file saved in the workspace (no text inline).
Open and parse it with code_execute using the workspace-relative path above.
</attached_files>
"""


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
    assert result.incomplete is False
    assert started[0].get("skip_reason") == "fast"
    assert completed[0]["status"] == "skipped"
    assert completed[0]["incomplete"] is False


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

    cfg = _config(thorough=True)
    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=cfg,
        complete_json=uneven,
    )
    assert captured["counts"] == [2, 2]
    from agentcore.runtime.debate.constants import DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET

    assert captured["budget"] == DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET
    assert result.fallback_self_search is True
    assert result.evidence_ready is False
    assert result.completeness == "empty"
    assert result.incomplete is True
    assert set(result.failed_sides) == {"pro", "con"}
    payload = result.to_completed_payload()
    assert payload["status"] == "degraded"
    assert payload["completeness"] == "empty"
    assert payload["incomplete"] is True
    assert set(payload["failed_sides"]) == {"pro", "con"}
    assert cfg.evidence_completeness == "empty"
    assert "庭前取证·证据不完整" in (cfg.research_dossier_index or "")


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
    assert "model" not in payload


def test_investigator_task_injects_turn_main():
    cfg = _config()
    side = cfg.sides[0]
    payload = investigator_task_payload(
        config=cfg,
        side=side,
        task=parse_order_tasks(["查判决书"])[0],
        index=0,
        retrieval_budget=6,
        turn_model="main-pro",
    )
    assert payload["model"] == "main-pro"


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


def test_parse_attached_file_sources_skips_binary_keeps_text():
    text_sources = parse_attached_file_sources(_ATTACHED_TEXT_PROMPT)
    assert len(text_sources) == 1
    assert text_sources[0].kind == "attachment"
    assert "第一条" in text_sources[0].excerpt
    assert text_sources[0].path == "attachments/合同.md"

    binary = parse_attached_file_sources(_ATTACHED_BINARY_ONLY_PROMPT)
    assert len(binary) == 1
    assert binary[0].failure == "binary_no_text"
    pack = assemble_evidence_pack_from_host(
        system_prompt=_ATTACHED_BINARY_ONLY_PROMPT,
        motion="x",
        sides=_config().sides,
    )
    assert pack is None


def test_assemble_evidence_pack_from_host_builds_disputes():
    pack = assemble_evidence_pack_from_host(
        system_prompt=_ATTACHED_TEXT_PROMPT,
        motion="是否采用方案 A",
        sides=_config().sides,
        background="已核实：首期款项条款存在。",
    )
    assert pack is not None
    assert pack.has_usable_body()
    assert pack.completeness in ("full", "partial")
    assert any(s.kind == "background" for s in pack.sources)
    assert len(pack.dispute_candidates) == 2
    wire = pack.to_wire()
    assert wire["sources"]
    assert wire["dispute_candidates"]


@pytest.mark.asyncio
async def test_pretrial_with_attachments_skips_investigators(
    monkeypatch: pytest.MonkeyPatch,
):
    """附件已在主持人上下文 → Evidence Pack 路径，不启动双调查员深挖。"""
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._system_prompt = _ATTACHED_TEXT_PROMPT

    inv_called = {"n": 0}

    async def fake_investigators(*_a, **_k):
        inv_called["n"] += 1
        return []

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    # 若误入点单路径，complete_json 会派单；pack 路径不应调用它。
    complete = AsyncMock(
        return_value={
            "orders": {
                "pro": [{"query": "深挖合同"}],
                "con": [{"query": "深挖合同"}],
            }
        }
    )

    cfg = _config(thorough=True)
    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=cfg,
        complete_json=complete,
    )
    assert inv_called["n"] == 0
    complete.assert_not_awaited()
    assert result.skipped is True
    assert result.skip_reason == "evidence_pack"
    assert result.investigators == []
    assert result.evidence_ready is True
    assert result.evidence_pack is not None
    assert result.evidence_pack.has_usable_body()
    assert result.completeness == "full"
    assert result.incomplete is False
    assert result.failed_sides == []
    assert result.external_evidence_mode == "skip"
    assert result.external_evidence_reason == "evidence_pack_full"
    assert result.retrieval_budget_per_investigator == 0
    assert cfg.pretrial_evidence_ready is True
    assert cfg.evidence_pack is not None
    assert cfg.evidence_completeness == "full"
    assert cfg.debater_retrieval_budgets == {"pro": 0, "con": 0}
    assert "共享证据包" in (cfg.research_dossier_index or "")
    assert "完整度=" in (cfg.research_dossier_index or "")
    assert len(tool._evidence_ledger) >= 1
    payload = result.to_completed_payload()
    assert payload["status"] == "skipped"
    assert payload["evidence_pack"]["sources"]
    assert payload["completeness"] == "full"
    assert payload["incomplete"] is False
    assert payload["failed_sides"] == []
    assert payload["external_evidence_mode"] == "skip"
    assert payload["external_evidence_reason"] == "evidence_pack_full"


@pytest.mark.asyncio
async def test_pretrial_partial_investigator_failure_marks_incomplete(
    monkeypatch: pytest.MonkeyPatch,
):
    """一侧调查员失败 → completeness=partial、failed_sides 显式、status=degraded。"""
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._system_prompt = ""
    tool._tools = SimpleNamespace(list_all=lambda: [])
    tool._base_tool_context = SimpleNamespace(backend=MagicMock(), location="cloud")
    tool._acc = MagicMock()
    tool._llm = MagicMock()
    tool._profile_set = MagicMock()
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    async def orders_fn(_s: str, _u: str, _step: str) -> dict:
        return {
            "orders": {
                "pro": [{"query": "正方取证"}],
                "con": [{"query": "反方取证"}],
            }
        }

    async def fake_investigators(*_a, **kwargs):
        from agentcore.runtime.debate.pretrial import InvestigatorOutcome

        return [
            InvestigatorOutcome(
                side_key="pro",
                run_id="inv_pro_0",
                parent_run_id=kwargs["debater_ids"]["pro"],
                ok=True,
                notes="正方笔记",
                task_query="正方取证",
            ),
            InvestigatorOutcome(
                side_key="con",
                run_id="inv_con_0",
                parent_run_id=kwargs["debater_ids"]["con"],
                ok=False,
                task_query="反方取证",
            ),
        ]

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.declare_debater_skeleton",
        lambda *a, **k: {"pro": "mod_r1_pro", "con": "mod_r1_con"},
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.preregister_research_dossier",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.list_research_artifact_paths",
        AsyncMock(return_value=[]),
    )

    cfg = _config(thorough=True)
    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=cfg,
        complete_json=orders_fn,
    )
    assert result.skipped is False
    assert result.completeness == "partial"
    assert result.incomplete is True
    assert result.failed_sides == ["con"]
    assert result.evidence_ready is True
    assert result.fallback_self_search is False
    payload = result.to_completed_payload()
    assert payload["status"] == "degraded"
    assert payload["failed_sides"] == ["con"]
    assert cfg.evidence_completeness == "partial"
    assert cfg.pretrial_failed_sides == ["con"]
    from agentcore.runtime.debate.constants import BOUNDED_GAP_FILL_RETRIEVAL_BUDGET

    assert cfg.debater_retrieval_budgets == {
        "pro": 0,
        "con": BOUNDED_GAP_FILL_RETRIEVAL_BUDGET,
    }
    assert "证据不完整" in (cfg.research_dossier_index or "")
    assert "完整度=partial" in (cfg.research_dossier_index or "")


def test_assemble_evidence_pack_truncated_is_partial():
    """截断附件 → pack.completeness=partial，索引带不完整标注。"""
    from agentcore.runtime.debate.evidence_pack import format_evidence_pack_index

    long_body = "条款正文。" * 400
    prompt = f"""
<attached_files>
--- File: 长约.md (attachments/长约.md) [truncated] ---
{long_body}
</attached_files>
"""
    pack = assemble_evidence_pack_from_host(
        system_prompt=prompt,
        motion="是否采用方案 A",
        sides=_config().sides,
    )
    assert pack is not None
    assert pack.completeness == "partial"
    assert any(s.failure == "truncated" for s in pack.sources)
    index = format_evidence_pack_index(pack)
    assert "完整度=partial" in index
    assert "证据不完整" in index


def test_completeness_from_investigator_outcomes_sides():
    from agentcore.runtime.debate.evidence_pack import (
        completeness_from_investigator_outcomes,
    )
    from agentcore.runtime.debate.pretrial import InvestigatorOutcome

    outcomes = [
        InvestigatorOutcome(
            side_key="pro", run_id="a", parent_run_id="p", ok=True, task_query="q"
        ),
        InvestigatorOutcome(
            side_key="con", run_id="b", parent_run_id="c", ok=False, task_query="q"
        ),
    ]
    completeness, failed = completeness_from_investigator_outcomes(outcomes)
    assert completeness == "partial"
    assert failed == ["con"]


@pytest.mark.asyncio
async def test_pretrial_binary_attachments_still_allow_investigators(
    monkeypatch: pytest.MonkeyPatch,
):
    """仅 binary 附件（无可用正文）→ 不走 pack，仍可派调查员外证。"""
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._system_prompt = _ATTACHED_BINARY_ONLY_PROMPT
    tool._tools = SimpleNamespace(list_all=lambda: [])
    tool._base_tool_context = SimpleNamespace(backend=MagicMock(), location="cloud")
    tool._acc = MagicMock()
    tool._llm = MagicMock()
    tool._profile_set = MagicMock()
    tool._system_prompt = _ATTACHED_BINARY_ONLY_PROMPT
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    async def orders_fn(_s: str, _u: str, _step: str) -> dict:
        return {
            "orders": {
                "pro": [{"query": "外网查判决"}],
                "con": [{"query": "外网查判决"}],
            }
        }

    captured: dict = {}

    async def fake_investigators(*_a, **kwargs):
        captured["orders"] = kwargs["orders"]
        from agentcore.runtime.debate.pretrial import InvestigatorOutcome

        return [
            InvestigatorOutcome(
                side_key=o.side_key,
                run_id=f"inv_{o.side_key}_{i}",
                parent_run_id=kwargs["debater_ids"][o.side_key],
                ok=True,
                task_query=t.query,
            )
            for o in kwargs["orders"]
            for i, t in enumerate(o.tasks)
        ]

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.declare_debater_skeleton",
        lambda *a, **k: {"pro": "mod_r1_pro", "con": "mod_r1_con"},
    )
    # 刷新案卷可能触达 backend；桩掉以免依赖真实工作区。
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.preregister_research_dossier",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.list_research_artifact_paths",
        AsyncMock(return_value=[]),
    )

    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=_config(thorough=True),
        complete_json=orders_fn,
    )
    assert result.skip_reason != "evidence_pack"
    assert result.skipped is False
    assert "orders" in captured
    assert len(result.investigators) >= 2


def test_resolve_external_evidence_plan_full_skips_partial_bounds():
    """完整度驱动：full 跳过外证；partial/failed 有界；预算复用残搜常量。"""
    from agentcore.runtime.debate.constants import (
        BOUNDED_GAP_FILL_RETRIEVAL_BUDGET,
        DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET,
        MAX_GAP_FILL_TASKS_PER_SIDE,
    )
    from agentcore.runtime.debate.evidence_pack import (
        debater_budgets_from_completeness,
        resolve_external_evidence_plan,
    )

    full = resolve_external_evidence_plan(
        completeness="full",
        path="evidence_pack",
        side_keys=["pro", "con"],
    )
    assert full.mode == "skip"
    assert full.allow_external is False
    assert full.retrieval_budget == 0
    assert full.reason == "evidence_pack_full"

    partial = resolve_external_evidence_plan(
        completeness="partial",
        path="evidence_pack",
        side_keys=["pro", "con"],
    )
    assert partial.mode == "gap_fill"
    assert partial.allow_external is True
    assert partial.retrieval_budget == BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    assert partial.max_tasks_per_side == MAX_GAP_FILL_TASKS_PER_SIDE == 1
    assert set(partial.sides) == {"pro", "con"}
    assert partial.reason == "evidence_pack_gap"

    failed = resolve_external_evidence_plan(
        completeness="partial",
        failed_sides=["con"],
        path="investigators",
        side_keys=["pro", "con"],
    )
    assert failed.mode == "gap_fill"
    assert failed.sides == ("con",)
    assert failed.retrieval_budget == BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    assert failed.reason == "failed_sides_gap"

    inv = resolve_external_evidence_plan(
        completeness="empty",
        path="investigators",
        side_keys=["pro", "con"],
    )
    assert inv.mode == "investigators"
    assert inv.retrieval_budget == DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET

    budgets = debater_budgets_from_completeness(
        side_keys=["pro", "con"],
        completeness="partial",
        failed_sides=["con"],
    )
    assert budgets == {"pro": 0, "con": BOUNDED_GAP_FILL_RETRIEVAL_BUDGET}
    full_budgets = debater_budgets_from_completeness(
        side_keys=["pro", "con"],
        completeness="full",
        failed_sides=[],
    )
    assert full_budgets == {"pro": 0, "con": 0}


@pytest.mark.asyncio
async def test_pretrial_partial_pack_runs_bounded_gap_fill(
    monkeypatch: pytest.MonkeyPatch,
):
    """截断附件 → partial pack → 有界补证（每方 1 任务、残搜预算），禁无限深挖。"""
    from agentcore.runtime.debate.constants import BOUNDED_GAP_FILL_RETRIEVAL_BUDGET

    long_body = "条款正文。" * 400
    prompt = f"""
<attached_files>
--- File: 长约.md (attachments/长约.md) [truncated] ---
{long_body}
</attached_files>
"""
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._system_prompt = prompt
    tool._tools = SimpleNamespace(list_all=lambda: [])
    tool._base_tool_context = SimpleNamespace(backend=MagicMock(), location="cloud")
    tool._acc = MagicMock()
    tool._llm = MagicMock()
    tool._profile_set = MagicMock()
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    captured: dict = {}

    async def fake_investigators(*_a, **kwargs):
        captured["retrieval_budget"] = kwargs["retrieval_budget"]
        captured["gap_fill"] = kwargs.get("gap_fill")
        captured["allow_read_url"] = kwargs.get("allow_read_url")
        captured["orders"] = kwargs["orders"]
        from agentcore.runtime.debate.pretrial import InvestigatorOutcome

        return [
            InvestigatorOutcome(
                side_key=o.side_key,
                run_id=f"inv_{o.side_key}_{i}",
                parent_run_id=kwargs["debater_ids"][o.side_key],
                ok=True,
                notes=f"补证笔记 {o.side_key}",
                task_query=t.query,
            )
            for o in kwargs["orders"]
            for i, t in enumerate(o.tasks)
        ]

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.declare_debater_skeleton",
        lambda *a, **k: {"pro": "mod_r1_pro", "con": "mod_r1_con"},
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.preregister_research_dossier",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.research_dossier.list_research_artifact_paths",
        AsyncMock(return_value=[]),
    )

    complete = AsyncMock(return_value={"orders": {}})
    cfg = _config(thorough=True)
    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=cfg,
        complete_json=complete,
    )
    complete.assert_not_awaited()  # 不走主辩点单深挖
    assert result.skipped is False
    assert result.external_evidence_mode == "gap_fill"
    assert result.external_evidence_reason == "evidence_pack_gap"
    assert captured["gap_fill"] is True
    assert captured["retrieval_budget"] == BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    assert captured["allow_read_url"] is True
    assert result.retrieval_budget_per_investigator == BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    # 每方至多 1 条补证任务
    assert all(len(o.tasks) == 1 for o in captured["orders"])
    assert {o.side_key for o in captured["orders"]} == {"pro", "con"}
    # 补证成功 → 完整度回写 full；辩手外证预算归零
    assert result.completeness == "full"
    assert result.failed_sides == []
    assert cfg.debater_retrieval_budgets == {"pro": 0, "con": 0}
    assert result.evidence_pack is not None


@pytest.mark.asyncio
async def test_pretrial_gap_fill_budget_exhausted_stops_without_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    """补证失败/耗尽后停止：不自愈重跑；完整度回写 partial + failed_sides；缺口方残搜。"""
    from agentcore.runtime.debate.constants import BOUNDED_GAP_FILL_RETRIEVAL_BUDGET

    long_body = "条款正文。" * 400
    prompt = f"""
<attached_files>
--- File: 长约.md (attachments/长约.md) [truncated] ---
{long_body}
</attached_files>
"""
    tool = MagicMock()
    tool._sink = MagicMock()
    tool._evidence_ledger = EvidenceLedger()
    tool._depth = 0
    tool._system_prompt = prompt
    tool._tools = SimpleNamespace(list_all=lambda: [])
    tool._base_tool_context = SimpleNamespace(backend=MagicMock(), location="cloud")
    tool._profile_set = MagicMock()
    tool._user_message = ""
    tool._max_parallel = 4
    tool._approval_gate = None

    calls = {"n": 0}

    async def fake_investigators(*_a, **kwargs):
        calls["n"] += 1
        from agentcore.runtime.debate.pretrial import InvestigatorOutcome

        return [
            InvestigatorOutcome(
                side_key=o.side_key,
                run_id=f"inv_{o.side_key}_{i}",
                parent_run_id=kwargs["debater_ids"][o.side_key],
                ok=False,
                task_query=t.query,
            )
            for o in kwargs["orders"]
            for i, t in enumerate(o.tasks)
        ]

    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.run_investigators", fake_investigators
    )
    monkeypatch.setattr(
        "agentcore.runtime.debate.pretrial.declare_debater_skeleton",
        lambda *a, **k: {"pro": "mod_r1_pro", "con": "mod_r1_con"},
    )

    cfg = _config(thorough=True)
    result = await run_pretrial_phase(
        tool,
        execution_id="e1",
        moderator_run_id="mod1",
        config=cfg,
        complete_json=AsyncMock(return_value={}),
    )
    assert calls["n"] == 1  # 耗尽/失败后不自愈补跑
    assert result.completeness == "partial"  # 包体仍可用
    assert set(result.failed_sides) == {"pro", "con"}
    assert result.retrieval_budget_per_investigator == BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    assert cfg.debater_retrieval_budgets == {
        "pro": BOUNDED_GAP_FILL_RETRIEVAL_BUDGET,
        "con": BOUNDED_GAP_FILL_RETRIEVAL_BUDGET,
    }
    assert result.to_completed_payload()["status"] == "degraded"


def test_investigator_task_payload_gap_fill_strips_read_url_when_disallowed():
    from agentcore.runtime.debate.pretrial import EvidenceTask, investigator_task_payload

    cfg = _config()
    side = cfg.sides[0]
    payload = investigator_task_payload(
        config=cfg,
        side=side,
        task=EvidenceTask(query="补证 x"),
        index=0,
        retrieval_budget=2,
        allow_read_url=False,
        gap_fill=True,
    )
    assert "read_url" not in payload["tools"]
    assert payload["retrieval_budget"] == 2
    assert "有界缺口补证" in payload["task"]

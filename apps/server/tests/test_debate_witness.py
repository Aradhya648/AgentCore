"""批 D1 · 证人模式：点名判定、窄续写、台账登记、无 session 零行为。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.debate.evidence_ledger import EvidenceLedger
from agentcore.runtime.debate.types import (
    CrossExamQa,
    DebateConfig,
    DebateForm,
    DebateSide,
    RoundPolicy,
    SideTurn,
    WitnessSeatInfo,
)
from agentcore.runtime.debate.witness import (
    WITNESS_SIDE_KEY_PREFIX,
    build_witness_seats,
    fork_witness_session,
    is_lens_session,
    lens_label_from_session,
    make_witness_runner,
    probe_witness_sessions,
    register_witness_answers_in_ledger,
    witness_exam_questions,
)
from agentcore.runtime.runs.session import RunSession
from agentcore.runtime.runs.types import RunSpec
from agentcore.runtime.sessions import SessionStore


def _lens_session(run_id: str = "lens_0", role: str = "法律视角") -> RunSession:
    return RunSession(
        run_id=run_id,
        spec=RunSpec(
            run_id=run_id,
            agent_id=run_id,
            task=f"{role}调研",
            role=role,
            tools=["web_search", "file_read", "write_file"],
        ),
        transcript=[
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="调研主题"),
            LLMMessage(role="assistant", content="已核实条款第十二条。"),
        ],
        content="已核实条款第十二条。",
        recall_count=0,
    )


def test_is_lens_session_by_run_id_and_role():
    assert is_lens_session(_lens_session("lens_0"))
    assert is_lens_session(_lens_session("synth", role="舆情公关视角"))
    synth = _lens_session("synthesizer", role="汇总分析师")
    assert not is_lens_session(synth)
    plain = _lens_session("worker_1", role="研究员")
    assert not is_lens_session(plain)


def test_lens_label_strips_视角():  # noqa: N802
    assert lens_label_from_session(_lens_session(role="法律视角")) == "法律"


def test_probe_empty_store_zero_behavior():
    assert probe_witness_sessions(None) == []
    assert probe_witness_sessions(SessionStore()) == []


def test_probe_finds_lens_sessions_sorted():
    store = SessionStore()
    store.put(_lens_session("lens_1", "品牌商业视角"))
    store.put(_lens_session("lens_0", "法律视角"))
    store.put(
        RunSession(
            run_id="synthesizer",
            spec=RunSpec(
                run_id="synthesizer",
                agent_id="synthesizer",
                task="汇总",
                role="汇总分析师",
            ),
            transcript=[LLMMessage(role="assistant", content="综述")],
            content="综述",
        )
    )
    found = probe_witness_sessions(store)
    assert [s.run_id for s in found] == ["lens_0", "lens_1"]


def test_fork_witness_session_readonly_and_recall_independent():
    lens = _lens_session()
    lens.recall_count = 2
    seat = fork_witness_session(
        lens, seat_run_id="mod_wit_lens_0", moderator_run_id="mod", depth=2
    )
    assert seat.run_id == "mod_wit_lens_0"
    assert seat.recall_count == 0
    assert "write_file" not in (seat.spec.tools or [])
    assert "file_read" in (seat.spec.tools or [])
    assert seat.spec.group == "debate:witness"
    assert seat.transcript == lens.transcript
    # 透镜原 session 不被改写
    assert lens.recall_count == 2
    assert lens.run_id == "lens_0"


def test_build_witness_seats_keys():
    seats = build_witness_seats(
        [_lens_session("lens_0"), _lens_session("lens_1", "品牌商业视角")],
        moderator_run_id="debate_mod",
        depth=2,
    )
    assert set(seats) == {"lens_0", "lens_1"}
    assert seats["lens_0"].seat_run_id == "debate_mod_wit_lens_0"
    assert "来自幕1" in seats["lens_0"].origin_caption


def test_register_witness_answers_in_ledger():
    ledger = EvidenceLedger()
    seats = build_witness_seats(
        [_lens_session()], moderator_run_id="mod", depth=1
    )
    seat = seats["lens_0"]
    ids = register_witness_answers_in_ledger(
        ledger,
        seat=seat,
        exchanges=[
            CrossExamQa(question="合同有无解除条款？", answer="第十二条可解除。"),
            CrossExamQa(question="空答", answer=""),
        ],
    )
    assert len(ids) == 1
    entry = ledger.get(ids[0])
    assert entry is not None
    assert entry["side_key"] == f"{WITNESS_SIDE_KEY_PREFIX}lens_0"
    assert "解除" in (entry.get("snippet") or "")


@pytest.mark.asyncio
async def test_witness_exam_questions_parses_factual_keys():
    config = DebateConfig(
        motion="是否解约",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="正", stance="解约"),
            DebateSide(key="con", name="反", stance="观望"),
        ],
        policy=RoundPolicy(thorough=True, max_rounds=3),
    )
    turns = [
        SideTurn(
            side_key="pro",
            side_name="正",
            run_id="r_pro",
            content="合同第十二条可解除",
            ok=True,
        ),
        SideTurn(
            side_key="con",
            side_name="反",
            run_id="r_con",
            content="第十二条不适用",
            ok=True,
        ),
    ]

    async def complete_json(system, user, scenario):  # noqa: ANN001, ARG001
        assert scenario == "witness_exam"
        assert "事实" in system or "事实" in user
        return {"questions": {"lens_0": ["合同第十二条原文如何表述？"]}}

    out = await witness_exam_questions(
        complete_json,
        config,
        "解除条款效力",
        turns,
        {"lens_0": "证人·法律（来自幕1·法律）"},
    )
    assert out == {"lens_0": ["合同第十二条原文如何表述？"]}


@pytest.mark.asyncio
async def test_witness_exam_questions_drops_unknown_keys():
    config = DebateConfig(
        motion="m",
        form=DebateForm.DEBATE,
        sides=[DebateSide(key="pro", name="正", stance="a")],
        policy=RoundPolicy.quick(),
    )
    turns = [
        SideTurn(side_key="pro", side_name="正", run_id="r", content="x", ok=True)
    ]

    async def complete_json(_s, _u, _sc):  # noqa: ANN001
        return {"questions": {"ghost": ["？"], "lens_0": ["真实问题"]}}

    out = await witness_exam_questions(
        complete_json, config, "f", turns, {"lens_0": "证人·法律"}
    )
    assert out == {"lens_0": ["真实问题"]}


@pytest.mark.asyncio
async def test_moderator_skips_witness_when_roster_empty():
    """无幕1 透镜 session（花名册空）→ 认真辩透也不点名，零行为变化。"""
    import json

    from agentcore.llm.provider.protocol import LLMResponse
    from agentcore.runtime.debate import Moderator
    from agentcore.runtime.debate.types import CrossExamExchange

    class _Scripted:
        async def complete(self, request):  # noqa: ANN001
            step = request.scenario.rsplit(".", 1)[-1]
            if step == "frame":
                return LLMResponse(
                    content=json.dumps({"focus": "焦点", "opening": "开场"})
                )
            if step == "cross_exam":
                return LLMResponse(
                    content=json.dumps({"questions": {"pro": ["Q?"], "con": ["Q?"]}})
                )
            if step == "witness_exam":
                raise AssertionError("不应请求证人点名")
            if step == "assess":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "够了",
                            "summary": "小结",
                            "scores": {},
                        }
                    )
                )
            if step == "brief":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "crux": "c",
                            "strongest_points": {},
                            "leaning": "l",
                            "confidence": "中",
                            "recommendation": "r",
                        }
                    )
                )
            return LLMResponse(content="{}")

    wit_called = {"n": 0}

    async def run_round(**_kw):  # noqa: ANN003
        return [
            SideTurn(
                side_key="pro", side_name="正", run_id="p", content="a", ok=True
            ),
            SideTurn(
                side_key="con", side_name="反", run_id="c", content="b", ok=True
            ),
        ]

    async def run_cross_exam(**kw):  # noqa: ANN003
        return [
            CrossExamExchange(
                target=k,
                exchanges=[CrossExamQa(question=qs[0], answer="答")],
                answer_run_id=f"cx_{k}",
            )
            for k, qs in kw["questions"].items()
            if qs
        ]

    async def run_witness_exam(**_kw):  # noqa: ANN003
        wit_called["n"] += 1
        return []

    mod = Moderator(provider=_Scripted(), model="m", run_id="mod")
    config = DebateConfig(
        motion="命题",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="正", stance="a"),
            DebateSide(key="con", name="反", stance="b"),
        ],
        policy=RoundPolicy(thorough=True, max_rounds=2),
    )
    result = await mod.run(
        config,
        run_round=run_round,
        run_cross_exam=run_cross_exam,
        run_witness_exam=run_witness_exam,
        witness_roster=(),
    )
    assert wit_called["n"] == 0
    assert result.witnesses == []
    assert result.rounds[0].witness_exam == []


@pytest.mark.asyncio
async def test_moderator_skips_witness_on_quick_policy():
    """快速对碰关闭质询 → 即便有花名册与 runner 也不点名。"""
    import json

    from agentcore.llm.provider.protocol import LLMResponse
    from agentcore.runtime.debate import Moderator

    class _Scripted:
        async def complete(self, request):  # noqa: ANN001
            step = request.scenario.rsplit(".", 1)[-1]
            if step == "frame":
                return LLMResponse(
                    content=json.dumps({"focus": "焦点", "opening": "开场"})
                )
            if step == "assess":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "够了",
                            "summary": "小结",
                            "scores": {},
                        }
                    )
                )
            if step == "brief":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "crux": "c",
                            "strongest_points": {},
                            "leaning": "l",
                            "confidence": "中",
                            "recommendation": "r",
                        }
                    )
                )
            return LLMResponse(content="{}")

    wit_called = {"n": 0}

    async def run_round(**_kw):  # noqa: ANN003
        return [
            SideTurn(
                side_key="pro", side_name="正", run_id="p", content="论点", ok=True
            ),
            SideTurn(
                side_key="con", side_name="反", run_id="c", content="反点", ok=True
            ),
        ]

    async def run_witness_exam(**_kw):  # noqa: ANN003
        wit_called["n"] += 1
        return []

    mod = Moderator(provider=_Scripted(), model="m", run_id="mod")
    config = DebateConfig(
        motion="命题",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="正", stance="a"),
            DebateSide(key="con", name="反", stance="b"),
        ],
        policy=RoundPolicy.quick(),
    )
    result = await mod.run(
        config,
        run_round=run_round,
        run_witness_exam=run_witness_exam,
        witness_roster=[
            WitnessSeatInfo(
                key="lens_0",
                name="证人·法律",
                lens_run_id="lens_0",
                seat_run_id="mod_wit_lens_0",
            )
        ],
    )
    assert wit_called["n"] == 0
    assert result.rounds[0].witness_exam == []
    # 花名册仍进结果（开赛探测到了），但未发生答问。
    assert len(result.witnesses) == 1


@pytest.mark.asyncio
async def test_moderator_calls_witness_on_thorough_debate():
    import json

    from agentcore.llm.provider.protocol import LLMResponse
    from agentcore.runtime.debate import Moderator
    from agentcore.runtime.debate.types import CrossExamExchange, WitnessExamExchange

    class _Scripted:
        async def complete(self, request):  # noqa: ANN001
            step = request.scenario.rsplit(".", 1)[-1]
            if step == "frame":
                return LLMResponse(
                    content=json.dumps({"focus": "焦点", "opening": "开场"})
                )
            if step == "cross_exam":
                return LLMResponse(
                    content=json.dumps(
                        {"questions": {"pro": ["为何？"], "con": ["依据？"]}}
                    )
                )
            if step == "witness_exam":
                return LLMResponse(
                    content=json.dumps(
                        {"questions": {"lens_0": ["条款原文？"]}}
                    )
                )
            if step == "assess":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "够了",
                            "summary": "小结",
                            "scores": {
                                "pro": {
                                    "argument": 3,
                                    "engagement": 3,
                                    "evidence": 3,
                                    "penalties": [],
                                    "note": "",
                                    "total": 9,
                                },
                                "con": {
                                    "argument": 3,
                                    "engagement": 3,
                                    "evidence": 3,
                                    "penalties": [],
                                    "note": "",
                                    "total": 9,
                                },
                            },
                        }
                    )
                )
            if step == "brief":
                return LLMResponse(
                    content=json.dumps(
                        {
                            "crux": "c",
                            "strongest_points": {"pro": "a", "con": "b"},
                            "leaning": "l",
                            "confidence": "中",
                            "recommendation": "r",
                            "decisive": "",
                        }
                    )
                )
            return LLMResponse(content="{}")

    async def run_round(**_kw):  # noqa: ANN003
        return [
            SideTurn(
                side_key="pro", side_name="正", run_id="p", content="有条款", ok=True
            ),
            SideTurn(
                side_key="con", side_name="反", run_id="c", content="无条款", ok=True
            ),
        ]

    async def run_cross_exam(**kw):  # noqa: ANN003
        return [
            CrossExamExchange(
                target=k,
                exchanges=[CrossExamQa(question=qs[0], answer="答")],
                answer_run_id=f"cx_{k}",
            )
            for k, qs in kw["questions"].items()
            if qs
        ]

    async def run_witness_exam(**kw):  # noqa: ANN003
        assert "lens_0" in kw["questions"]
        return [
            WitnessExamExchange(
                witness_key="lens_0",
                lens_run_id="lens_0",
                name="证人·法律",
                origin_caption="来自幕1·法律",
                exchanges=[
                    CrossExamQa(
                        question=kw["questions"]["lens_0"][0],
                        answer="第十二条写明可解除。",
                    )
                ],
                answer_run_id="mod_r1_wit_lens_0",
                seat_run_id="mod_wit_lens_0",
            )
        ]

    mod = Moderator(provider=_Scripted(), model="m", run_id="mod")
    config = DebateConfig(
        motion="是否解约",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide(key="pro", name="正", stance="解约"),
            DebateSide(key="con", name="反", stance="观望"),
        ],
        policy=RoundPolicy(thorough=True, max_rounds=2),
    )
    result = await mod.run(
        config,
        run_round=run_round,
        run_cross_exam=run_cross_exam,
        run_witness_exam=run_witness_exam,
        witness_roster=[
            WitnessSeatInfo(
                key="lens_0",
                name="证人·法律",
                lens_run_id="lens_0",
                seat_run_id="mod_wit_lens_0",
                lens_label="法律",
                origin_caption="来自幕1·法律",
            )
        ],
    )
    assert len(result.witnesses) == 1
    wx = result.rounds[0].witness_exam
    assert len(wx) == 1
    assert wx[0].witness_key == "lens_0"
    payload = result.rounds[0].to_event_payload()
    assert payload["witness_exam"][0]["origin_caption"] == "来自幕1·法律"
    assert result.to_event_payload()["witnesses"][0]["key"] == "lens_0"


async def test_witness_exam_emits_unexamined_when_no_questions():
    """主持人未点名 → 可观测 debate.witness.unexamined（席位保持待命）。"""
    from structlog.testing import capture_logs

    seats = build_witness_seats(
        [_lens_session("lens_0")],
        moderator_run_id="mod",
        depth=1,
    )
    tool = SimpleNamespace(
        _approval_gate=None,
        _base_tool_context=SimpleNamespace(backend=SimpleNamespace(location="cloud")),
        _max_parallel=None,
        _llm=None,
        _tools=[],
        _profile_set=None,
        _sink=MagicMock(),
        _acc=MagicMock(),
        _evidence_ledger=EvidenceLedger(),
    )
    runner = make_witness_runner(tool, "exec", "mod", seats)
    with capture_logs() as logs:
        out = await runner(round_no=1, focus="焦点", questions={})
    assert out == []
    assert any(e.get("event") == "debate.witness.unexamined" for e in logs)

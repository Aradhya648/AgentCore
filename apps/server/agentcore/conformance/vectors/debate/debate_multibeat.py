"""Multi-beat adversarial debate conformance vector."""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    debate_result,
    debate_round_started,
    message_end,
    message_start,
    run_completed,
    run_output_delta,
    run_plan,
    run_started,
)

from .._common import _CONV, _COST, _USAGE, _ctx_block
from ._builders import (
    _moderator_agents_runs,
    _pro_con_debater_agents,
    _pro_con_debater_runs,
    _side_continue,
)


def _multi_agent_debate_multibeat() -> list[SSEEvent]:
    """多轮对抗辩论 + 每轮质询 + 结辩：钉死协作图「参与者×beat 列」契约。

    每方 5 个可见节点（首轮陈词无角标 + 第1轮质询 + 第2轮陈词 + 第2轮质询 + 结辩），
    ``run_context`` 首块 task（真实 feedback 孪生）+ 浓缩通道块区分质询/结辩/续轮（复用既有
    字段，不新造 beat wire）。golden 断言：进度 11/11；各续写 beat 含 task；两轮均带 cross_exam；
    closings 齐。
    """
    cap, mod = "captain1", "debate_mb_mod1"
    pro_r1, con_r1 = f"{mod}_r1_pro", f"{mod}_r1_con"
    pro_r1_cx, con_r1_cx = f"{mod}_r1_cx_pro", f"{mod}_r1_cx_con"
    pro_r2, con_r2 = f"{mod}_r2_pro", f"{mod}_r2_con"
    pro_r2_cx, con_r2_cx = f"{mod}_r2_cx_pro", f"{mod}_r2_cx_con"
    pro_closing, con_closing = f"{mod}_closing_pro", f"{mod}_closing_con"
    mod_agents, mod_runs = _moderator_agents_runs(
        mod, cap, "主持多轮正反辩论：是否采用方案 A"
    )
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_r1,
        con_r1,
        pro_task="论证支持采用方案 A",
        con_task="论证反对采用方案 A",
    )
    score = {
        "argument": 3,
        "engagement": 3,
        "evidence": 3,
        "penalties": [],
        "note": "交锋充分。",
        "total": 9,
    }
    debate_payload = {
        "form": "debate",
        "motion": "是否采用方案 A",
        "stop_reason": "converged",
        "narrative_first": False,
        "sides": [
            {"key": "pro", "name": "支持方", "stance": "支持采用方案 A", "is_subject": False},
            {"key": "con", "name": "反对方", "stance": "反对采用方案 A", "is_subject": False},
        ],
        "rounds": [
            {
                "round_no": 1,
                "focus": "收益与风险敞口",
                "summary": "首轮立论后质询，争点仍在风险可控性。",
                "verdict": {
                    "real_clash": True,
                    "new_arguments": True,
                    "converged": False,
                    "stop_reason": "",
                    "rationale": "尚有新论据，续辩。",
                },
                "sides": [
                    {"key": "pro", "name": "支持方", "run_id": pro_r1, "ok": True, "absent": False, "arguments": []},
                    {"key": "con", "name": "反对方", "run_id": con_r1, "ok": True, "absent": False, "arguments": []},
                ],
                "clashes": [],
                "cross_exam": [
                    {
                        "target": "pro",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "收益口径是否含尾部？",
                                "answer": "未含【待核实·推断】",
                            },
                        ],
                        "answer_run_id": pro_r1_cx,
                    },
                    {
                        "target": "con",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "风险有无量化故障率？",
                                "answer": "暂无【待核实·推断】",
                            },
                        ],
                        "answer_run_id": con_r1_cx,
                    },
                ],
                "scores": {"pro": score, "con": score},
            },
            {
                "round_no": 2,
                "focus": "灰度与回滚兜底",
                "summary": "第二轮聚焦灰度兜底后质询，争点收敛。",
                "verdict": {
                    "real_clash": True,
                    "new_arguments": False,
                    "converged": True,
                    "stop_reason": "无新论据。",
                    "rationale": "可收场。",
                },
                "sides": [
                    {"key": "pro", "name": "支持方", "run_id": pro_r2, "ok": True, "absent": False, "arguments": []},
                    {"key": "con", "name": "反对方", "run_id": con_r2, "ok": True, "absent": False, "arguments": []},
                ],
                "clashes": [],
                "cross_exam": [
                    {
                        "target": "pro",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "熔断谁买单？",
                                "answer": "灰度预算池【已核实·预案】",
                            },
                        ],
                        "answer_run_id": pro_r2_cx,
                    },
                    {
                        "target": "con",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "反对全量的硬门槛是？",
                                "answer": "须有双写一致性 SLA【待核实·推断】",
                            },
                        ],
                        "answer_run_id": con_r2_cx,
                    },
                ],
                "scores": {"pro": score, "con": score},
            },
        ],
        "closings": [
            {"key": "pro", "name": "支持方", "run_id": pro_closing, "ok": True},
            {"key": "con", "name": "反对方", "run_id": con_closing, "ok": True},
        ],
        "brief": {
            "crux": "方案 A 风险是否可控",
            "strongest_points": {"pro": "灰度可兜底", "con": "双写窗口未解"},
            "handoffs": [],
            "decisive": "综合净分接近，倾向有条件灰度。",
            "leaning": "倾向有条件采用",
            "confidence": "medium",
            "recommendation": "先灰度再全量。",
        },
    }
    cx1 = [
        _ctx_block(
            "task",
            "质询环节",
            "## 第 1 轮 · 质询环节\n请按 ### 质询一 标题逐条正面作答。\n1. 质询题",
        ),
        _ctx_block("cross_exam", "第 1 轮 · 质询（必须正面回答）", "- 质询题"),
    ]
    cx2 = [
        _ctx_block(
            "task",
            "质询环节",
            "## 第 2 轮 · 质询环节\n请按 ### 质询一 标题逐条正面作答。\n1. 质询题",
        ),
        _ctx_block("cross_exam", "第 2 轮 · 质询（必须正面回答）", "- 质询题"),
    ]
    closing_ctx = [
        _ctx_block(
            "task",
            "结辩环节",
            "## 结辩环节\n请【只讲胜负手】；【不得引入任何新论据】。直接输出你的结辩陈词。",
        ),
        _ctx_block("closing", "结辩环节", "本场辩论已充分交锋，现请做结辩陈词。"),
    ]
    r2_ctx = [
        _ctx_block(
            "task",
            "第 2 轮任务",
            "## 第 2 轮 · 本轮焦点：灰度与回滚兜底\n对方上一轮的论点如下，请针对性回应。",
        ),
        _ctx_block("round_focus", "第 2 轮 · 本轮焦点", "灰度与回滚兜底"),
        _ctx_block("opponent", "对方上一轮", "对方上轮论点摘要"),
    ]
    events: list[SSEEvent] = [
        message_start("m1", conversation_id=_CONV),
        content_delta("多轮对抗辩论，每轮质询后结辩。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="多轮正反辩论：是否采用方案 A",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus="收益与风险敞口",
            cross_exam_enabled=True,
            opening="多轮对抗开场：先把收益与风险敞口摆上台面。",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_r1, "d_pro", parent_run_id=mod),
        run_output_delta(pro_r1, "d_pro", "支持：收益可量化【已核实·审计】。"),
        run_completed(
            pro_r1,
            "d_pro",
            output_summary="支持方第1轮",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_r1, "d_con", parent_run_id=mod),
        run_output_delta(con_r1, "d_con", "反对：风险缺兜底【已核实·复盘】。"),
        run_completed(
            con_r1,
            "d_con",
            output_summary="反对方第1轮",
            duration_ms=850,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        *(_side_continue(
            pro_r1_cx, parent=mod, continues_run_id=pro_r1,
            stance="pro",
            round_no=1,
            context_blocks=cx1,
            delta="### 质询一\n未含尾部【待核实·推断】。",
            output_summary="支持方第1轮质询",
            duration_ms=600,
        )),
        *(_side_continue(
            con_r1_cx, parent=mod, continues_run_id=con_r1,
            stance="con",
            round_no=1,
            context_blocks=cx1,
            delta="### 质询一\n暂无故障率【待核实·推断】。",
            output_summary="反对方第1轮质询",
            duration_ms=610,
        )),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=2,
            focus="灰度与回滚兜底",
            cross_exam_enabled=True,
        ),
        *(_side_continue(
            pro_r2, parent=mod, continues_run_id=pro_r1,
            stance="pro",
            round_no=2,
            context_blocks=r2_ctx,
            delta="续辩：灰度熔断可兜底【已核实·预案】。",
            output_summary="支持方第2轮",
            duration_ms=700,
        )),
        *(_side_continue(
            con_r2, parent=mod, continues_run_id=con_r1,
            stance="con",
            round_no=2,
            context_blocks=r2_ctx,
            delta="续辩：双写窗口仍未解【已核实·复盘】。",
            output_summary="反对方第2轮",
            duration_ms=720,
        )),
        *(_side_continue(
            pro_r2_cx, parent=mod, continues_run_id=pro_r1,
            stance="pro",
            round_no=2,
            context_blocks=cx2,
            delta="### 质询一\n预算池买单【已核实·预案】。",
            output_summary="支持方第2轮质询",
            duration_ms=580,
        )),
        *(_side_continue(
            con_r2_cx, parent=mod, continues_run_id=con_r1,
            stance="con",
            round_no=2,
            context_blocks=cx2,
            delta="### 质询一\n须有一致性 SLA【待核实·推断】。",
            output_summary="反对方第2轮质询",
            duration_ms=590,
        )),
        *(_side_continue(
            pro_closing, parent=mod, continues_run_id=pro_r1,
            stance="pro",
            round_no=2,
            context_blocks=closing_ctx,
            delta="结辩：收益确定、风险有解，应有条件采用。",
            output_summary="支持方结辩",
            duration_ms=500,
        )),
        *(_side_continue(
            con_closing, parent=mod, continues_run_id=con_r1,
            stance="con",
            round_no=2,
            context_blocks=closing_ctx,
            delta="结辩：风险未对冲前不宜全量。",
            output_summary="反对方结辩",
            duration_ms=510,
        )),
        run_completed(
            mod,
            mod,
            output_summary="方案 A 的风险是否可控",
            duration_ms=2400,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(execution_id="exec1", moderator_run_id=mod, payload=debate_payload),
        message_end(FinishReason.END_TURN, input_tokens=4200, output_tokens=900, cost=_COST),
    ]
    return events


"""庭前取证 conformance：thorough 带队完整流 + fast 不带队秒过。"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    debate_pretrial_completed,
    debate_pretrial_orders,
    debate_pretrial_progress,
    debate_pretrial_started,
    debate_result,
    debate_round_started,
    message_end,
    message_start,
    run_completed,
    run_context,
    run_output_delta,
    run_plan,
    run_started,
)

from .._common import _CONV, _COST, _USAGE, _ctx_block
from ._builders import _moderator_agents_runs, _pro_con_debater_agents, _pro_con_debater_runs


def _multi_agent_debate_pretrial_thorough() -> list[SSEEvent]:
    """thorough=True：庭前点单 → 取证员（parent=主辩）→ 立论。"""
    cap, mod = "captain1", "debate_mod_pt"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    inv_pro, inv_con = f"{mod}_inv_pro_0", f"{mod}_inv_con_0"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持正反辩论：是否采用方案 A")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="论证支持采用方案 A",
        con_task="论证反对采用方案 A",
    )
    inv_agents = [
        {"id": inv_pro, "role": "取证·支持方", "thinking": True},
        {"id": inv_con, "role": "取证·反对方", "thinking": True},
    ]
    inv_runs = [
        {
            "id": inv_pro,
            "agent_id": inv_pro,
            "task": "为支持方取证：方案 A 成本可控的来源",
            "depends_on": [],
            "parent_run_id": pro_run,
            # 与生产对齐：取证员 group 在 pretrial: 命名空间（非 debate: 参与者）
            "group": "pretrial:investigators:pro",
        },
        {
            "id": inv_con,
            "agent_id": inv_con,
            "task": "为反对方取证：方案 A 风险敞口的来源",
            "depends_on": [],
            "parent_run_id": con_run,
            "group": "pretrial:investigators:con",
        },
    ]
    sides_wire = [
        {"key": "pro", "name": "支持方"},
        {"key": "con", "name": "反对方"},
    ]
    orders_wire = [
        {
            "side_key": "pro",
            "tasks": [{"query": "方案 A 成本可控的来源", "purpose": "立论底料"}],
            "source": "debater",
        },
        {
            "side_key": "con",
            "tasks": [{"query": "方案 A 风险敞口的来源", "purpose": "立论底料"}],
            "source": "debater",
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场辩论。"),
        run_plan(
            execution_id="exec_pt",
            plan_type="debate",
            task_summary="正反辩论：是否采用方案 A",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_pretrial_started(
            execution_id="exec_pt",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
        ),
        # 主辩骨架（庭前声明，parent=主持人）
        run_plan(
            execution_id="exec_pt",
            plan_type="debate",
            task_summary="庭前取证·主辩点单",
            agents=debater_agents,
            runs=debater_runs,
        ),
        debate_pretrial_orders(
            execution_id="exec_pt",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            orders=orders_wire,
            investigator_count_per_side=1,
            retrieval_budget_per_investigator=14,
        ),
        run_plan(
            execution_id="exec_pt",
            plan_type="debate",
            task_summary="",
            agents=inv_agents,
            runs=inv_runs,
        ),
        # 与生产同构：取证员走 execute_agent_node 首跑，run_started 不带 group
        # （权威 = 上方 run_plan.runs[].group）；续写路径才在 started 上携 group。
        run_started(
            inv_pro,
            inv_pro,
            parent_run_id=pro_run,
        ),
        run_output_delta(inv_pro, inv_pro, "笔记：成本可控【已核实·#e1】"),
        run_completed(
            inv_pro,
            inv_pro,
            output_summary="取证完成",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_pretrial_progress(
            execution_id="exec_pt",
            moderator_run_id=mod,
            side_key="pro",
            investigator_run_id=inv_pro,
            parent_run_id=pro_run,
            status="completed",
            evidence_ledger_count=1,
        ),
        run_started(
            inv_con,
            inv_con,
            parent_run_id=con_run,
        ),
        run_output_delta(inv_con, inv_con, "笔记：风险敞口【已核实·#e2】"),
        run_completed(
            inv_con,
            inv_con,
            output_summary="取证完成",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_pretrial_progress(
            execution_id="exec_pt",
            moderator_run_id=mod,
            side_key="con",
            investigator_run_id=inv_con,
            parent_run_id=con_run,
            status="completed",
            evidence_ledger_count=2,
        ),
        debate_pretrial_completed(
            execution_id="exec_pt",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            status="done",
            orders=orders_wire,
            investigators=[
                {
                    "side_key": "pro",
                    "run_id": inv_pro,
                    "parent_run_id": pro_run,
                    "ok": True,
                    "task_query": "方案 A 成本可控的来源",
                },
                {
                    "side_key": "con",
                    "run_id": inv_con,
                    "parent_run_id": con_run,
                    "ok": True,
                    "task_query": "方案 A 风险敞口的来源",
                },
            ],
            fallback_self_search=False,
            evidence_ready=True,
            evidence_ledger_count=2,
            evidence_ledger_delta=[
                {
                    "id": "#e1",
                    "url": "https://example.com/a",
                    "title": "成本报告",
                    "snippet": "",
                    "site": "",
                    "date": "",
                    "tier": "media",
                    "side_key": "pro",
                },
                {
                    "id": "#e2",
                    "url": "https://example.com/b",
                    "title": "风险备忘",
                    "snippet": "",
                    "site": "",
                    "date": "",
                    "tier": "media",
                    "side_key": "con",
                },
            ],
        ),
        debate_round_started(
            execution_id="exec_pt",
            moderator_run_id=mod,
            round_no=1,
            focus="成本与风险",
            cross_exam_enabled=True,
            opening="先从成本与风险切入。",
            form="debate",
        ),
        run_plan(
            execution_id="exec_pt",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_run, pro_run, parent_run_id=mod, stance="pro", round_no=1),
        run_context(pro_run, pro_run, [_ctx_block("task", "立论", "支持方案 A")]),
        run_output_delta(pro_run, pro_run, "### 成本可控\n有据可依【已核实·#e1】。"),
        run_completed(
            pro_run,
            pro_run,
            output_summary="支持方立论",
            duration_ms=1200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_run, con_run, parent_run_id=mod, stance="con", round_no=1),
        run_context(con_run, con_run, [_ctx_block("task", "立论", "反对方案 A")]),
        run_output_delta(con_run, con_run, "### 风险未兜底\n敞口仍在【已核实·#e2】。"),
        run_completed(
            con_run,
            con_run,
            output_summary="反对方立论",
            duration_ms=1100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="1 轮·收敛",
            duration_ms=5000,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(
            execution_id="exec_pt",
            moderator_run_id=mod,
            payload={
                "form": "debate",
                "motion": "是否采用方案 A",
                "stop_reason": "converged",
                "opening": "先从成本与风险切入。",
                "narrative_first": False,
                "sides": [
                    {
                        "key": "pro",
                        "name": "支持方",
                        "stance": "支持采用方案 A",
                        "is_subject": False,
                    },
                    {
                        "key": "con",
                        "name": "反对方",
                        "stance": "反对采用方案 A",
                        "is_subject": False,
                    },
                ],
                "rounds": [
                    {
                        "round_no": 1,
                        "focus": "成本与风险",
                        "summary": "双方围绕成本与风险交锋。",
                        "verdict": {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "核心分歧已暴露",
                        },
                        "sides": [
                            {
                                "key": "pro",
                                "name": "支持方",
                                "run_id": pro_run,
                                "ok": True,
                            },
                            {
                                "key": "con",
                                "name": "反对方",
                                "run_id": con_run,
                                "ok": True,
                            },
                        ],
                        "clashes": [],
                        "cross_exam": [],
                        "scores": {},
                    }
                ],
                "closings": [],
                "brief": {
                    "crux": "成本 vs 风险",
                    "strongest_points": {"pro": "成本可控", "con": "风险未兜底"},
                    "handoffs": [],
                    "decisive": "需用户权衡",
                    "leaning": "未决",
                    "confidence": "medium",
                    "recommendation": "先补风险兜底再定",
                },
                "evidence_ledger": [
                    {
                        "id": "#e1",
                        "url": "https://example.com/a",
                        "title": "成本报告",
                        "snippet": "",
                        "site": "",
                        "date": "",
                        "tier": "media",
                        "side_key": "pro",
                    },
                    {
                        "id": "#e2",
                        "url": "https://example.com/b",
                        "title": "风险备忘",
                        "snippet": "",
                        "site": "",
                        "date": "",
                        "tier": "media",
                        "side_key": "con",
                    },
                ],
            },
        ),
        content_delta("辩论结束，简报如上。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]


def _multi_agent_debate_pretrial_fast() -> list[SSEEvent]:
    """thorough=False：庭前秒过（skip_reason=fast），无取证员。"""
    cap, mod = "captain1", "debate_mod_fast"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持正反辩论：快速对碰")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="快速支持",
        con_task="快速反对",
    )
    sides_wire = [
        {"key": "pro", "name": "支持方"},
        {"key": "con", "name": "反对方"},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("快速对碰。"),
        run_plan(
            execution_id="exec_fast",
            plan_type="debate",
            task_summary="正反辩论：快速对碰",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_pretrial_started(
            execution_id="exec_fast",
            moderator_run_id=mod,
            thorough=False,
            sides=sides_wire,
            skip_reason="fast",
        ),
        debate_pretrial_completed(
            execution_id="exec_fast",
            moderator_run_id=mod,
            thorough=False,
            sides=sides_wire,
            status="skipped",
            skip_reason="fast",
            orders=[],
            investigators=[],
            fallback_self_search=False,
            evidence_ready=False,
            evidence_ledger_count=0,
            evidence_ledger_delta=[],
        ),
        debate_round_started(
            execution_id="exec_fast",
            moderator_run_id=mod,
            round_no=1,
            focus="核心一击",
            cross_exam_enabled=False,
            opening="",
            form="debate",
        ),
        run_plan(
            execution_id="exec_fast",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_run, pro_run, parent_run_id=mod, stance="pro", round_no=1),
        run_output_delta(pro_run, pro_run, "支持。"),
        run_completed(
            pro_run,
            pro_run,
            output_summary="支持方",
            duration_ms=400,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_run, con_run, parent_run_id=mod, stance="con", round_no=1),
        run_output_delta(con_run, con_run, "反对。"),
        run_completed(
            con_run,
            con_run,
            output_summary="反对方",
            duration_ms=400,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="1 轮·快速",
            duration_ms=1200,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(
            execution_id="exec_fast",
            moderator_run_id=mod,
            payload={
                "form": "debate",
                "motion": "快速对碰命题",
                "stop_reason": "converged",
                "opening": "",
                "narrative_first": False,
                "sides": [
                    {
                        "key": "pro",
                        "name": "支持方",
                        "stance": "支持",
                        "is_subject": False,
                    },
                    {
                        "key": "con",
                        "name": "反对方",
                        "stance": "反对",
                        "is_subject": False,
                    },
                ],
                "rounds": [
                    {
                        "round_no": 1,
                        "focus": "核心一击",
                        "summary": "快速交锋。",
                        "verdict": {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "单轮即收",
                        },
                        "sides": [
                            {
                                "key": "pro",
                                "name": "支持方",
                                "run_id": pro_run,
                                "ok": True,
                            },
                            {
                                "key": "con",
                                "name": "反对方",
                                "run_id": con_run,
                                "ok": True,
                            },
                        ],
                        "clashes": [],
                        "cross_exam": [],
                        "scores": {},
                    }
                ],
                "closings": [],
                "brief": {
                    "crux": "快速分歧",
                    "strongest_points": {"pro": "支持", "con": "反对"},
                    "handoffs": [],
                    "decisive": "",
                    "leaning": "未决",
                    "confidence": "low",
                    "recommendation": "需要更深入再辩",
                },
                "evidence_ledger": [],
            },
        ),
        message_end(FinishReason.END_TURN, input_tokens=500, output_tokens=80, cost=_COST),
    ]

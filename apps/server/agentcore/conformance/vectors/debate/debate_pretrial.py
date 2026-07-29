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
            completeness="full",
            incomplete=False,
            failed_sides=[],
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
            completeness="empty",
            incomplete=False,
            failed_sides=[],
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


def _pack_source(
    *,
    source_id: str,
    label: str,
    path: str,
    excerpt: str,
    complete: bool = True,
    failure: str | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "kind": "attachment",
        "label": label,
        "path": path,
        "excerpt": excerpt,
        "complete": complete,
        "failure": failure,
    }


def _multi_agent_debate_pretrial_evidence_pack_full() -> list[SSEEvent]:
    """Evidence Pack 完整：skip 外证、budget/plan=0、completeness=full。"""
    cap, mod = "captain1", "debate_mod_ep_full"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持正反辩论：合同条款争议")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="依共享证据包论证支持",
        con_task="依共享证据包论证反对",
    )
    sides_wire = [
        {"key": "pro", "name": "支持方"},
        {"key": "con", "name": "反对方"},
    ]
    pack_wire = {
        "motion": "是否续签合同",
        "completeness": "full",
        "notes": "从主持人上下文组装共享证据包（1 份可用正文附件）",
        "sources": [
            _pack_source(
                source_id="att:contract",
                label="合同.md",
                path="attachments/合同.md",
                excerpt="甲乙双方约定价款与交付期限……",
            )
        ],
        "dispute_candidates": [
            {
                "claim": "价款条款是否完备",
                "why_contested": "双方对违约金计算口径有分歧",
                "related_source_ids": ["att:contract"],
            }
        ],
    }
    external_plan = {
        "mode": "skip",
        "retrieval_budget": 0,
        "sides": [],
        "allow_read_url": False,
        "max_tasks_per_side": 0,
        "reason": "evidence_pack_full",
        "allow_external": False,
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("附件已齐，按共享证据包开辩。"),
        run_plan(
            execution_id="exec_ep_full",
            plan_type="debate",
            task_summary="正反辩论：是否续签合同",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_pretrial_started(
            execution_id="exec_ep_full",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
        ),
        debate_pretrial_orders(
            execution_id="exec_ep_full",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            orders=[],
            investigator_count_per_side=0,
            retrieval_budget_per_investigator=0,
            evidence_pack=pack_wire,
            path="evidence_pack",
            completeness="full",
            incomplete=False,
            external_evidence=external_plan,
        ),
        debate_pretrial_completed(
            execution_id="exec_ep_full",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            status="skipped",
            skip_reason="evidence_pack",
            orders=[],
            investigators=[],
            fallback_self_search=False,
            evidence_ready=True,
            completeness="full",
            incomplete=False,
            failed_sides=[],
            evidence_pack=pack_wire,
            external_evidence_mode="skip",
            external_evidence_reason="evidence_pack_full",
            retrieval_budget_per_investigator=0,
            evidence_ledger_count=1,
            evidence_ledger_delta=[
                {
                    "id": "#e1",
                    "url": "",
                    "title": "合同.md",
                    "snippet": "甲乙双方约定价款与交付期限……",
                    "site": "",
                    "date": "",
                    "tier": "primary",
                    "side_key": "evidence_pack",
                }
            ],
        ),
        debate_round_started(
            execution_id="exec_ep_full",
            moderator_run_id=mod,
            round_no=1,
            focus="价款条款",
            cross_exam_enabled=False,
            opening="双方依共享证据包立论。",
            form="debate",
        ),
        run_plan(
            execution_id="exec_ep_full",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_run, pro_run, parent_run_id=mod, stance="pro", round_no=1),
        run_output_delta(pro_run, pro_run, "支持续签【已核实·#e1】。"),
        run_completed(
            pro_run,
            pro_run,
            output_summary="支持方",
            duration_ms=500,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_run, con_run, parent_run_id=mod, stance="con", round_no=1),
        run_output_delta(con_run, con_run, "反对续签【已核实·#e1】。"),
        run_completed(
            con_run,
            con_run,
            output_summary="反对方",
            duration_ms=500,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="1 轮·证据包",
            duration_ms=1500,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(
            execution_id="exec_ep_full",
            moderator_run_id=mod,
            payload={
                "form": "debate",
                "motion": "是否续签合同",
                "stop_reason": "converged",
                "opening": "双方依共享证据包立论。",
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
                "moderator_run_id": mod,
                "moderator_model": "deepseek-v4-flash",
                "rounds": [
                    {
                        "round_no": 1,
                        "focus": "价款条款",
                        "summary": "围绕合同价款",
                        "verdict": {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "依共享证据包交锋后收敛",
                        },
                        "sides": [
                            {
                                "key": "pro",
                                "name": "支持方",
                                "run_id": pro_run,
                                "ok": True,
                                "arguments": [],
                            },
                            {
                                "key": "con",
                                "name": "反对方",
                                "run_id": con_run,
                                "ok": True,
                                "arguments": [],
                            },
                        ],
                        "clashes": [],
                        "cross_exam": [],
                        "scores": {},
                    }
                ],
                "closings": [],
                "brief": {
                    "crux": "价款条款",
                    "strongest_points": {"pro": "支持", "con": "反对"},
                    "handoffs": [],
                    "decisive": "",
                    "leaning": "未决",
                    "confidence": "low",
                    "recommendation": "复核违约金口径",
                },
                "evidence_ledger": [
                    {
                        "id": "#e1",
                        "url": "",
                        "title": "合同.md",
                        "snippet": "甲乙双方约定价款与交付期限……",
                        "site": "合同.md",
                        "date": "",
                        "tier": "unknown",
                        "side_key": "evidence_pack",
                        "dossier_path": "attachments/合同.md",
                        "origin_id": "",
                        "dossier_label": "合同.md",
                    }
                ],
            },
        ),
        message_end(FinishReason.END_TURN, input_tokens=600, output_tokens=100, cost=_COST),
    ]


def _multi_agent_debate_pretrial_evidence_pack_gap_fill() -> list[SSEEvent]:
    """Evidence Pack 截断：有界 gap_fill + reason；一侧失败 → partial。"""
    from agentcore.runtime.debate.constants import BOUNDED_GAP_FILL_RETRIEVAL_BUDGET

    cap, mod = "captain1", "debate_mod_ep_gap"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    inv_pro, inv_con = f"{mod}_inv_pro_0", f"{mod}_inv_con_0"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持正反辩论：长约缺口补证")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="论证支持（含补证）",
        con_task="论证反对（含补证）",
    )
    sides_wire = [
        {"key": "pro", "name": "支持方"},
        {"key": "con", "name": "反对方"},
    ]
    pack_wire = {
        "motion": "是否采用方案 A",
        "completeness": "partial",
        "notes": "从主持人上下文组装共享证据包（截断附件）",
        "sources": [
            _pack_source(
                source_id="att:long",
                label="长约.md",
                path="attachments/长约.md",
                excerpt="条款正文…" * 20,
                complete=False,
                failure="truncated",
            )
        ],
        "dispute_candidates": [],
    }
    budget = BOUNDED_GAP_FILL_RETRIEVAL_BUDGET
    external_plan = {
        "mode": "gap_fill",
        "retrieval_budget": budget,
        "sides": ["pro", "con"],
        "allow_read_url": True,
        "max_tasks_per_side": 1,
        "reason": "evidence_pack_gap",
        "allow_external": True,
    }
    # 具名 str，避免 list[dict] 字面量被 mypy 推成 Collection[str] 后不可索引。
    pro_gap_query = (
        "是否采用方案 A：补证「长约.md」—支持「支持方」的权威外证；禁对已注入附件重复深挖"
    )
    con_gap_query = (
        "是否采用方案 A：补证「长约.md」—支持「反对方」的权威外证；禁对已注入附件重复深挖"
    )
    orders_wire: list[dict[str, object]] = [
        {
            "side_key": "pro",
            "tasks": [
                {
                    "query": pro_gap_query,
                    "purpose": "有界缺口补证",
                }
            ],
            "source": "auto",
        },
        {
            "side_key": "con",
            "tasks": [
                {
                    "query": con_gap_query,
                    "purpose": "有界缺口补证",
                }
            ],
            "source": "auto",
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("附件截断，启动有界补证。"),
        run_plan(
            execution_id="exec_ep_gap",
            plan_type="debate",
            task_summary="正反辩论：是否采用方案 A",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_pretrial_started(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
        ),
        debate_pretrial_orders(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            orders=orders_wire,
            investigator_count_per_side=1,
            retrieval_budget_per_investigator=budget,
            evidence_pack=pack_wire,
            path="evidence_pack_gap_fill",
            completeness="partial",
            incomplete=True,
            external_evidence=external_plan,
        ),
        # 主辩骨架（补证员 parent=主辩）
        run_plan(
            execution_id="exec_ep_gap",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_plan(
            execution_id="exec_ep_gap",
            plan_type="debate",
            task_summary="",
            agents=[
                {"id": inv_pro, "role": "取证·支持方", "thinking": True},
                {"id": inv_con, "role": "取证·反对方", "thinking": True},
            ],
            runs=[
                {
                    "id": inv_pro,
                    "agent_id": inv_pro,
                    "task": pro_gap_query,
                    "depends_on": [],
                    "parent_run_id": pro_run,
                    "group": "pretrial:investigators:pro",
                },
                {
                    "id": inv_con,
                    "agent_id": inv_con,
                    "task": con_gap_query,
                    "depends_on": [],
                    "parent_run_id": con_run,
                    "group": "pretrial:investigators:con",
                },
            ],
        ),
        run_started(inv_pro, inv_pro, parent_run_id=pro_run),
        run_output_delta(inv_pro, inv_pro, "补证找到权威来源。"),
        run_completed(
            inv_pro,
            inv_pro,
            output_summary="支持方补证",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_pretrial_progress(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            side_key="pro",
            investigator_run_id=inv_pro,
            parent_run_id=pro_run,
            status="completed",
            evidence_ledger_count=2,
        ),
        run_started(inv_con, inv_con, parent_run_id=con_run),
        run_completed(
            inv_con,
            inv_con,
            output_summary="反对方补证失败",
            duration_ms=400,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
            # 与生产一致：失败仍发 run_completed；庭前 completed.investigators.ok=False
        ),
        debate_pretrial_progress(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            side_key="con",
            investigator_run_id=inv_con,
            parent_run_id=con_run,
            status="failed",
            evidence_ledger_count=2,
        ),
        debate_pretrial_completed(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            thorough=True,
            sides=sides_wire,
            status="degraded",
            orders=orders_wire,
            investigators=[
                {
                    "side_key": "pro",
                    "run_id": inv_pro,
                    "parent_run_id": pro_run,
                    "ok": True,
                    "task_query": pro_gap_query,
                },
                {
                    "side_key": "con",
                    "run_id": inv_con,
                    "parent_run_id": con_run,
                    "ok": False,
                    "task_query": con_gap_query,
                },
            ],
            fallback_self_search=False,
            evidence_ready=True,
            completeness="partial",
            incomplete=True,
            failed_sides=["con"],
            evidence_pack={**pack_wire, "completeness": "partial"},
            external_evidence_mode="gap_fill",
            external_evidence_reason="evidence_pack_gap",
            retrieval_budget_per_investigator=budget,
            evidence_ledger_count=2,
            evidence_ledger_delta=[
                {
                    "id": "#e1",
                    "url": "",
                    "title": "长约.md",
                    "snippet": "条款正文…",
                    "site": "",
                    "date": "",
                    "tier": "primary",
                    "side_key": "evidence_pack",
                },
                {
                    "id": "#e2",
                    "url": "https://example.com/gap",
                    "title": "补证来源",
                    "snippet": "",
                    "site": "",
                    "date": "",
                    "tier": "media",
                    "side_key": "pro",
                },
            ],
        ),
        debate_round_started(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            round_no=1,
            focus="缺口与风险",
            cross_exam_enabled=False,
            opening="补证未齐，仍开立论。",
            form="debate",
        ),
        run_started(pro_run, pro_run, parent_run_id=mod, stance="pro", round_no=1),
        run_output_delta(pro_run, pro_run, "支持方案 A【已核实·#e2】。"),
        run_completed(
            pro_run,
            pro_run,
            output_summary="支持方",
            duration_ms=600,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_run, con_run, parent_run_id=mod, stance="con", round_no=1),
        run_output_delta(con_run, con_run, "反对方案 A（补证缺口仍在）。"),
        run_completed(
            con_run,
            con_run,
            output_summary="反对方",
            duration_ms=600,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="1 轮·有界补证",
            duration_ms=2000,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(
            execution_id="exec_ep_gap",
            moderator_run_id=mod,
            payload={
                "form": "debate",
                "motion": "是否采用方案 A",
                "stop_reason": "converged",
                "opening": "补证未齐，仍开立论。",
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
                "moderator_run_id": mod,
                "moderator_model": "deepseek-v4-flash",
                "rounds": [
                    {
                        "round_no": 1,
                        "focus": "缺口与风险",
                        "summary": "补证部分失败",
                        "verdict": {
                            "real_clash": True,
                            "new_arguments": False,
                            "converged": True,
                            "stop_reason": "converged",
                            "rationale": "补证未齐仍收敛交锋",
                        },
                        "sides": [
                            {
                                "key": "pro",
                                "name": "支持方",
                                "run_id": pro_run,
                                "ok": True,
                                "arguments": [],
                            },
                            {
                                "key": "con",
                                "name": "反对方",
                                "run_id": con_run,
                                "ok": True,
                                "arguments": [],
                            },
                        ],
                        "clashes": [],
                        "cross_exam": [],
                        "scores": {},
                    }
                ],
                "closings": [],
                "brief": {
                    "crux": "补证缺口",
                    "strongest_points": {"pro": "支持", "con": "反对"},
                    "handoffs": [],
                    "decisive": "",
                    "leaning": "未决",
                    "confidence": "low",
                    "recommendation": "补齐反对方外证后再决",
                },
                "evidence_ledger": [
                    {
                        "id": "#e1",
                        "url": "",
                        "title": "长约.md",
                        "snippet": "条款正文…" * 20,
                        "site": "长约.md",
                        "date": "",
                        "tier": "unknown",
                        "side_key": "evidence_pack",
                        "dossier_path": "attachments/长约.md",
                        "origin_id": "",
                        "dossier_label": "长约.md",
                    },
                    {
                        "id": "#e2",
                        "url": "https://example.com/gap",
                        "title": "补证来源",
                        "snippet": "",
                        "site": "",
                        "date": "",
                        "tier": "media",
                        "side_key": "pro",
                        "dossier_path": "",
                        "origin_id": "",
                        "dossier_label": "",
                    },
                ],
            },
        ),
        message_end(FinishReason.END_TURN, input_tokens=800, output_tokens=120, cost=_COST),
    ]

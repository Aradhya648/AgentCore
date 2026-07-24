"""旧载荷降级兼容向量 —— 无 beat / findings / thread_turns 的红队收场仍可 fold。"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    debate_result,
    message_end,
    message_start,
    run_completed,
    run_plan,
    run_started,
)

from .._common import _CONV, _COST, _USAGE
from ._builders import _moderator_agents_runs


def _multi_agent_red_team_legacy_risk_severities() -> list[SSEEvent]:
    """旧红队载荷：只有 risk_severities、无 findings/beat —— 三端 fold 降级不炸。"""
    cap, mod = "captain1", "legacy_rt_mod"
    subj_run = f"{mod}_r1_subject"
    red1_run = f"{mod}_r1_red1"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持红队审查：旧载荷兼容")
    debate_payload = {
        "form": "red_team",
        "motion": "旧磁带回放：按方风险严重度",
        "stop_reason": "red_team_exhausted",
        "narrative_first": False,
        "sides": [
            {
                "key": "subject",
                "name": "方案方",
                "stance": "方案可行",
                "is_subject": True,
                "model": "",
            },
            {
                "key": "red1",
                "name": "安全红队",
                "stance": "挖安全风险",
                "is_subject": False,
                "model": "",
            },
        ],
        "rounds": [
            {
                "round_no": 1,
                "focus": "旧场次焦点",
                "summary": "旧拓扑并行波小结。",
                "verdict": {
                    "real_clash": True,
                    "new_arguments": False,
                    "converged": True,
                    "stop_reason": "red_team_exhausted",
                    "rationale": "旧载荷无 finding 台账。",
                },
                # 故意不带 beat / findings / thread_turns
                "sides": [
                    {
                        "key": "subject",
                        "name": "方案方",
                        "run_id": subj_run,
                        "ok": True,
                        "absent": False,
                        "arguments": [],
                    },
                    {
                        "key": "red1",
                        "name": "安全红队",
                        "run_id": red1_run,
                        "ok": True,
                        "absent": False,
                        "arguments": [],
                    },
                ],
                "clashes": [],
            },
        ],
        "brief": {
            "crux": "旧风险看板",
            "strongest_points": {"red1": "有高危风险", "subject": "可修补"},
            # 旧权威字段：前端降级读 risk_severities
            "risk_severities": {"red1": "high"},
            "handoffs": [],
            "leaning": "有条件通过",
            "confidence": "low",
            "recommendation": "先看旧风险看板再决定。",
        },
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("回放一场旧红队磁带。"),
        run_plan(
            execution_id="exec_legacy_rt",
            plan_type="debate",
            task_summary="旧红队兼容",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        # 旧拓扑 = 单波并行：全员（含方案方）一个 debater plan——旧磁带回放协作图不缺席。
        run_plan(
            execution_id="exec_legacy_rt",
            plan_type="debate",
            task_summary="",
            agents=[
                {
                    "id": "d_subject",
                    "role": "方案方",
                    "thinking": True,
                },
                {
                    "id": "d_red1",
                    "role": "安全红队",
                    "thinking": True,
                },
            ],
            runs=[
                {
                    "id": subj_run,
                    "agent_id": "d_subject",
                    "task": "为方案抗辩并修补",
                    "depends_on": [],
                    "parent_run_id": mod,
                    "group": "debate:red_team",
                    "round": 1,
                },
                {
                    "id": red1_run,
                    "agent_id": "d_red1",
                    "task": "挖方案的安全风险",
                    "depends_on": [],
                    "parent_run_id": mod,
                    "group": "debate:red_team",
                    "round": 1,
                },
            ],
        ),
        run_started(subj_run, "d_subject", parent_run_id=mod),
        run_completed(
            subj_run,
            "d_subject",
            output_summary="方案方",
            duration_ms=100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(red1_run, "d_red1", parent_run_id=mod),
        run_completed(
            red1_run,
            "d_red1",
            output_summary="红队",
            duration_ms=100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="旧风险看板",
            duration_ms=200,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(
            execution_id="exec_legacy_rt", moderator_run_id=mod, payload=debate_payload
        ),
        message_end(FinishReason.END_TURN, input_tokens=100, output_tokens=50, cost=_COST),
    ]

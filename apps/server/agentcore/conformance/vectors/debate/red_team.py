"""Red-team review conformance vector — finding 台账 + 三拍拓扑。"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    debate_result,
    debate_round,
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
from ._builders import _moderator_agents_runs


def _multi_agent_red_team() -> list[SSEEvent]:
    """多 Agent：红队三拍（攻→应→复）+ finding 台账 + 门决。

    旧「按方 risk_severities」退役；brief.findings + gate + must_fix 为权威。
    cross_exam_enabled=false（三拍取代通用质询）；closings=[]（O1）。
    """
    cap, mod = "captain1", "redteam_mod1"
    red1_atk = f"{mod}_r1_red1"
    red2_atk = f"{mod}_r1_red2"
    subj_def = f"{mod}_r1_subject_defense"
    red1_reb = f"{mod}_r1_red1_rebuttal"
    red2_reb = f"{mod}_r1_red2_rebuttal"
    mod_agents, mod_runs = _moderator_agents_runs(
        mod, cap, "主持红队审查：压测「自建鉴权服务」方案"
    )
    findings = [
        {
            "id": "r1-f1",
            "severity": "critical",
            "target": "刷新令牌轮换",
            "attacker_key": "red1",
            "status": "escalated",
            "disposition": "mitigate",
            "attack_run_id": red1_atk,
            "response_run_id": subj_def,
            "rebuttal_run_id": red1_reb,
            "merged_from": [],
        },
        {
            "id": "r1-f2",
            "severity": "major",
            "target": "审计日志留存",
            "attacker_key": "red2",
            "status": "closed",
            "disposition": "accept",
            "attack_run_id": red2_atk,
            "response_run_id": subj_def,
            "rebuttal_run_id": red2_reb,
            "merged_from": [],
        },
    ]
    round_payload = {
        "round_no": 1,
        "focus": "凭证存储与会话固定的攻击面",
        "summary": "红队挖出令牌与审计两条刺；方案方逐条处置；复攻仍 escalate 令牌轮换。",
        "verdict": {
            "real_clash": True,
            "new_arguments": True,
            "converged": True,
            "stop_reason": "red_team_exhausted",
            "rationale": "critical/major 已有下场；令牌项 escalate 进加固清单。",
        },
        "sides": [
            {
                "key": "red1",
                "name": "安全红队",
                "run_id": red1_atk,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "attack",
            },
            {
                "key": "red2",
                "name": "合规红队",
                "run_id": red2_atk,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "attack",
            },
            {
                "key": "subject",
                "name": "方案方",
                "run_id": subj_def,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "defense",
            },
            {
                "key": "red1",
                "name": "安全红队",
                "run_id": red1_reb,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "rebuttal",
            },
            {
                "key": "red2",
                "name": "合规红队",
                "run_id": red2_reb,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "rebuttal",
            },
        ],
        "clashes": [],
        "user_interjections": [],
        "cross_exam": [],
        "scores": {},
        "findings": findings,
        "thread_turns": [],
    }
    debate_payload = {
        "form": "red_team",
        "motion": "压测「自建鉴权服务」方案的稳健性",
        "stop_reason": "red_team_exhausted",
        "narrative_first": False,
        "opening": "红队开场：先压测凭证存储与会话固定。",
        "sides": [
            {
                "key": "subject",
                "name": "方案方",
                "stance": "自建鉴权可控且省授权成本",
                "is_subject": True,
                "model": "",
            },
            {
                "key": "red1",
                "name": "安全红队",
                "stance": "自建鉴权的攻击面与凭证安全",
                "is_subject": False,
                "model": "",
            },
            {
                "key": "red2",
                "name": "合规红队",
                "stance": "自建鉴权的合规与审计缺口",
                "is_subject": False,
                "model": "",
            },
        ],
        "rounds": [round_payload],
        "closings": [],
        "subtopics": [],
        "brief": {
            "crux": "自建鉴权的攻击面是否可控、加固成本是否低于外采",
            "strongest_points": {
                "red1": "刷新令牌缺轮换与设备绑定，泄漏即长期可用。",
                "red2": "无审计日志留存与访问追溯，过不了等保。",
                "subject": "可引入短时访问令牌 + 轮换刷新令牌。",
            },
            "risk_severities": {},
            "findings": findings,
            "gate": "needs_major_rework",
            "must_fix": ["r1-f1"],
            "consensus_map": [],
            "handoffs": [
                {"kind": "value", "text": "把鉴权握在自己手里的掌控感 vs 外采省心？"},
                {"kind": "fact", "text": "自建 vs 外采的真实合规改造工作量"},
            ],
            "decisive": "finding r1-f1（令牌轮换）定了门决",
            "leaning": "需重大修改：先闭环 critical 再上线",
            "confidence": "medium",
            "recommendation": "上线前必须完成 r1-f1 加固并复测。",
        },
    }
    # 生产逐拍 emit debater plan：攻击波（红队并行 first_round）与回应拍（方案方单独
    # first_round）各一个 run_plan。方案方 defense 节点必须进 plan/group——否则离线回放
    # 协作图上方案方缺席、finding 的 response_run_id 挂不到发言节点。
    attack_agents = [
        {
            "id": "d_red1",
            "role": "安全红队",
            "thinking": True,
        },
        {
            "id": "d_red2",
            "role": "合规红队",
            "thinking": True,
        },
    ]
    defense_agents = [
        {
            "id": "d_subject",
            "role": "方案方",
            "thinking": True,
        },
    ]
    attack_runs = [
        {
            "id": red1_atk,
            "agent_id": "d_red1",
            "task": "挖「自建鉴权服务」方案的安全风险",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:red_team",
            "round": 1,
        },
        {
            "id": red2_atk,
            "agent_id": "d_red2",
            "task": "审「自建鉴权服务」方案的合规缺口",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:red_team",
            "round": 1,
        },
    ]
    defense_runs = [
        {
            "id": subj_def,
            "agent_id": "d_subject",
            "task": "逐条处置本轮 finding：接受/缓解/反驳/挂起",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:red_team",
            "round": 1,
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我发起一场红队审查来压测这个方案。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="红队审查：压测「自建鉴权服务」方案",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus="凭证存储与会话固定的攻击面",
            cross_exam_enabled=False,
            opening="红队开场：先压测凭证存储与会话固定。",
            form="red_team",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=attack_agents,
            runs=attack_runs,
        ),
        run_started(red1_atk, "d_red1", parent_run_id=mod),
        run_context(
            red1_atk,
            "d_red1",
            [
                _ctx_block("task", "第 1 轮·attack", "挖安全 finding"),
                _ctx_block("attack", "attack", "攻击波"),
            ],
        ),
        run_output_delta(red1_atk, "d_red1", "- [critical] 指向：刷新令牌轮换 — 泄漏即长期可用"),
        run_completed(
            red1_atk,
            "d_red1",
            output_summary="安全红队攻击完成",
            duration_ms=860,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(red2_atk, "d_red2", parent_run_id=mod),
        run_context(
            red2_atk,
            "d_red2",
            [
                _ctx_block("task", "第 1 轮·attack", "挖合规 finding"),
                _ctx_block("attack", "attack", "攻击波"),
            ],
        ),
        run_output_delta(red2_atk, "d_red2", "- [major] 指向：审计日志留存 — 过不了等保"),
        run_completed(
            red2_atk,
            "d_red2",
            output_summary="合规红队攻击完成",
            duration_ms=780,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 回应拍波次 plan（生产 first_round(sides=[方案方]) 单独 emit）——方案方进 plan/group。
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=defense_agents,
            runs=defense_runs,
        ),
        run_started(subj_def, "d_subject", parent_run_id=mod),
        run_context(
            subj_def,
            "d_subject",
            [
                _ctx_block("task", "第 1 轮·defense", "逐条处置 finding"),
                _ctx_block("defense", "defense", "回应拍"),
            ],
        ),
        run_output_delta(subj_def, "d_subject", "r1-f1 缓解：引入轮换；r1-f2 接受：补审计。"),
        run_completed(
            subj_def,
            "d_subject",
            output_summary="方案方回应完成",
            duration_ms=820,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 续写 run：agent_id = 本拍 run_id（与生产 continue_run 同构），continues_run_id 指攻击波根。
        run_started(
            red1_reb,
            red1_reb,
            parent_run_id=mod,
            continues_run_id=red1_atk,
            group="debate:red_team",
            round_no=1,
        ),
        run_context(
            red1_reb,
            red1_reb,
            [
                _ctx_block("task", "第 1 轮·rebuttal", "复核处置"),
                _ctx_block("rebuttal", "rebuttal", "复攻拍"),
            ],
        ),
        run_output_delta(red1_reb, red1_reb, "r1-f1 escalated：轮换方案仍放大惊群。"),
        run_completed(
            red1_reb,
            red1_reb,
            output_summary="安全红队复攻完成",
            duration_ms=640,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(
            red2_reb,
            red2_reb,
            parent_run_id=mod,
            continues_run_id=red2_atk,
            group="debate:red_team",
            round_no=1,
        ),
        run_context(
            red2_reb,
            red2_reb,
            [
                _ctx_block("task", "第 1 轮·rebuttal", "复核处置"),
                _ctx_block("rebuttal", "rebuttal", "复攻拍"),
            ],
        ),
        run_output_delta(red2_reb, red2_reb, "r1-f2 closed：审计补强可接受。"),
        run_completed(
            red2_reb,
            red2_reb,
            output_summary="合规红队复攻完成",
            duration_ms=520,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_round(
            execution_id="exec1",
            moderator_run_id=mod,
            payload=round_payload,
        ),
        run_completed(
            mod,
            mod,
            output_summary="自建鉴权的攻击面是否可控",
            duration_ms=2100,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(execution_id="exec1", moderator_run_id=mod, payload=debate_payload),
        message_end(FinishReason.END_TURN, input_tokens=3200, output_tokens=560, cost=_COST),
    ]

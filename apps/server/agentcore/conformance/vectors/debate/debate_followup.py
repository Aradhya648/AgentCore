"""Debate followup / user-interjection conformance vector."""

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
    run_context,
    run_output_delta,
    run_plan,
    run_started,
)

from .._common import _CONV, _COST, _USAGE, _ctx_block
from ._builders import (
    _moderator_agents_runs,
    _pro_con_debater_agents,
    _pro_con_debater_runs,
)


def _multi_agent_debate_followup() -> list[SSEEvent]:
    """多 Agent：正反辩论【收场】带【用户追问】+【3 轮版本链】（交互式逐轮 / 追问，Phase 2）。
    第 1 轮后用户向支持方【追问】「灰度期数据口径不一致谁来兜底」并选续辩，第 2、3 轮辩手
    （continue revision）逐轮续写 → 收场 ``debate_result`` 的 ``rounds[1]`` 携 verbatim
    ``user_interjections``=``[{ask, target_key:"pro", answered:true}]``——verbatim 追问痕迹
    以此为准（逐轮决策事件 D3 起虽 DURABLE，但只承载 decision/focus），三端 verbatim 折入
    ``ProjectedTurn.debate``，重载复盘可见。

    亦是【乙 wire 携 round/stance · 单一轮次投影】的 3 轮回归床（用户报的「5 轮只剩 2 版本」
    根因）：每个后续轮辩手的 ``run_started`` 携 ``stance``/``group``/``round``（r2→round 2、
    r3→round 3），三端 fold 把这三个字段投到修订节点上——故 golden 的 ``runs`` 里 pro/con 各有
    原始 + v2 + v3 三个版本、且各携真实 round，图元逐轮成链不再叠成 2 个，辩论室 2 方逐轮
    ≥2 轮发言不再丢。验「追问随轮留痕」+「修订携轮次/立场」契约全链路（types → events.ts →
    三端 verbatim fold）。"""
    cap, mod = "captain1", "debate_fu_mod1"
    pro_r1, con_r1 = f"{mod}_r1_pro", f"{mod}_r1_con"
    pro_r2, con_r2 = f"{mod}_r2_pro", f"{mod}_r2_con"
    pro_r3, con_r3 = f"{mod}_r3_pro", f"{mod}_r3_con"
    mod_agents, mod_runs = _moderator_agents_runs(
        mod, cap, "主持正反辩论（可追问）：是否采用方案 A"
    )
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_r1,
        con_r1,
        pro_task="论证支持采用方案 A",
        con_task="论证反对采用方案 A",
    )
    round1_payload = {
        "round_no": 1,
        "focus": "方案 A 的收益与风险敞口",
        "summary": "支持方强调收益可量化，反对方指出缺乏风险兜底，焦点收敛到风险可控性。",
        "verdict": {
            "real_clash": True,
            "new_arguments": True,
            "converged": False,
            "stop_reason": "",
            "rationale": "核心交锋已起，但风险兜底尚未谈透，值得再探一轮。",
        },
        "sides": [
            {"key": "pro", "name": "支持方", "run_id": pro_r1, "ok": True, "absent": False, "arguments": []},
            {"key": "con", "name": "反对方", "run_id": con_r1, "ok": True, "absent": False, "arguments": []},
        ],
        "clashes": [
            {
                "from_key": "con",
                "to_key": "pro",
                "point": "收益可量化但未对冲风险敞口，量化口径回避了尾部风险。",
            },
        ],
        # 第 1 轮无前序边界 ⇒ 无用户追问（载荷形状统一，恒带空列表）。
        "user_interjections": [],
        # 记分裁判（P2）：首轮各方咬合但未见底，支持方量化更实、小幅领先（净分 9 : 8）。
        "scores": {
            "pro": {
                "argument": 4, "engagement": 2, "evidence": 3,
                "penalties": [], "note": "收益量化扎实，但尚未正面接住风险兜底。", "total": 9,
            },
            "con": {
                "argument": 3, "engagement": 3, "evidence": 2,
                "penalties": [], "note": "风险敞口命门抓得准，缺量化证据。", "total": 8,
            },
        },
    }
    round2_payload = {
        "round_no": 2,
        "focus": "灰度期数据口径不一致时的兜底机制",
        "summary": "支持方正面回应追问：灰度期以反对方数据口径为准并设熔断；分歧收敛到阈值该如何设。",
        "verdict": {
            "real_clash": True,
            "new_arguments": True,
            "converged": False,
            "stop_reason": "",
            "rationale": "支持方接住追问、给出兜底，但回滚/熔断阈值该多严仍有实质分歧，值得再探一轮。",
        },
        "sides": [
            {"key": "pro", "name": "支持方", "run_id": pro_r2, "ok": True, "absent": False, "arguments": []},
            {"key": "con", "name": "反对方", "run_id": con_r2, "ok": True, "absent": False, "arguments": []},
        ],
        "clashes": [
            {
                "from_key": "con",
                "to_key": "pro",
                "point": "以反对方口径为准虽稳妥，但熔断阈值过松仍可能放大尾部风险。",
            },
        ],
        # 用户在第 1 轮边界向【支持方】追问、本轮承接回应（verbatim 复盘单元）。
        "user_interjections": [
            {
                "ask": "灰度期如果出现数据口径不一致，谁来兜底、按谁的口径？",
                "target_key": "pro",
                "answered": True,
            },
        ],
        # 记分裁判（P2）：胜负手拉开轮——支持方正面接住追问、给出灰度兜底（回应完整度跳到 4），反对方
        # 回避了成本归属被扣分（净分 11 : 7）。
        "scores": {
            "pro": {
                "argument": 4, "engagement": 4, "evidence": 3,
                "penalties": [], "note": "正面接住追问、给出保守口径 + 熔断兜底。", "total": 11,
            },
            "con": {
                "argument": 3, "engagement": 3, "evidence": 2,
                "penalties": ["回避了灰度兜底的成本归属"],
                "note": "仍质疑熔断阈值，但对成本归属避而不答。", "total": 7,
            },
        },
    }
    round3_payload = {
        "round_no": 3,
        "focus": "回滚与熔断阈值该如何设定",
        "summary": "支持方提出按尾部损失分位设阈并自动回滚，反对方认可机制、仅保留阈值取值分歧，收敛到价值取舍。",
        "verdict": {
            "real_clash": True,
            "new_arguments": False,
            "converged": True,
            "stop_reason": "兜底机制已谈透，仅剩阈值取值这一价值判断需用户拍板。",
            "rationale": "阈值机制双方达成一致，取值严松是风险偏好取舍、AI 判不了，交用户拍板。",
        },
        "sides": [
            {"key": "pro", "name": "支持方", "run_id": pro_r3, "ok": True, "absent": False, "arguments": []},
            {"key": "con", "name": "反对方", "run_id": con_r3, "ok": True, "absent": False, "arguments": []},
        ],
        "clashes": [
            {
                "from_key": "con",
                "to_key": "pro",
                "point": "按分位设阈方向对，但分位取多少直接决定放行多少尾部风险，仍需拍板。",
            },
        ],
        # 第 3 轮无新的用户追问（载荷形状统一，恒带空列表）。
        "user_interjections": [],
        # 记分裁判（P2）：收敛轮——阈值机制达成一致、双方势均力敌（净分 10 : 10），仅剩阈值取值待拍板。
        "scores": {
            "pro": {
                "argument": 3, "engagement": 4, "evidence": 3,
                "penalties": [], "note": "按分位设阈 + 自动回滚，机制落地。", "total": 10,
            },
            "con": {
                "argument": 3, "engagement": 4, "evidence": 3,
                "penalties": [], "note": "认可机制，保留阈值取值分歧。", "total": 10,
            },
        },
    }
    debate_payload = {
        "form": "debate",
        "motion": "是否采用方案 A",
        "stop_reason": "converged",
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
        "rounds": [round1_payload, round2_payload, round3_payload],
        "brief": {
            "crux": "方案 A 的风险是否可控、灰度兜底是否到位",
            "strongest_points": {
                "pro": "收益显著且可量化，已就追问给出灰度兜底（保守口径 + 熔断 + 按分位设阈自动回滚）",
                "con": "风险敞口缺乏兜底，熔断阈值仍可能过松",
            },
            "handoffs": [
                {"kind": "value", "text": "增长优先 vs 稳健优先"},
                {"kind": "fact", "text": "历史故障率的数据口径不一致"},
                # 用户追问已被回应、但仅剩的阈值取舍上交用户拍板（追问不石沉大海）。
                {
                    "kind": "question",
                    "text": "灰度的回滚/熔断阈值取多少（你的追问已促成兜底，取值仍需你定）？",
                },
            ],
            # 胜负手（P2）：据逐轮记分累计（净分 30 : 25）——胜负手在第 2 轮拉开。
            "decisive": "胜负手在第 2 轮：支持方正面接住你的追问、给出灰度兜底（回应完整度跳升），反对方却回避成本归属被扣分；第 3 轮双方就阈值机制达成一致。累计净分 30 : 25，支持方占优，仅剩阈值取值是价值取舍。",
            "leaning": "倾向有条件采用",
            "confidence": "medium",
            "recommendation": "采纳支持方的灰度兜底方案（按分位设阈 + 自动回滚），阈值取值需你拍板。",
        },
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我发起一场可追问的正反辩论来定夺。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="正反辩论（可追问）：是否采用方案 A",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus="方案 A 的收益与风险敞口",
            cross_exam_enabled=True,
            opening="这场可追问辩论：先把方案 A 的收益与风险敞口说清。",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_r1, "d_pro", parent_run_id=mod),
        run_output_delta(pro_r1, "d_pro", "支持理由：收益可量化。"),
        run_completed(
            pro_r1,
            "d_pro",
            output_summary="支持方陈述完成",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_r1, "d_con", parent_run_id=mod),
        run_output_delta(con_r1, "d_con", "反对理由：风险无兜底。"),
        run_completed(
            con_r1,
            "d_con",
            output_summary="反对方陈述完成",
            duration_ms=850,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 第 2 轮：辩手 continue revision（parent=首轮 run，revision=2）回应用户追问。乙 wire
        # 携 round/stance：修订 run_started 携 stance/group + 真实 round=2，三端 fold 投到修订
        # 节点上（单一轮次投影）。
        run_started(
            pro_r2, pro_r2, parent_run_id=mod, continues_run_id=pro_r1,
            stance="pro", group="debate:debate", round_no=2,
        ),
        # 续写轮收到的上下文：task=真实 feedback 孪生 + 浓缩材料块（焦点 / 追问 / 对方）。
        run_context(
            pro_r2,
            pro_r2,
            [
                _ctx_block(
                    "task",
                    "第 2 轮任务",
                    "## 第 2 轮 · 本轮焦点：灰度期的兜底与熔断机制\n"
                    "⚠️ 用户在本轮追问（向你提出）：\n- 灰度期谁来兜底？\n"
                    "对方上一轮的论点如下，请针对性回应。",
                ),
                _ctx_block("round_focus", "第 2 轮 · 本轮焦点", "灰度期的兜底与熔断机制"),
                _ctx_block(
                    "interjection",
                    "用户本轮追问（向你提出 · 最高优先级）",
                    "- 灰度期谁来兜底？",
                ),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 反方",
                    "反对理由：风险无兜底。",
                    source_role="反方",
                    source_run_id=con_r1,
                ),
            ],
        ),
        run_output_delta(pro_r2, pro_r2, "回应追问：灰度以保守口径为准并设熔断。"),
        run_completed(
            pro_r2,
            pro_r2,
            output_summary="支持方回应追问完成",
            duration_ms=820,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(
            con_r2, con_r2, parent_run_id=mod, continues_run_id=con_r1,
            stance="con", group="debate:debate", round_no=2,
        ),
        run_context(
            con_r2,
            con_r2,
            [
                _ctx_block(
                    "task",
                    "第 2 轮任务",
                    "## 第 2 轮 · 本轮焦点：灰度期的兜底与熔断机制\n"
                    "对方上一轮的论点如下，请针对性回应。",
                ),
                _ctx_block("round_focus", "第 2 轮 · 本轮焦点", "灰度期的兜底与熔断机制"),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 正方",
                    "支持理由：收益可量化。",
                    source_role="正方",
                    source_run_id=pro_r1,
                ),
                _ctx_block(
                    "challenge",
                    "上一轮你被反驳的命门",
                    "- 正方：收益可量化，风险可用熔断兜底，并非无解。",
                ),
            ],
        ),
        run_output_delta(con_r2, con_r2, "仍存疑：熔断阈值过松。"),
        run_completed(
            con_r2,
            con_r2,
            output_summary="反对方续论完成",
            duration_ms=830,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 第 3 轮：再续写一轮（revision=3 / round=3）。续写 parent 恒为【原始首轮 run】
        # （session.run_id 跨轮不变）——修订是绕原始的「星」，revisionOf 全指向 pro_r1；图层据
        # revision 排序把星铺成 原始→v2→v3 的链，验多轮不塌成 2 版本。
        run_started(
            pro_r3, pro_r3, parent_run_id=mod, continues_run_id=pro_r1,
            stance="pro", group="debate:debate", round_no=3,
        ),
        run_context(
            pro_r3,
            pro_r3,
            [
                _ctx_block(
                    "task",
                    "第 3 轮任务",
                    "## 第 3 轮 · 本轮焦点：熔断阈值如何取值\n对方上一轮的论点如下，请针对性回应。",
                ),
                _ctx_block("round_focus", "第 3 轮 · 本轮焦点", "熔断阈值如何取值"),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 反方",
                    "仍存疑：熔断阈值过松。",
                    source_role="反方",
                    source_run_id=con_r2,
                ),
            ],
        ),
        run_output_delta(pro_r3, pro_r3, "收敛：按尾部损失分位设阈并自动回滚。"),
        run_completed(
            pro_r3,
            pro_r3,
            output_summary="支持方第三轮收敛完成",
            duration_ms=810,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(
            con_r3, con_r3, parent_run_id=mod, continues_run_id=con_r1,
            stance="con", group="debate:debate", round_no=3,
        ),
        run_context(
            con_r3,
            con_r3,
            [
                _ctx_block(
                    "task",
                    "第 3 轮任务",
                    "## 第 3 轮 · 本轮焦点：熔断阈值如何取值\n对方上一轮的论点如下，请针对性回应。",
                ),
                _ctx_block("round_focus", "第 3 轮 · 本轮焦点", "熔断阈值如何取值"),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 正方",
                    "回应追问：灰度以保守口径为准并设熔断。",
                    source_role="正方",
                    source_run_id=pro_r2,
                ),
            ],
        ),
        run_output_delta(con_r3, con_r3, "认可机制，仅阈值取值仍需拍板。"),
        run_completed(
            con_r3,
            con_r3,
            output_summary="反对方第三轮收敛完成",
            duration_ms=820,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="灰度兜底已达成，仅剩阈值取值待你拍板",
            duration_ms=2800,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(execution_id="exec1", moderator_run_id=mod, payload=debate_payload),
        message_end(FinishReason.END_TURN, input_tokens=3600, output_tokens=620, cost=_COST),
    ]

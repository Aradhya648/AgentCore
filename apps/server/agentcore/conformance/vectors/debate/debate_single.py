"""Single-beat adversarial debate conformance vector."""

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


def _multi_agent_debate() -> list[SSEEvent]:
    """多 Agent：辩论（debate 工具 / 主持人驱动）。两段 run_plan(plan_type="debate")——先声明
    主持人节点（CEO 不进图，主持人 ``parent_run_id`` 引用 CEO captain run、节点不在图），再声明
    本轮正反辩手（携 stance/group/round，parent=主持人）；主持人走 run_started→run_completed
    完整生命周期（团队进度因此 3/3 正确收尾，不再有永久 pending 的编排节点），收场 debate_result
    承载【决策简报 + 交锋叙事线】双产物——三端 verbatim 折入 ProjectedTurn.debate，各方发言全文
    靠 rounds[*].sides[*].run_id 关联执行图辩手节点。

    亦承载【质询回合 P1 + 记分裁判 P2】端到端契约：本轮 ``cross_exam`` = 主持人代表交锋向各方发的
    定向必答质询（问题 verbatim 进载荷、作答全文随 ``answer_run_id`` 的 continue_run 事件走，故各方
    多出一个 ``_r1_cx_{key}`` 质询作答 run——faithful：作答是 continue_run，run_started 携 revision=2 +
    原辩手 stance/group/round）；``scores`` = 裁判本轮给各方的三维记分 + 罚分 + 净分；``brief.decisive``
    = 据逐轮记分推导的胜负手。三者均为附加字段（settledModel 据 answer_run_id 取回作答、据 scores/
    decisive 渲染比分与胜负手），载荷恒带空集合/空对象。

    亦承载【结辩收束 P4】端到端契约：收场 ``closings`` = 辩已辩尽后各方的结辩陈词（身份 verbatim 进载荷、
    陈词全文随 ``run_id`` 的 continue_run 事件走，故各方在质询后再多一个 ``_closing_{key}`` 结辩 run——
    faithful：结辩是 continue_run，run_started 携 revision=3 + 原辩手 stance/group/round）；settledModel 据
    ``closings[*].run_id`` 取回陈词全文渲染「结辩陈词」区。载荷恒带空集合/空对象。"""
    cap, mod = "captain1", "debate_mod1"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    pro_cx, con_cx = f"{mod}_r1_cx_pro", f"{mod}_r1_cx_con"
    pro_closing, con_closing = f"{mod}_closing_pro", f"{mod}_closing_con"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持正反辩论：是否采用方案 A")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="论证支持采用方案 A",
        con_task="论证反对采用方案 A",
    )
    debate_payload = {
        "form": "debate",
        "motion": "是否采用方案 A",
        "stop_reason": "converged",
        # 主持人开场白（可选、渐进式契约）：证明「会说话的主持人」开场白经 fold verbatim 折入
        # ProjectedTurn.debate.opening 的端到端链路；其余向量省略此字段验证缺省回落
        # （opening 空 → 前端不渲染主持人入场，不再拼模板假冒开口）。
        "opening": "这场要定的是该不该上方案 A，先从最要害的成本与收益切入。",
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
                "focus": "方案 A 的收益与风险敞口",
                "summary": "支持方强调收益可量化，反对方指出缺乏风险兜底，焦点收敛到风险可控性。",
                "verdict": {
                    "real_clash": True,
                    "new_arguments": False,
                    "converged": True,
                    "stop_reason": "双方核心分歧已充分暴露，无新论据。",
                    "rationale": "争点收敛到风险可控性这一关键点，继续无新增信息。",
                },
                "sides": [
                    {
                        "key": "pro",
                        "name": "支持方",
                        "run_id": pro_run,
                        "ok": True,
                        "absent": False,
                        "arguments": [
                            {
                                "id": "arg-0",
                                "title": "支持理由：收益可量化",
                                "body": (
                                    "支持理由：收益可量化——首年可降本【已核实·2024成本审计】约 18%，"
                                    "同类系统迁移回收周期约两个季度【待核实·推断】。"
                                ),
                            }
                        ],
                    },
                    {
                        "key": "con",
                        "name": "反对方",
                        "run_id": con_run,
                        "ok": True,
                        "absent": False,
                        "arguments": [
                            {
                                "id": "arg-0",
                                "title": "反对理由：风险缺兜底",
                                "body": (
                                    "反对理由：风险缺兜底——迁移期存在双写不一致窗口【已核实·内部SRE复盘】，"
                                    "尾部故障率恐被低估【待核实·推断】。"
                                ),
                            }
                        ],
                    },
                ],
                "clashes": [
                    {
                        "from_key": "con",
                        "to_key": "pro",
                        "point": "收益可量化但未对冲风险敞口，量化口径回避了尾部风险。",
                    },
                ],
                # 质询回合（P1）：主持人定向必答质询各方，作答全文随 answer_run_id 的 run 走（不塞载荷）。
                "cross_exam": [
                    {
                        "target": "pro",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "收益量化口径是否计入了尾部风险？请是/否直接回答。",
                                "answer": "量化口径未含尾部风险【待核实·推断】",
                            },
                            {
                                "question": "若熔断触发、灰度止损，已投入成本由谁承担？",
                                "answer": "成本由灰度预算池兜底、触发熔断即回滚【已核实·灰度预案v2】",
                            },
                        ],
                        "answer_run_id": pro_cx,
                    },
                    {
                        "target": "con",
                        "questioner": "",
                        "exchanges": [
                            {
                                "question": "你主张的风险敞口，有无可量化的历史故障率支撑？没有就直说。",
                                "answer": "暂无统一口径的历史故障率【待核实·推断】；但同类系统的尾部事件可作参照【已核实·SRE年报】",
                            },
                        ],
                        "answer_run_id": con_cx,
                    },
                ],
                # 记分裁判（P2）：本轮各方三维记分 + 罚分（每条 -1）+ 净分 total（后端算好、前端直用）。
                "scores": {
                    "pro": {
                        "argument": 4,
                        "engagement": 3,
                        "evidence": 3,
                        "penalties": [],
                        "note": "收益量化扎实，质询下承认口径未含尾部但给出熔断兜底。",
                        "total": 10,
                    },
                    "con": {
                        "argument": 3,
                        "engagement": 4,
                        "evidence": 2,
                        "penalties": ["以未证实的尾部风险当既定事实"],
                        "note": "紧咬风险敞口命门、回应完整，但缺量化证据且有一处未支撑主张。",
                        "total": 8,
                    },
                },
            },
        ],
        # 结辩收束（P4）：辩已辩尽后各方的结辩陈词（身份 verbatim 进载荷、陈词全文随 run_id 的 run 走），
        # settledModel 据 closings[*].run_id 取回渲染「结辩陈词」区。仅认真辩透 + 对抗形态开启。
        "closings": [
            {"key": "pro", "name": "支持方", "run_id": pro_closing, "ok": True},
            {"key": "con", "name": "反对方", "run_id": con_closing, "ok": True},
        ],
        "brief": {
            "crux": "方案 A 的风险是否可控",
            "strongest_points": {"pro": "收益显著且可量化", "con": "风险敞口缺乏兜底"},
            "handoffs": [
                {"kind": "value", "text": "增长优先 vs 稳健优先"},
                {"kind": "fact", "text": "历史故障率的数据口径不一致"},
                {"kind": "question", "text": "灰度的回滚阈值如何设定？"},
            ],
            # 胜负手（P2）：据逐轮记分推导——点名谁的哪点被扣分 / 更站得住，让 leaning 可追溯。
            "decisive": "反对方紧咬「风险敞口未对冲」命门，却把未证实的尾部风险当既定事实（记分 -1）；支持方收益量化更扎实、质询下给出熔断兜底，综合净分小幅领先（10 : 8）。",
            "leaning": "倾向有条件采用",
            "confidence": "medium",
            "recommendation": "先小流量灰度验证风险，再决定是否全量。",
        },
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我发起一场正反辩论来定夺。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="正反辩论：是否采用方案 A",
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
            opening="这场要定的是该不该上方案 A，先从最要害的成本与收益切入。",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(pro_run, "d_pro", parent_run_id=mod),
        run_output_delta(
            pro_run,
            "d_pro",
            "支持理由：收益可量化——首年可降本【已核实·2024成本审计】约 18%，"
            "同类系统迁移回收周期约两个季度【待核实·推断】。",
        ),
        run_completed(
            pro_run,
            "d_pro",
            output_summary="支持方陈述完成",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(con_run, "d_con", parent_run_id=mod),
        run_output_delta(
            con_run,
            "d_con",
            "反对理由：风险缺兜底——迁移期存在双写不一致窗口【已核实·内部SRE复盘】，"
            "尾部故障率恐被低估【待核实·推断】。",
        ),
        run_completed(
            con_run,
            "d_con",
            output_summary="反对方陈述完成",
            duration_ms=850,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 质询回合（P1）：陈述后、裁判前，各方对主持人质询 continue_run 作答（faithful：作答是续写，
        # run_started 携 revision=2 + 原辩手 stance/group/round；run_context 首块 task=真实 feedback
        # 逐字孪生 + cross_exam 清单块（beat presence）；作答全文随本 run 走）。
        run_started(
            pro_cx, pro_cx, parent_run_id=mod, continues_run_id=pro_run,
            stance="pro", group="debate:debate", round_no=1, side_key="pro",
        ),
        run_context(
            pro_cx,
            pro_cx,
            [
                _ctx_block(
                    "task",
                    "质询环节",
                    "## 第 1 轮 · 质询环节（本轮焦点：方案 A 的收益与风险敞口）\n"
                    "主持人代表交锋，向你发出以下【必须正面回答】的质询。"
                    "请按「### 质询一」「### 质询二」标题逐条正面作答。\n"
                    "质询列表（共 2 条）：\n"
                    "1. 收益量化口径是否计入了尾部风险？请是/否直接回答。\n"
                    "2. 若熔断触发、灰度止损，已投入成本由谁承担？",
                ),
                _ctx_block(
                    "cross_exam",
                    "第 1 轮 · 质询（必须正面回答）",
                    "- 收益量化口径是否计入了尾部风险？请是/否直接回答。\n"
                    "- 若熔断触发、灰度止损，已投入成本由谁承担？",
                ),
            ],
        ),
        run_output_delta(
            pro_cx,
            pro_cx,
            "### 质询一\n"
            "量化口径未含尾部风险【待核实·推断】\n\n"
            "### 质询二\n"
            "成本由灰度预算池兜底、触发熔断即回滚【已核实·灰度预案v2】",
        ),
        run_completed(
            pro_cx,
            pro_cx,
            output_summary="支持方质询作答完成",
            duration_ms=640,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(
            con_cx, con_cx, parent_run_id=mod, continues_run_id=con_run,
            stance="con", group="debate:debate", round_no=1, side_key="con",
        ),
        run_context(
            con_cx,
            con_cx,
            [
                _ctx_block(
                    "task",
                    "质询环节",
                    "## 第 1 轮 · 质询环节（本轮焦点：方案 A 的收益与风险敞口）\n"
                    "主持人代表交锋，向你发出以下【必须正面回答】的质询。"
                    "请按「### 质询一」标题逐条正面作答。\n"
                    "质询列表（共 1 条）：\n"
                    "1. 你主张的风险敞口，有无可量化的历史故障率支撑？没有就直说。",
                ),
                _ctx_block(
                    "cross_exam",
                    "第 1 轮 · 质询（必须正面回答）",
                    "- 你主张的风险敞口，有无可量化的历史故障率支撑？没有就直说。",
                ),
            ],
        ),
        run_output_delta(
            con_cx,
            con_cx,
            "### 质询一\n"
            "暂无统一口径的历史故障率【待核实·推断】；但同类系统的尾部事件可作参照"
            "【已核实·SRE年报】",
        ),
        run_completed(
            con_cx,
            con_cx,
            output_summary="反对方质询作答完成",
            duration_ms=620,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        # 结辩收束（P4）：质询后、主持人终审前，各方 continue_run 做结辩陈词（faithful：结辩是续写，
        # run_started 携 revision=3；run_context 首块 task=closing_task 逐字孪生 + closing 通道纯环节标记）。
        run_started(
            pro_closing, pro_closing, parent_run_id=mod, continues_run_id=pro_run,
            stance="pro", group="debate:debate", round_no=1, side_key="pro",
        ),
        run_context(
            pro_closing,
            pro_closing,
            [
                _ctx_block(
                    "task",
                    "结辩环节",
                    "## 结辩环节（本场辩论已充分交锋，现在请你做【结辩陈词】）\n"
                    "这是你的**最后陈词**，不是新一轮立论——请【只讲胜负手】；"
                    "【不得引入任何新论据 / 新事实 / 新案例】。直接输出你的结辩陈词。",
                ),
                _ctx_block("closing", "结辩环节", "本场辩论已充分交锋，现请做结辩陈词。"),
            ],
        ),
        run_output_delta(
            pro_closing,
            pro_closing,
            "结辩：方案 A 首年降本可核实【已核实·2024成本审计】，尾部风险有熔断兜底、"
            "触发即回滚可控——收益确定、风险有解，应有条件采用。",
        ),
        run_completed(
            pro_closing,
            pro_closing,
            output_summary="支持方结辩完成",
            duration_ms=520,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(
            con_closing, con_closing, parent_run_id=mod, continues_run_id=con_run,
            stance="con", group="debate:debate", round_no=1, side_key="con",
        ),
        run_context(
            con_closing,
            con_closing,
            [
                _ctx_block(
                    "task",
                    "结辩环节",
                    "## 结辩环节（本场辩论已充分交锋，现在请你做【结辩陈词】）\n"
                    "这是你的**最后陈词**，不是新一轮立论——请【只讲胜负手】；"
                    "【不得引入任何新论据 / 新事实 / 新案例】。直接输出你的结辩陈词。",
                ),
                _ctx_block("closing", "结辩环节", "本场辩论已充分交锋，现请做结辩陈词。"),
            ],
        ),
        run_output_delta(
            con_closing,
            con_closing,
            "结辩：对方的收益量化口径始终未含尾部风险【待核实·推断】，双写不一致窗口"
            "【已核实·内部SRE复盘】未有硬兜底——风险未对冲前不宜全量。",
        ),
        run_completed(
            con_closing,
            con_closing,
            output_summary="反对方结辩完成",
            duration_ms=540,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="方案 A 的风险是否可控",
            duration_ms=2000,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(execution_id="exec1", moderator_run_id=mod, payload=debate_payload),
        message_end(FinishReason.END_TURN, input_tokens=3000, output_tokens=500, cost=_COST),
    ]

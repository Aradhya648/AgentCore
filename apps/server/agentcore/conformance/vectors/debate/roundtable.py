"""Roundtable debate conformance vectors (in-progress rounds + settled)."""

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


def _multi_agent_roundtable_rounds() -> list[SSEEvent]:
    """多 Agent：圆桌（roundtable）逐轮增量 + 中途取消。主持人逐轮 emit ``debate_round_started``
    （发言【前】给焦点）/ ``debate_round``（裁判 + 小结【后】给整轮）——三端折叠成 ProjectedTurn.
    debateRounds：第 1 轮完整（focus/summary/verdict/各方→辩手 run_id），第 2 轮仅开场
    （focus，verdict=None=进行中）后被取消。后续轮辩手是首轮的续写 revision（``revision=2`` +
    ``parent_run_id``，三端从 run_started 合成修订节点 + 继承原 agent 身份）。无 ``debate_result``
    （中途停）→ debate 恒 None，叙事线只在 debateRounds（这正是进行中实时叠加的覆盖点）。
    圆桌辩手节点携 ``group=debate:roundtable`` + ``round`` 但【无 stance】（多方非二元正反）。"""
    cap, mod = "captain1", "rt_mod1"
    r1a, r1b, r1c = f"{mod}_r1_a", f"{mod}_r1_b", f"{mod}_r1_c"
    r2a, r2b = f"{mod}_r2_a", f"{mod}_r2_b"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持多方圆桌：AI 该如何治理")
    debater_agents = [
        {
            "id": "rt_a",
            "role": "技术视角",
            "thinking": True,
        },
        {
            "id": "rt_b",
            "role": "监管视角",
            "thinking": True,
        },
        {
            "id": "rt_c",
            "role": "产业视角",
            "thinking": True,
        },
    ]
    debater_runs = [
        {
            "id": r1a,
            "agent_id": "rt_a",
            "task": "从技术视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
        {
            "id": r1b,
            "agent_id": "rt_b",
            "task": "从监管视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
        {
            "id": r1c,
            "agent_id": "rt_c",
            "task": "从产业视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
    ]
    round1_payload = {
        "round_no": 1,
        "focus": "AI 治理的第一性问题：风险从何而来",
        "summary": "技术方归因能力外溢，监管方强调问责缺位，产业方提醒落地成本，焦点铺成三条光谱。",
        "verdict": {
            "real_clash": True,
            "new_arguments": True,
            "converged": False,
            "stop_reason": "",
            "rationale": "三方视角已铺开但尚未交锋收敛，值得再探一轮。",
        },
        "sides": [
            {
                "key": "a",
                "name": "技术视角",
                "run_id": r1a,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "thread",
            },
            {
                "key": "b",
                "name": "监管视角",
                "run_id": r1b,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "thread",
            },
            {
                "key": "c",
                "name": "产业视角",
                "run_id": r1c,
                "ok": True,
                "absent": False,
                "arguments": [],
                "beat": "thread",
            },
        ],
        "clashes": [
            {
                "from_key": "b",
                "to_key": "a",
                "point": "能力外溢说回避了问责主体，技术归因不能替代责任分配。",
            },
            {
                "from_key": "c",
                "to_key": "b",
                "point": "强问责会抬高合规成本，产业落地承受不起一刀切立法。",
            },
        ],
        "findings": [],
        "thread_turns": [
            {"speaker": "a", "reply_to": "", "run_id": r1a, "ok": True, "beat": "thread"},
            {"speaker": "b", "reply_to": "a", "run_id": r1b, "ok": True, "beat": "thread"},
            {"speaker": "c", "reply_to": "b", "run_id": r1c, "ok": True, "beat": "thread"},
        ],
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场多方圆桌。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="多方圆桌：AI 该如何治理",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        # 第 1 轮：开场先报焦点（发言【前】）+ 开场白，再声明本轮辩手 + 各方发言，收尾报整轮裁判 + 小结。
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus=round1_payload["focus"],
            cross_exam_enabled=False,
            opening="圆桌开场：先问 AI 治理的风险从何而来。",
            form="roundtable",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(r1a, "rt_a", parent_run_id=mod),
        run_output_delta(r1a, "rt_a", "技术视角：能力外溢是根因。"),
        run_completed(
            r1a,
            "rt_a",
            output_summary="技术视角发言完成",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(r1b, "rt_b", parent_run_id=mod),
        run_output_delta(r1b, "rt_b", "监管视角：问责缺位才是关键。"),
        run_completed(
            r1b,
            "rt_b",
            output_summary="监管视角发言完成",
            duration_ms=820,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(r1c, "rt_c", parent_run_id=mod),
        run_output_delta(r1c, "rt_c", "产业视角：别忽视落地成本。"),
        run_completed(
            r1c,
            "rt_c",
            output_summary="产业视角发言完成",
            duration_ms=810,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_round(execution_id="exec1", moderator_run_id=mod, payload=round1_payload),
        # 第 2 轮：开场报焦点（verdict 仍 None=进行中），辩手续写（revision=2）发言中被取消。
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=2,
            focus="第二轮：三方就『问责机制』正面交锋",
            cross_exam_enabled=False,
        ),
        # 乙 wire 携 round/stance（多方无 stance）：续写携 group + 真实 round=2，三端 fold 投到
        # 修订节点上，debateLiveRounds 据 round 而非版本号铺轮次（单一轮次投影）。
        run_started(
            r2a, "rt_a2", parent_run_id=mod, continues_run_id=r1a,
            group="debate:roundtable", round_no=2,
        ),
        # 圆桌续写轮：task=真实 feedback 孪生 + 焦点 + 其余各方上轮论点。
        run_context(
            r2a,
            "rt_a2",
            [
                _ctx_block(
                    "task",
                    "第 2 轮任务",
                    "## 第 2 轮 · 本轮焦点：三方就『问责机制』正面交锋\n"
                    "对方上一轮的论点如下，请回应并补充。",
                ),
                _ctx_block("round_focus", "第 2 轮 · 本轮焦点", "三方就『问责机制』正面交锋"),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 监管视角",
                    "监管视角：问责缺位才是关键。",
                    source_role="监管视角",
                    source_run_id=r1b,
                ),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 产业视角",
                    "产业视角：别忽视落地成本。",
                    source_role="产业视角",
                    source_run_id=r1c,
                ),
            ],
        ),
        run_output_delta(r2a, "rt_a2", "技术视角续：问责需可观测性支撑。"),
        run_started(
            r2b, "rt_b2", parent_run_id=mod, continues_run_id=r1b,
            group="debate:roundtable", round_no=2,
        ),
        run_context(
            r2b,
            "rt_b2",
            [
                _ctx_block(
                    "task",
                    "第 2 轮任务",
                    "## 第 2 轮 · 本轮焦点：三方就『问责机制』正面交锋\n"
                    "对方上一轮的论点如下，请回应并补充。",
                ),
                _ctx_block("round_focus", "第 2 轮 · 本轮焦点", "三方就『问责机制』正面交锋"),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 技术视角",
                    "技术视角：能力外溢是根因。",
                    source_role="技术视角",
                    source_run_id=r1a,
                ),
                _ctx_block(
                    "opponent",
                    "对方上一轮 · 产业视角",
                    "产业视角：别忽视落地成本。",
                    source_role="产业视角",
                    source_run_id=r1c,
                ),
            ],
        ),
        run_output_delta(r2b, "rt_b2", "监管视角续：可观测性应立法强制。"),
        message_end(FinishReason.CANCELLED, input_tokens=4000, output_tokens=700, cost=_COST),
    ]

def _multi_agent_roundtable_settled() -> list[SSEEvent]:
    """多 Agent：圆桌探讨【收场】(roundtable settled)。3 视角多边碰撞后主持人收场，debate_result
    (form="roundtable") 承载【观点光谱 + 交锋叙事线】双产物：strongest_points 按 side.key 给各视角
    核心主张（光谱），leaning=综合观察、recommendation=建议。探讨无单一裁决/赢家。验「观点光谱」英雄
    区（置顶 glanceable）+ 叙事后简报小结（共同焦点一行 / 需你拍板 / 还需厘清），与正反/红队同一套
    次级信息主次（去掉旧版等权 DisputeSection，三形态一致）。圆桌辩手无 stance（多方非二元正反）。"""
    cap, mod = "captain1", "rts_mod1"
    ra, rb, rc = f"{mod}_r1_a", f"{mod}_r1_b", f"{mod}_r1_c"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, "主持多方圆桌：AI 该如何治理")
    debater_agents = [
        {
            "id": "rt_a",
            "role": "技术视角",
            "thinking": True,
        },
        {
            "id": "rt_b",
            "role": "监管视角",
            "thinking": True,
        },
        {
            "id": "rt_c",
            "role": "产业视角",
            "thinking": True,
        },
    ]
    debater_runs = [
        {
            "id": ra,
            "agent_id": "rt_a",
            "task": "从技术视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
        {
            "id": rb,
            "agent_id": "rt_b",
            "task": "从监管视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
        {
            "id": rc,
            "agent_id": "rt_c",
            "task": "从产业视角谈 AI 治理",
            "depends_on": [],
            "parent_run_id": mod,
            "group": "debate:roundtable",
            "round": 1,
        },
    ]
    debate_payload = {
        "form": "roundtable",
        "motion": "AI 该如何治理",
        "stop_reason": "converged",
        "narrative_first": False,
        # 圆桌≥3 视角，语义名对称同风格（技术 / 监管 / 产业视角）；无 is_subject、无 stance。
        "sides": [
            {
                "key": "a",
                "name": "技术视角",
                "stance": "风险源于能力外溢，治理应内建可观测与熔断",
                "is_subject": False,
                "model": "",
            },
            {
                "key": "b",
                "name": "监管视角",
                "stance": "缺的是问责主体，须以立法明确责任归属",
                "is_subject": False,
                "model": "",
            },
            {
                "key": "c",
                "name": "产业视角",
                "stance": "一刀切立法抬高合规成本，应分级分场景落地",
                "is_subject": False,
                "model": "",
            },
        ],
        "rounds": [
            {
                "round_no": 1,
                "focus": "AI 治理的主轴：先管能力还是先管问责",
                "summary": "技术方归因能力外溢，监管方强调问责缺位，产业方提醒落地成本，三方收敛到分级治理。",
                "verdict": {
                    "real_clash": True,
                    "new_arguments": False,
                    "converged": True,
                    "stop_reason": "三方视角已充分铺开并就分级治理形成交集。",
                    "rationale": "光谱铺满且出现交集，继续无新增视角。",
                },
                "sides": [
                    {
                        "key": "a",
                        "name": "技术视角",
                        "run_id": ra,
                        "ok": True,
                        "absent": False,
                        "arguments": [],
                        "beat": "thread",
                    },
                    {
                        "key": "b",
                        "name": "监管视角",
                        "run_id": rb,
                        "ok": True,
                        "absent": False,
                        "arguments": [],
                        "beat": "thread",
                    },
                    {
                        "key": "c",
                        "name": "产业视角",
                        "run_id": rc,
                        "ok": True,
                        "absent": False,
                        "arguments": [],
                        "beat": "thread",
                    },
                ],
                "clashes": [
                    {
                        "from_key": "b",
                        "to_key": "a",
                        "point": "能力外溢说回避了问责主体，技术归因不能替代责任分配。",
                    },
                    {
                        "from_key": "c",
                        "to_key": "b",
                        "point": "强问责会抬高合规成本，产业落地承受不起一刀切立法。",
                    },
                ],
                "findings": [],
                "thread_turns": [
                    {"speaker": "a", "reply_to": "", "run_id": ra, "ok": True, "beat": "thread"},
                    {"speaker": "b", "reply_to": "a", "run_id": rb, "ok": True, "beat": "thread"},
                    {"speaker": "c", "reply_to": "b", "run_id": rc, "ok": True, "beat": "thread"},
                ],
            },
        ],
        "closings": [],
        "subtopics": ["先管能力还是先管问责", "分级落地的成本边界"],
        "brief": {
            "crux": "AI 治理的主轴：先管能力还是先管问责",
            "strongest_points": {
                "a": "风险源于能力外溢，治理应内建可观测与熔断。",
                "b": "缺的是问责主体，须以立法明确责任归属。",
                "c": "一刀切立法抬高合规成本，应分级分场景落地。",
            },
            "risk_severities": {},
            "findings": [],
            "gate": "",
            "must_fix": [],
            "consensus_map": [
                {
                    "topic": "先管能力还是先管问责",
                    "consensus": ["分级治理 + 可观测先行"],
                    "divergences": ["问责立法时点与强度"],
                    "crux": "价值：创新速度 vs 风险兜底",
                }
            ],
            "handoffs": [
                {"kind": "value", "text": "创新速度优先 vs 风险兜底优先？"},
                {"kind": "fact", "text": "现有事故里『能力外溢』与『问责缺位』各占多少缺一致数据"},
                {"kind": "question", "text": "谁来认定与维护『高风险场景』清单？"},
            ],
            "decisive": "",
            "leaning": "三方共识：分级治理 + 可观测先行，问责随之立法",
            "confidence": "medium",
            "recommendation": "按能力分级，先强制高风险场景的可观测与熔断，再补问责立法。",
        },
    }
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场多方圆桌并收场。"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="多方圆桌：AI 该如何治理",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus="AI 治理的主轴：先管能力还是先管问责",
            cross_exam_enabled=False,
            opening="圆桌收场前开场：先定治理主轴——能力还是问责。",
            form="roundtable",
        ),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary="",
            agents=debater_agents,
            runs=debater_runs,
        ),
        run_started(ra, "rt_a", parent_run_id=mod),
        run_output_delta(ra, "rt_a", "技术视角：能力外溢是根因，需可观测与熔断。"),
        run_completed(
            ra,
            "rt_a",
            output_summary="技术视角发言完成",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(rb, "rt_b", parent_run_id=mod),
        run_output_delta(rb, "rt_b", "监管视角：问责缺位才是关键，须立法明确。"),
        run_completed(
            rb,
            "rt_b",
            output_summary="监管视角发言完成",
            duration_ms=820,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started(rc, "rt_c", parent_run_id=mod),
        run_output_delta(rc, "rt_c", "产业视角：别忽视落地成本，应分级分场景。"),
        run_completed(
            rc,
            "rt_c",
            output_summary="产业视角发言完成",
            duration_ms=810,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            mod,
            mod,
            output_summary="AI 治理的主轴：先管能力还是先管问责",
            duration_ms=2200,
            role="主持人",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        debate_result(execution_id="exec1", moderator_run_id=mod, payload=debate_payload),
        message_end(FinishReason.END_TURN, input_tokens=3400, output_tokens=600, cost=_COST),
    ]

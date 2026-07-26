"""Conformance vector builders — interactive gate pause/continue scenarios.

See ``vectors/__init__.py`` for the aggregated ``VECTORS`` registry.
"""

from __future__ import annotations

from collections.abc import Callable

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    approval_required,
    approval_resolved,
    checkpoint_required,
    checkpoint_resolved,
    content_delta,
    debate_round_started,
    message_end,
    message_start,
    plan_review_required,
    plan_review_resolved,
    question_posted,
    reasoning_delta,
    run_completed,
    run_output_delta,
    run_plan,
    run_started,
    team_preview_required,
    team_preview_resolved,
    tool_use_end,
    tool_use_start,
)

from ._common import _CONV, _COST, _USAGE
from .debate._builders import (
    _moderator_agents_runs,
    _pro_con_debater_agents,
    _pro_con_debater_runs,
)


def _approval_paused() -> list[SSEEvent]:
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我需要运行代码。"),
        approval_required(
            approval_id="tc1",
            conversation_id=_CONV,
            tool_call_id="tc1",
            tool_name="code_execute",
            arguments={"code": "print(1)"},
        ),
    ]

def _approval_resolved_continue() -> list[SSEEvent]:
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我需要运行代码。"),
        approval_required(
            approval_id="tc1",
            conversation_id=_CONV,
            tool_call_id="tc1",
            tool_name="code_execute",
            arguments={"code": "print(1)"},
        ),
        approval_resolved(approval_id="tc1", tool_call_id="tc1", decision="approve"),
        tool_use_start("tc1", "code_execute", {"code": "print(1)"}),
        tool_use_end("tc1", "code_execute", success=True, output="1\n"),
        content_delta("运行结果是 1。"),
        message_end(FinishReason.END_TURN, input_tokens=900, output_tokens=80, cost=_COST),
    ]

def _plan_review_paused() -> list[SSEEvent]:
    agents = [
        {
            "id": "w1",
            "role": "调研",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "执行",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "出方案", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "落地", "depends_on": ["r1"]},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="分阶段",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_completed(
            "r1",
            "w1",
            output_summary="方案就绪",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        plan_review_required(
            checkpoint_id="cp1",
            conversation_id=_CONV,
            steps=[{"run_id": "r1", "role": "调研", "summary": "方案就绪"}],
            pending=[{"run_id": "r2", "role": "执行"}],
        ),
    ]

def _plan_review_resolved_continue() -> list[SSEEvent]:
    base = _plan_review_paused()
    return [
        *base,
        plan_review_resolved(checkpoint_id="cp1", decision="continue"),
        run_started("r2", "w2"),
        run_completed(
            "r2",
            "w2",
            output_summary="已落地",
            duration_ms=1100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        message_end(FinishReason.END_TURN, input_tokens=3000, output_tokens=400, cost=_COST),
    ]

def _single_agent_checkpoint() -> list[SSEEvent]:
    """单聊·检查点 (ask_user blocking=true)：CEO 想清楚后向用户拍板、暂停回合。检查点在时间线
    **原位**落一个 `checkpoint` 标记（卡片正文另路 fold，按 checkpoint_id 取回），回合停在
    checkpoint_required（无 message_end）→ pendingInteraction=checkpoint、status=paused。
    验「检查点不再压到气泡底部、而是回到它真实发生的时序位」。"""
    return [
        message_start("m1", conversation_id=_CONV),
        reasoning_delta("这个需求有歧义，先问清楚。"),
        content_delta("开始前我确认一下方向："),
        checkpoint_required(
            checkpoint_id="cp1",
            conversation_id=_CONV,
            question="先做 A 还是 B？",
            context="两条路线各有取舍。",
            intent="kickoff",
        ),
    ]

def _single_agent_checkpoint_finalized() -> list[SSEEvent]:
    """单聊·检查点【收口即终止】(②)：ask_user(blocking) 落帧后【不再
    挂在内存 Future】，回合直接以 ``message_end(finish_reason=paused)`` 收口——流到此【终止】（对照
    ``_single_agent_checkpoint`` 的「停在 ``checkpoint_required``、无 ``message_end``」挂起态）。
    关键断言：``status`` 仍 ``paused``、``pendingInteraction`` 仍 checkpoint（同一张 resume 卡），但
    ``finishReason="paused"`` + ``cost`` 落账——客户端据「流以 paused 收尾」渲成单张 resume 卡（统一
    冷路 ``POST .../resume``，根除 live/durable 双态）。验「终止式挂起 == 挂起态的同一恢复面」。"""
    return [
        *_single_agent_checkpoint(),
        message_end(FinishReason.PAUSED, input_tokens=1900, output_tokens=210, cost=_COST),
    ]

def _single_agent_checkpoint_resolved() -> list[SSEEvent]:
    """单聊·检查点【冷路恢复】(② resume)：ask_user(blocking) 落帧暂停后，用户经
    ``POST .../resume`` 拍板续跑——``checkpoint_resolved`` 清掉 pendingInteraction、status 从
    paused 回 running，回合继续产出并正常 ``end_turn`` 收尾。对照 ``_single_agent_checkpoint``
    （停在 ``checkpoint_required`` 的挂起态）验「同一张 resume 卡在续跑后关闭、回合跑到底」。"""
    return [
        *_single_agent_checkpoint(),
        checkpoint_resolved(checkpoint_id="cp1", decision="continue"),
        content_delta("好，按 A 推进。"),
        content_delta(" 已完成初稿。"),
        message_end(FinishReason.END_TURN, input_tokens=2100, output_tokens=260, cost=_COST),
    ]

def _plan_review_finalized() -> list[SSEEvent]:
    """结构化挂起·计划复核【收口即终止】(②)：delegate ``checkpoint_after`` 落帧后回合以
    ``message_end(finish_reason=paused)`` 收口（对照 ``_plan_review_paused`` 的「停在
    ``plan_review_required``、无 ``message_end``」挂起态）。``status`` 仍 ``paused``、
    ``pendingInteraction`` 仍 plan_review、已完成 r1 仍带 checkpoint 徽标，但 ``finishReason="paused"``
    + ``cost`` 落账。delegate 的 plan_review 对偶，证终止式挂起在多 Agent 图上同样退回单张 resume 卡。"""
    return [
        *_plan_review_paused(),
        message_end(FinishReason.PAUSED, input_tokens=3000, output_tokens=400, cost=_COST),
    ]

def _single_agent_non_blocking_ask() -> list[SSEEvent]:
    """单聊·非阻塞发问 (ask_user blocking=false)：CEO 抛出一个已有默认值的问题但**继续干**，不
    挂起、不结算。时间线**原位**落一个 `ask` 标记（卡片正文另路 fold，按 ask_id 取回），回合
    照常 end_turn 收尾。验「非阻塞发问插在它真实发生的正文之间，而非堆到底部」。"""
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我先按常见默认推进。"),
        question_posted(
            ask_id="ask1",
            conversation_id=_CONV,
            question="需要同时导出 PDF 吗？",
            context="默认仅 Markdown。",
        ),
        content_delta(" 已完成初稿。"),
        message_end(FinishReason.END_TURN, input_tokens=1000, output_tokens=200, cost=_COST),
    ]


def _proposal_pick_checkpoint() -> list[SSEEvent]:
    """单聊·方案挑选卡 (ask_user card=proposal_pick)：阻塞挂起，intent=proposal_pick，
    恰好 1 个 choice 单选 + options 2–6。"""
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("有三条可行路线，请挑一条："),
        checkpoint_required(
            checkpoint_id="cp_pick",
            conversation_id=_CONV,
            question="选哪条方案推进？",
            context="三条路线成本与风险不同。",
            questions=[
                {
                    "id": "q0",
                    "prompt": "选哪条方案？",
                    "kind": "choice",
                    "multiple": False,
                    "default": "",
                    "options": [
                        {"label": "方案 A：快速原型", "detail": "一周内可验证"},
                        {"label": "方案 B：稳妥重构", "detail": "两周，债务更少"},
                        {"label": "方案 C：外包试点", "recommended": True},
                    ],
                }
            ],
            intent="proposal_pick",
        ),
        message_end(FinishReason.PAUSED, input_tokens=1800, output_tokens=120, cost=_COST),
    ]


def _ask_user_shape_reject_then_pick() -> list[SSEEvent]:
    """单聊·方案挑选卡先被结构校验拒绝、模型自纠正后改对：ask_user(card=proposal_pick) 误塞
    多题 → 结构校验拒绝（tool_use_start + tool_use_end status=error）→ 自纠正后重发单题单选挂起。

    棘轮：ask_user 是交互原语，由 checkpoint/ask 标记代言（MARKER_STANDIN_TOOLS），其
    tool_use_start/end 都【不落 captain 工具步】——所以这条「可自纠正的结构校验失败」既不
    残留 open 工具行、也不外泄红色工具错误给用户；golden.process 仅有 checkpoint 标记。"""
    return [
        message_start("m1", conversation_id=_CONV),
        # 误用：card=proposal_pick 却塞了 2 个 question — 结构校验拒绝（模型可自纠正）。
        tool_use_start(
            "ask_reject",
            "ask_user",
            {
                "card": "proposal_pick",
                "message": "做官网前先定几件事",
                "questions": [{"prompt": "选整体风格?"}, {"prompt": "选配色?"}],
            },
        ),
        tool_use_end(
            "ask_reject",
            "ask_user",
            success=False,
            output=(
                "card=proposal_pick 要求恰好 1 个 question（kind=choice、multiple=false、"
                "options 2–6 个候选方案）。两条出路：要问多个【不同】问题 → 去掉 card；"
                "同一决策的候选方案 → 合并成 1 个 question 的多个 options。"
            ),
        ),
        # 自纠正后重发单题单选 → 正常挂起（尾部铺垫文案被 checkpoint 吸收）。
        content_delta("有三条可行路线，请挑一条："),
        checkpoint_required(
            checkpoint_id="cp_pick",
            conversation_id=_CONV,
            question="选哪条方案推进？",
            context="三条路线成本与风险不同。",
            questions=[
                {
                    "id": "q0",
                    "prompt": "选哪条方案？",
                    "kind": "choice",
                    "multiple": False,
                    "default": "",
                    "options": [
                        {"label": "方案 A：快速原型", "detail": "一周内可验证"},
                        {"label": "方案 B：稳妥重构", "detail": "两周，债务更少"},
                        {"label": "方案 C：外包试点", "recommended": True},
                    ],
                }
            ],
            intent="proposal_pick",
        ),
        message_end(FinishReason.PAUSED, input_tokens=1900, output_tokens=140, cost=_COST),
    ]


def _risk_ack_checkpoint() -> list[SSEEvent]:
    """单聊·风险确认卡 (ask_user card=risk_ack)：阻塞挂起，intent=risk_ack，
    恰好 1 个 choice 多选 + options 1–10。"""
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("落地前请勾选要一并处理的风险："),
        checkpoint_required(
            checkpoint_id="cp_risk",
            conversation_id=_CONV,
            question="哪些风险要在本轮处理？",
            context="未勾选的项将记入后续 backlog。",
            questions=[
                {
                    "id": "q0",
                    "prompt": "勾选要处理的风险",
                    "kind": "choice",
                    "multiple": True,
                    "default": "",
                    "options": [
                        {
                            "label": "[高] 密钥轮换",
                            "detail": "生产密钥仍是默认值，泄露即全库失守",
                            "recommended": True,
                        },
                        {"label": "[中] 备份校验", "detail": "近 30 天备份未做恢复演练"},
                        {"label": "回滚演练"},
                    ],
                }
            ],
            intent="risk_ack",
        ),
        message_end(FinishReason.PAUSED, input_tokens=1900, output_tokens=140, cost=_COST),
    ]


def _presentation_kickoff_format_options() -> list[SSEEvent]:
    """演讲/PPT 开工卡：强制非空 format_options；resume 以 selected=f0 结构化记账。

    Wire 钉 format_options（pptx / marp / outline）；checkpoint_resolved.selected 含
    ``f0``——与 presentation_format ledger 的 format_id 同形（resume 记账入口）。
    对照普通 kickoff（无 format_options）验「演讲意图必须带交付形态选项」。
    """
    format_opts = [
        {
            "id": "f0",
            "label": "PowerPoint（.pptx）— 真幻灯片文件；有 code_execute 时推荐",
        },
        {
            "id": "f1",
            "label": "Marp Markdown 幻灯片 — 无代码执行时推荐",
        },
        {
            "id": "f2",
            "label": "仅讲稿大纲 — 只要讲稿、不要幻灯片文件",
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("开始前确认课件交付形态："),
        checkpoint_required(
            checkpoint_id="cp_fmt",
            conversation_id=_CONV,
            question="这份课件用哪种交付形态？",
            context="演讲 / PPT 意图：必须选定形态后再开做。",
            format_options=format_opts,
            intent="kickoff",
        ),
        checkpoint_resolved(
            checkpoint_id="cp_fmt",
            decision="continue",
            note="选 PowerPoint",
            selected=["f0"],
        ),
        content_delta("好，按 PowerPoint（.pptx）推进。"),
        message_end(FinishReason.END_TURN, input_tokens=1800, output_tokens=140, cost=_COST),
    ]


def _organize_plan_checkpoint() -> list[SSEEvent]:
    """单聊·整理方案卡 (ask_user card=organize_plan)：阻塞挂起，intent=organize_plan，
    恰好 1 个 choice 多选 + options 1–50（原路径→新路径）。"""
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("请确认整理方案（取消勾选即剔除）："),
        checkpoint_required(
            checkpoint_id="cp_org",
            conversation_id=_CONV,
            question="按下列方案整理桌面？",
            context="确认后按方案批量执行，不再二次弹审批。",
            questions=[
                {
                    "id": "q0",
                    "prompt": "整理项",
                    "kind": "choice",
                    "multiple": True,
                    "default": "",
                    "options": [
                        {
                            "label": "发票.pdf → 财务/发票.pdf",
                            "op": "move",
                            "source": "external/desk/发票.pdf",
                            "destination": "external/desk/财务/发票.pdf",
                        },
                        {
                            "label": "新建 财务/",
                            "op": "mkdir",
                            "path": "external/desk/财务",
                        },
                    ],
                }
            ],
            intent="organize_plan",
        ),
        message_end(FinishReason.PAUSED, input_tokens=1900, output_tokens=140, cost=_COST),
    ]


def _team_preview_finalized() -> list[SSEEvent]:
    """团队预审薄预览【收口即终止】：多 Agent 首委派在 run_plan 后、首波前挂起，以
    ``message_end(finish_reason=paused)`` 收口。``pendingInteraction`` = team_preview，
    时间线落 ``team_preview`` 标记；与 plan_review 波间闸门分离。"""
    agents = [
        {
            "id": "w1",
            "role": "调研",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研方案", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "写初稿", "depends_on": ["r1"]},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "调研"}, {"role": "撰写"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="构建 X",
            agents=agents,
            runs=plan_runs,
        ),
        team_preview_required(
            checkpoint_id="tp1",
            conversation_id=_CONV,
            workers=[
                {
                    "run_id": "r1",
                    "role": "调研",
                    "task": "调研方案",
                    "depends_on": [],
                    "debate": False,
                },
                {
                    "run_id": "r2",
                    "role": "撰写",
                    "task": "写初稿",
                    "depends_on": ["r1"],
                    "debate": False,
                },
            ],
            tools=["code_execute", "file_write", "test_run"],
            primitive="delegate",
        ),
        message_end(FinishReason.PAUSED, input_tokens=1200, output_tokens=80, cost=_COST),
    ]


def _debate_team_preview_finalized() -> list[SSEEvent]:
    """辩论开工卡：顶层 debate 在主持人循环启动前挂起收口。"""
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场辩论。"),
        tool_use_start(
            "db1",
            "debate",
            {
                "motion": "该不该上四天工作制？",
                "form": "debate",
                "sides": [
                    {"key": "pro", "name": "正方", "stance": "应推广"},
                    {"key": "con", "name": "反方", "stance": "暂缓"},
                ],
                "thorough": True,
            },
        ),
        team_preview_required(
            checkpoint_id="tp-debate",
            conversation_id=_CONV,
            workers=[],
            tools=[],
            primitive="debate",
            motion="该不该上四天工作制？",
            form="debate",
            sides=[
                {"key": "pro", "name": "正方", "stance": "应推广"},
                {"key": "con", "name": "反方", "stance": "暂缓"},
            ],
            max_rounds=5,
            thorough=True,
        ),
        message_end(FinishReason.PAUSED, input_tokens=800, output_tokens=40, cost=_COST),
    ]


def _debate_team_preview_research_first() -> list[SSEEvent]:
    """退役棘轮：开工卡不再 offer research_first；本向量保留 resolve 旧决议路径。

    挂起 payload **无** offer_research_first；若用户仍经旧客户端提交 research_first，
    回灌文案与不开赛行为不变。
    """
    from agentcore.runtime.kickoff.research_first import research_first_tool_result

    motion = "该不该上四天工作制？"
    refeed = research_first_tool_result(motion=motion, user_message="")
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场辩论。"),
        tool_use_start(
            "db1",
            "debate",
            {
                "motion": motion,
                "form": "debate",
                "sides": [
                    {"key": "pro", "name": "正方", "stance": "应推广"},
                    {"key": "con", "name": "反方", "stance": "暂缓"},
                ],
                "thorough": True,
            },
        ),
        team_preview_required(
            checkpoint_id="tp-debate-rf",
            conversation_id=_CONV,
            workers=[],
            tools=[],
            primitive="debate",
            motion=motion,
            form="debate",
            sides=[
                {"key": "pro", "name": "正方", "stance": "应推广"},
                {"key": "con", "name": "反方", "stance": "暂缓"},
            ],
            max_rounds=5,
            thorough=True,
        ),
        team_preview_resolved(
            checkpoint_id="tp-debate-rf", decision="research_first"
        ),
        tool_use_end("db1", "debate", success=True, output=refeed),
        content_delta("好的，我先挂多视角调研。"),
        message_end(FinishReason.END_TURN, input_tokens=900, output_tokens=60, cost=_COST),
    ]


def _debate_team_preview_research_first_recommended() -> list[SSEEvent]:
    """退役棘轮：不再点亮 research_first_recommended；普通开工卡挂起。"""
    motion = "LV 案模拟法庭：一审判决是否过重？"
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来组织一场辩论。"),
        tool_use_start(
            "db1",
            "debate",
            {
                "motion": motion,
                "form": "debate",
                "sides": [
                    {"key": "plaintiff", "name": "原告", "stance": "判决过重"},
                    {"key": "defendant", "name": "被告", "stance": "判决适当"},
                ],
                "thorough": True,
            },
        ),
        team_preview_required(
            checkpoint_id="tp-debate-rf-rec",
            conversation_id=_CONV,
            workers=[],
            tools=[],
            primitive="debate",
            motion=motion,
            form="debate",
            sides=[
                {"key": "plaintiff", "name": "原告", "stance": "判决过重"},
                {"key": "defendant", "name": "被告", "stance": "判决适当"},
            ],
            max_rounds=5,
            thorough=True,
        ),
        message_end(FinishReason.PAUSED, input_tokens=800, output_tokens=40, cost=_COST),
    ]


def _debate_team_preview_resolved_continue() -> list[SSEEvent]:
    """辩论开工卡放行后主持人循环已开赛（team_preview resolved + 协作图有 runs）。

    对照 ``debate_team_preview_finalized``（pending）与 ``team_preview_resolved_continue``
    （delegate resolved+started）：本向量停在首轮正反陈述进行中，不收场——前端可离线预览
    「已开赛」协作图态。
    """
    cap, mod = "captain1", "debate_mod1"
    pro_run, con_run = f"{mod}_r1_pro", f"{mod}_r1_con"
    motion = "该不该上四天工作制？"
    mod_agents, mod_runs = _moderator_agents_runs(mod, cap, f"主持正反辩论：{motion}")
    debater_agents = _pro_con_debater_agents()
    debater_runs = _pro_con_debater_runs(
        mod,
        pro_run,
        con_run,
        pro_task="论证应推广四天工作制",
        con_task="论证暂缓推行四天工作制",
    )
    return [
        *_debate_team_preview_finalized()[:-1],
        team_preview_resolved(checkpoint_id="tp-debate", decision="continue"),
        run_plan(
            execution_id="exec1",
            plan_type="debate",
            task_summary=f"正反辩论：{motion}",
            agents=mod_agents,
            runs=mod_runs,
        ),
        run_started(mod, mod, parent_run_id=cap),
        debate_round_started(
            execution_id="exec1",
            moderator_run_id=mod,
            round_no=1,
            focus="生产力与员工福祉的取舍",
            cross_exam_enabled=True,
            opening="这场要定的是该不该上四天工作制，先从产出与休息的权衡切入。",
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
            "正方：四天制可降低倦怠、提升专注产出，试点企业已有可量化对照。",
        ),
        run_started(con_run, "d_con", parent_run_id=mod),
        run_output_delta(
            con_run,
            "d_con",
            "反方：服务业与协作密集岗位难以压缩工时，仓促推广会抬高成本与排班摩擦。",
        ),
        # 无 message_end：回合仍在辩论中（status=running），协作图可见主持人+正反双方。
    ]


def _team_preview_resolved_continue() -> list[SSEEvent]:
    """团队预审放行后首波开跑到 end_turn。"""
    return [
        *_team_preview_finalized()[:-1],
        team_preview_resolved(checkpoint_id="tp1", decision="continue"),
        run_started("r1", "w1"),
        run_completed(
            "r1",
            "w1",
            output_summary="调研完成",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started("r2", "w2"),
        run_completed(
            "r2",
            "w2",
            output_summary="初稿完成",
            duration_ms=1100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队完成"),
        content_delta("团队已交付。"),
        message_end(FinishReason.END_TURN, input_tokens=3000, output_tokens=400, cost=_COST),
    ]


def _decision_then_kill() -> list[SSEEvent]:
    """决策后杀进程：settlement 已落、无终态 → fold 无 pending gate，status=running。

    验收（回合恢复状态机收口）：重启投影不得出现待授权卡；对应 UI 救火「继续」（已决策·执行中断）。
    """
    return [
        *_team_preview_finalized()[:-1],
        team_preview_resolved(checkpoint_id="tp1", decision="continue"),
        run_started("r1", "w1"),
        # 杀进程：无 message_end / 无新 gate
    ]


def _decision_then_second_gate_then_kill() -> list[SSEEvent]:
    """决策后执行中二次挂起再杀：只投影新决策卡，旧 settlement 不产生中断态双显。"""
    return [
        *_team_preview_finalized()[:-1],
        team_preview_resolved(checkpoint_id="tp1", decision="continue"),
        run_started("r1", "w1"),
        run_completed(
            "r1",
            "w1",
            output_summary="调研完成",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        checkpoint_required(
            checkpoint_id="cp-second",
            conversation_id=_CONV,
            question="调研结论你认吗？",
            context="二次挂起",
            intent="decision",
        ),
        message_end(FinishReason.PAUSED, input_tokens=2200, output_tokens=180, cost=_COST),
    ]


VECTORS: dict[str, tuple[str, Callable[[], list[SSEEvent]]]] = {
    "approval_paused": ("审批：approval_required 暂停（无 message_end）", _approval_paused),
    "approval_resolved_continue": ("审批：通过后继续到 end_turn", _approval_resolved_continue),
    "plan_review_paused": ("结构化挂起：plan_review_required 暂停", _plan_review_paused),
    "plan_review_resolved_continue": ("结构化挂起：放行后跑完下游", _plan_review_resolved_continue),
    "plan_review_finalized": ("结构化挂起：计划复核收口即终止（②，plan_review_required→message_end(paused)，单一冷路 resume）", _plan_review_finalized),
    "team_preview_finalized": ("团队预审：首波前挂起收口（finish_reason=paused）", _team_preview_finalized),
    "team_preview_resolved_continue": ("团队预审：开做后跑完首波", _team_preview_resolved_continue),
    "decision_then_kill": (
        "恢复收口：决策后杀进程 → fold 无待授权、status=running（已决策·执行中断 / 救火继续）",
        _decision_then_kill,
    ),
    "decision_then_second_gate_then_kill": (
        "恢复收口：决策后二次挂起再杀 → 仅新决策卡 pending，无中断态双显",
        _decision_then_second_gate_then_kill,
    ),
    "debate_team_preview_finalized": ("辩论开工卡：主持人循环前挂起收口", _debate_team_preview_finalized),
    "debate_team_preview_research_first": (
        "辩论开工卡：offer_research_first → resolve research_first（不开赛·回灌文案）",
        _debate_team_preview_research_first,
    ),
    "debate_team_preview_research_first_recommended": (
        "辩论开工卡：research_first_recommended 键位反转（挂起·第三键升主键）",
        _debate_team_preview_research_first_recommended,
    ),
    "debate_team_preview_resolved_continue": (
        "辩论开工卡：开赛后主持人+正反已 start（协作图可见）",
        _debate_team_preview_resolved_continue,
    ),
    "single_agent_checkpoint": ("单聊：检查点 ask_user(blocking) 在时间线原位落 checkpoint 标记 + 暂停", _single_agent_checkpoint),
    "single_agent_checkpoint_finalized": ("单聊：检查点收口即终止（②，checkpoint_required→message_end(paused)，单一冷路 resume）", _single_agent_checkpoint_finalized),
    "single_agent_checkpoint_resolved": ("单聊：检查点 ask_user(blocking) 经 resume 续跑（checkpoint_resolved 清挂起→跑到 end_turn）", _single_agent_checkpoint_resolved),
    "single_agent_non_blocking_ask": ("单聊：非阻塞发问 question_posted 在时间线原位落 ask 标记、回合照常收尾", _single_agent_non_blocking_ask),
    "proposal_pick_checkpoint": ("单聊：方案挑选卡 ask_user(card=proposal_pick) 挂起（intent=proposal_pick）", _proposal_pick_checkpoint),
    "ask_user_shape_reject_then_pick": (
        "单聊：方案挑选卡误塞多题被结构校验拒绝→自纠正改对（校验失败不落工具步、不外泄红错）",
        _ask_user_shape_reject_then_pick,
    ),
    "risk_ack_checkpoint": ("单聊：风险确认卡 ask_user(card=risk_ack) 挂起（intent=risk_ack）", _risk_ack_checkpoint),
    "organize_plan_checkpoint": ("单聊：整理方案卡 ask_user(card=organize_plan) 挂起（intent=organize_plan）", _organize_plan_checkpoint),
    "presentation_kickoff_format_options": (
        "演讲/PPT 开工卡：checkpoint_required 强制非空 format_options；"
        "resume selected=f0 结构化记账（presentation_format ledger 同形）",
        _presentation_kickoff_format_options,
    ),
}

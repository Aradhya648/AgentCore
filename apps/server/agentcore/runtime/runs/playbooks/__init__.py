"""拆·playbook 固化 (docs/03-AI核心/编排器与CEO主Agent.md §playbook): a tiny registry of
high-frequency, high-variance team SHAPES promoted from prose guidance to instantiable
deterministic DAG skeletons — the CEO names one + fills a few slots instead of
hand-crafting the ``tasks`` array every time
(像 `debate` 的确定性骨架, [辩论编排设计](docs/03-AI核心/辩论编排设计.md)).

Each playbook is a PURE ``slots -> (tasks, errors)`` builder whose output is exactly the
``tasks`` dict-list :func:`agentcore.runtime.runs.builder.build_run_plan` already consumes, so an
instantiated playbook flows through the SAME pipeline (build_run_plan → drive → executor →
ceo_format) as a hand-written delegation — 纯加法、不加新子系统、零行为变化（不传 playbook 即如常）.

Deliberately SMALL. A playbook 固化 is for the few recurring, worth-codifying shapes,
NOT a general template engine (守 [dev-process](.cursor/rules/dev-process.mdc) 防僵化绊线): the
moment a "playbook" needs branching / conditionals / per-call structural choices it is no longer a
固定形状 and should stay a hand-written ``tasks`` array.
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.playbooks._common import (
    CONVERSATION_ID_MECH_KEY,
    MAX_PLAYBOOK_FANOUT,
    USER_MESSAGE_MECH_KEY,
    Playbook,
    PlaybookBuilder,
    clean_str,
)
from agentcore.runtime.runs.playbooks.build_site import (
    build_toolshed,
    build_website,
    build_website_verify,
)
from agentcore.runtime.runs.playbooks.build_soft import (
    build_app,
    build_feature,
    repair_code,
)
from agentcore.runtime.runs.playbooks.decide import compare_options
from agentcore.runtime.runs.playbooks.research import (
    multi_lens_research,
    parallel_brief,
    research_report,
)

PLAYBOOKS: dict[str, Playbook] = {
    "parallel_brief": Playbook(
        name="parallel_brief",
        summary=(
            "【对齐推进·默认多角协作】N 路并行摸底→方向笔记落盘→交回 CEO 对话综述；"
            "无提纲/撰稿/审校（一起弄懂/多路摸清；成文请升 research_report）"
        ),
        slots=(
            "topic(必填,主题) / angles(必填,≥2 个可并行摸底方向;"
            "超过扇出上限时末尾自动折叠到最后一节点并标注、不丢弃)"
        ),
        build=parallel_brief,
    ),
    "research_report": Playbook(
        name="research_report",
        summary=(
            "【成文专线】用户明示要报告/论文/落盘成文时："
            "调研→提纲→写作→审校（N 路并行调研，汇拢成纲再成文；"
            "成篇验收钉死单一主文件 `.md`；要 PDF/可分享则 md→md_to_pdf→handoff，"
            "禁 HTML 顶替/禁 reportlab 主路径）。一起弄懂/多路摸清请用 parallel_brief"
        ),
        slots=(
            "topic(必填,主题) / angles(可选,调研子方向数组,各派一名调研员;"
            "超过扇出上限时末尾自动折叠到最后一节点并标注、不丢弃) / "
            "checkpoint(可选,成纲后写作前暂停过目,默认 true) / audience(可选,读者) / "
            "deliverable(可选,产出形态) / "
            "output_path(可选,成篇主文件路径,默认 AgentCore/文档/research/报告.md；验收只认此路径)"
        ),
        build=research_report,
    ),
    "build_feature": Playbook(
        name="build_feature",
        summary="后端接口→（前端页面 ‖ 测试）并行的功能交付（接口契约经便签墙对齐）",
        slots=(
            "feature(必填,要实现的功能) / stack(可选,技术栈) / "
            "include(可选,['ui','test'] 子集,默认两者都要)"
        ),
        build=build_feature,
    ),
    "repair_code": Playbook(
        name="repair_code",
        summary=(
            "【无先验调查批】诊断(短)→修补→验证的单症状修码（runtime 错 / 缺 export；"
            "短轮次+工具收窄；禁触顶后换马甲；批次 code_verified；"
            "已有调查批确认修→手写+continue_from，勿套本 playbook）"
        ),
        slots=(
            "problem(必填,错误症状/缺 export 等) / "
            "verify(必填,怎么算修好:具体命令或等价说明;"
            "亦接受 verify_command/acceptance) / "
            "target(可选,优先文件路径) / artifacts(可选,落盘路径数组)"
        ),
        build=repair_code,
    ),
    "build_app": Playbook(
        name="build_app",
        summary=(
            "绿场软件/SPA：scaffold→shared→N×module→integrate→smoke"
            "（五波串起不可减；禁单 worker 包整站；import 图须闭合）"
        ),
        slots=(
            "app(必填,要搭建的应用/SPA简述——"
            "例:app=\"面向运营的 Vue3 数据看板\") / "
            "modules(可选,功能模块名数组,各派一名实现;"
            "默认总览页·列表页) / "
            "stack(可选,技术栈,默认 Vue3+Vite+TS) / "
            "root(可选,项目目录名,默认从 app 简述派生)"
        ),
        build=build_app,
    ),
    "build_website": Playbook(
        name="build_website",
        summary=(
            "文案→前端(DESIGN.md+整页HTML/CSS/JS+轻量CONTRACT)→独立 QA"
            "（三串串行；sections 仅覆盖清单不扇出；营销 pack + visual critic）"
        ),
        slots=(
            "site(必填,要建的站点/落地页简述——delegate 时填入 playbook 的 site 参数, "
            "例:site=\"面向企业客户的智能数据分析 SaaS 中文营销官网\") / "
            "sections(可选,页面分区覆盖清单,不扇出节点;"
            "默认首屏英雄区·卖点能力区·行动号召区) / "
            "stack(可选,技术栈) / audience(可选,访客/读者)"
        ),
        build=build_website,
    ),
    "build_toolshed": Playbook(
        name="build_toolshed",
        summary=(
            "文案→前端(DESIGN.md+整页HTML/CSS/JS+轻量CONTRACT)→独立 QA"
            "（三串串行；sections 仅覆盖清单不扇出；强制 pack=tool_dense；"
            "anti-slop domain=tool；禁营销 hero/pricing 皮）"
        ),
        slots=(
            "site(必填,要建的控制台/工具台简述——"
            "例:site=\"面向运营的订单管理后台 dense 控制台\") / "
            "sections(可选,页面分区覆盖清单,不扇出节点;"
            "默认应用外壳·侧栏导航·数据表格) / "
            "stack(可选,技术栈) / audience(可选,使用者)"
        ),
        build=build_toolshed,
    ),
    "build_website_verify": Playbook(
        name="build_website_verify",
        summary=(
            "第二段整页/视觉验收（qa_deferred_budget 续派）：只跑 QA，要求已有 site/；"
            "勿重建文案/整站"
        ),
        slots=(
            "site(必填,与建站时 site 简述一致或写工作区站点名——"
            "例:site=\"面向企业客户的智能数据分析 SaaS 中文营销官网\")"
        ),
        build=build_website_verify,
    ),
    "compare_options": Playbook(
        name="compare_options",
        summary="N 路并行评估各选项→汇总对比推荐的决策支持",
        slots=(
            "question(必填,要决策的问题) / options(必填,>=2 且≤扇出上限个待比较选项;"
            "超上限显式拒绝、不折叠不截断) / "
            "criteria(可选,评估维度数组)"
        ),
        build=compare_options,
    ),
    "multi_lens_research": Playbook(
        name="multi_lens_research",
        summary=(
            "异质透镜并行调研→汇总交叉验证（可产 motion_card 建议开辩；"
            "调研报告落盘 AgentCore/文档/research/；默认法律/品牌商业/舆情公关/文化社会）"
        ),
        slots=(
            "topic(必填,主题/事件) / lenses(可选,透镜名数组；"
            "超过扇出上限时末尾自动折叠到最后一节点并标注、不丢弃；"
            "默认法律·品牌商业·舆情公关·文化社会)"
        ),
        build=multi_lens_research,
    ),
}


def available_playbooks() -> str:
    """One-line ``name（summary）`` listing for schema / skill / error messages — single source so
    the available set never drifts between the registry and what the CEO is told."""
    return "；".join(f"{p.name}（{p.summary}）" for p in PLAYBOOKS.values())


def collect_playbook_notes(tasks: list[dict[str, Any]]) -> list[str]:
    """Deduped ``playbook_note`` strings from expanded tasks (CEO-facing fold/merge notices)."""
    notes: list[str] = []
    seen: set[str] = set()
    for t in tasks:
        raw = t.get("playbook_note")
        if not isinstance(raw, str):
            continue
        note = raw.strip()
        if note and note not in seen:
            seen.add(note)
            notes.append(note)
    return notes


def expand_playbook(
    name: str,
    args: dict[str, Any] | None,
    *,
    user_message: str = "",
    conversation_id: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Expand a named playbook + slot args into a ``tasks`` dict-list for ``build_run_plan``.

    ``user_message`` is the turn's raw user line (from DelegateTool), injected as a
    mechanism-only key for playbooks that need proposition fidelity (e.g. multi_lens
    synthesizer). Not a CEO-facing slot.

    ``conversation_id`` is mechanism-only for ``build_website`` style-ledger injection.

    Returns ``(tasks, errors)``; a non-empty ``errors`` means the instantiation is rejected (unknown
    name, bad args type, or a missing required slot) and the caller must NOT run it — mirroring
    ``build_run_plan``'s reject-on-error contract so the delegate entry handles both the same
    way."""
    pb = PLAYBOOKS.get(name)
    if pb is None:
        return [], [f"未知 playbook『{name}』；可用：{available_playbooks()}"]
    if args is not None and not isinstance(args, dict):
        return [], [f"playbook_args 必须是对象；{pb.name} 槽位：{pb.slots}"]
    slot_args: dict[str, Any] = dict(args or {})
    um = clean_str(user_message)
    if um:
        slot_args[USER_MESSAGE_MECH_KEY] = um
    cid = clean_str(conversation_id)
    if cid:
        slot_args[CONVERSATION_ID_MECH_KEY] = cid
    return pb.build(slot_args)


__all__ = [
    "MAX_PLAYBOOK_FANOUT",
    "PLAYBOOKS",
    "Playbook",
    "PlaybookBuilder",
    "available_playbooks",
    "collect_playbook_notes",
    "expand_playbook",
]

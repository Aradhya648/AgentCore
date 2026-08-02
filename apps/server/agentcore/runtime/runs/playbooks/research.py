"""调研类 playbook：parallel_brief / research_report / multi_lens_research."""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.playbooks._common import (
    DIRECTED_SEARCH_TASK_HINT,
    RESEARCHER_ACADEMIC_SEARCH_DISCIPLINE,
    RESEARCHER_NOTE_GUIDANCE,
    RESEARCHER_SEARCH_DISCIPLINE,
    USER_MESSAGE_MECH_KEY,
    clean_str,
    clean_str_list,
    fold_fanout_slots,
)
from agentcore.workspace.stage_dirs import RESEARCH_DIR

_DEFAULT_MULTI_LENSES = ("法律", "品牌商业", "舆情公关", "文化社会")

# 幕 1 案卷目录：各透镜报告 + 汇总与命题卡（多幕共享；辩论阶段将读这些文件）。
_MULTI_LENS_RESEARCH_DIR = RESEARCH_DIR
_SYNTHESIZER_ARTIFACT = f"{_MULTI_LENS_RESEARCH_DIR}/汇总与命题卡.md"

_RESEARCH_REPORT_OUTLINE_ARTIFACT = f"{RESEARCH_DIR}/提纲.md"
_RESEARCH_REPORT_DEFAULT_ANGLE_ARTIFACT = f"{RESEARCH_DIR}/调研报告.md"

_SYNTHESIZER_MOTION_CARD_GUIDANCE = (
    "交叉验证时标清共识 / 冲突 / 分歧。"
    "若存在【真对立轴】（价值对立或主张相互否证、继续取证消解不了）——"
    "收尾调用 handoff【必须】填写结构化参数 `motion_card` 对象（主管呈报与开辩芯片只认此字段）："
    "motion；sides≥2（每方 key/name/stance，stance 薄立场一句话立场倾向）；"
    "fact_pointers（可 []）；rationale（论证为何须对抗而非继续取证）；form 默认 debate。"
    "存在真对立轴则必须产卡；【禁止】用交付正文 markdown 表、或 key_points 散文写"
    "『命题卡 / Motion=…』代替该对象；也勿写 Followups 芯片文案（系统据卡自动注入）。"
    "见分歧或仅事实缺口、无真对立轴【不要】产卡。"
    "【命题保真】motion 必须锚定用户原始问题的【对象】与【形态】："
    "对象=用户点名的主体 / 案由 / 标的；形态=用户点名的对抗形式。"
    "用户点名【模拟法庭 / 庭审 / 对簿公堂】等=原被告对抗【本案】时，"
    "motion 应是本案争议（如一审认定应否维持 / 是否构成侵权），"
    "制度 / 价值 / 政策分歧写入双方 stance 与 rationale 作论据，"
    "【禁止】把命题抬成制度层政策辩、替换命题对象。"
)


def _research_angle_artifact(label: str) -> str:
    """Workspace-relative path for one research_report angle dossier (angle in filename)."""
    from agentcore.workspace._paths import truncate_filename_utf8

    return f"{RESEARCH_DIR}/{truncate_filename_utf8(f'{label}调研报告.md')}"


def _brief_angle_artifact(label: str) -> str:
    """Workspace-relative path for one parallel_brief direction note (angle in filename)."""
    from agentcore.workspace._paths import truncate_filename_utf8

    return f"{RESEARCH_DIR}/{truncate_filename_utf8(f'{label}方向笔记.md')}"


def _lens_report_artifact(lens: str) -> str:
    """Workspace-relative Chinese-readable path for one lens report."""
    from agentcore.workspace._paths import truncate_filename_utf8

    return f"{_MULTI_LENS_RESEARCH_DIR}/{truncate_filename_utf8(f'{lens}透镜报告.md')}"


def _lens_report_artifact_for_parts(parts: list[str]) -> str:
    """Artifact path for a (possibly folded) lens slot — joined names when merged."""
    return _lens_report_artifact(" + ".join(parts))


def _lens_retrieval_division(lens: str, *, is_base_owner: bool) -> str:
    """Static retrieval-division pedagogy for one parallel lens task (no runtime deps).

    Lenses run in parallel and must not assume peer reports exist yet. Division is
    task-text only（职责分工）；检索额度走统一默认，playbook **不**再显式写入
    base/gap 两档 ``retrieval_budget``。

    Folded overflow always lands in the *last* slot (see ``fold_fanout_slots``), so
    ``is_base_owner`` remains index-0 only — first slot stays a single primary lens
    owning the shared factual base; merged last-slot workers stay gap lenses.
    """
    shared = (
        "【检索分工】多路并行、互不等待彼此产物——分工写在任务书里，勿假定可先读其它透镜报告；"
        f"本路报告落盘 `{_MULTI_LENS_RESEARCH_DIR}/` 供汇总与后续幕消费。"
    )
    if is_base_owner:
        return (
            f"{shared}"
            f"【本路·{lens}·公共基础事实负责人】时间线 / 双方主体 / 事件概况等公共底料由本路查全"
            "并写入报告；同时深挖本透镜独有角度与证据。其余透镜只做底料简要确认——"
            "勿指望他们补全公共底料。用尽检索预算后基于已有证据交付。"
        )
    return (
        f"{shared}"
        f"【本路·{lens}·独有缺口】公共基础事实（时间线 / 主体 / 事件概况）以简要确认为限，"
        "勿重复深挖全案底料；检索预算集中在本透镜独有角度、主张、证据与来源缺口——"
        "禁止把预算耗在重复搜公共底料上。"
    )


def _user_request_anchor_block(user_message: str) -> str:
    """Mechanism block: full user line for synthesizer fidelity (empty → omit)."""
    um = clean_str(user_message)
    if not um:
        return ""
    return (
        f"【用户原话·全文·机制注入】「{um}」——"
        "产卡时以这段原话为命题保真锚（不依赖上方 topic 摘要）；"
        "topic 仅为调研主题标签，不得覆盖原话中的对象与形态约束。"
    )


def parallel_brief(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """A 档·对齐推进：N 路并行摸底 → 方向笔记落盘；无提纲/撰稿/审校（交回 CEO 对话综述）.

    与 ``research_report``（B 成文专线）划界：本形状是调研默认——一起弄懂 / 多路摸清；
    仅当用户明示要报告/论文/落盘成文时才升 ``research_report``。angles 宜少扇出（常 2）。
    """
    topic = clean_str(args.get("topic"))
    if not topic:
        return [], ["parallel_brief 需要 slot『topic』（要摸底对齐的主题）"]
    angles_raw = clean_str_list(args.get("angles"), cap=None)
    if len(angles_raw) < 2:
        return [], [
            "parallel_brief 需要 slot『angles』且 ≥2 个可并行方向"
            "（单方向请手写 1 人 task，或明示成文走 research_report）"
        ]
    angle_slots, angle_fold_note = fold_fanout_slots(angles_raw, label="摸底方向")
    fold_hint = f" {angle_fold_note}" if angle_fold_note else ""

    tasks: list[dict[str, Any]] = []
    for i, parts in enumerate(angle_slots):
        merged = len(parts) > 1
        label = " + ".join(parts)
        artifact = _brief_angle_artifact(label)
        scope = (
            f"专门摸底以下合并方向：{'、'.join(f'【{p}】' for p in parts)}。"
            f"本节点职责涵盖上述全部 {len(parts)} 个方向；须全部覆盖，勿只做第一项。"
            if merged
            else f"专门摸底这一个方向：{parts[0]}。"
        )
        task_body: dict[str, Any] = {
            "id": f"brief_{i}",
            "role": "方向专员",
            "task": (
                f"围绕主题【{topic}】，{scope}"
                "给出该方向的关键事实 / 现状 / 证据与开放问题；关键数字 / 关键结论旁须就地标"
                "台账 id（#rN，与工具「[已登记来源]」一致）或显式待核实语，"
                "勿裸写无出处主张；附来源（文件:行 或 链接）。"
                "对关键法条、司法解释、判例等权威出处，须用 read_url 核对原文后再引用，"
                "勿仅凭搜索摘要断言条文或裁判要旨。"
                "聚焦本方向、回报精炼结论供 CEO 与用户对齐，不要写成终稿章节。"
                f"完整要点须用 file_write 落盘到 `{artifact}`"
                "（内容=本方向完整要点 + 来源，不是 handoff 摘要的复制）；"
                "handoff 结构化简报照旧，落盘是叠加、不得替代 handoff。"
                f"{RESEARCHER_SEARCH_DISCIPLINE}"
                f"{RESEARCHER_NOTE_GUIDANCE}"
                f"{fold_hint}"
            ),
            "deliverable": {
                "form": "files",
                "name": f"【{label}】方向笔记 + 来源（已落盘 {artifact}）",
                "artifacts": [artifact],
                "citation_mode": "two_phase",
            },
        }
        if angle_fold_note and merged:
            task_body["playbook_note"] = angle_fold_note
        tasks.append(task_body)
    return tasks, []


def research_report(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """B 成文专线：N×并行调研 → 提纲（默认 checkpoint）→ 写作 → 学术审校.

    仅当用户明示要报告/论文/落盘成文时使用；一起弄懂/多路摸清/仅提论文开源当资料
    默认 ``parallel_brief``，勿一上来三路成文。

    中间环（各路调研 + 提纲）与终稿同走案卷契约：``form=files`` + 钉死
    ``AgentCore/文档/research/`` 下路径（角度名入文件名，对齐 MLR ``{透镜}透镜报告.md``；
    提纲钉 ``提纲.md``）。成篇验收钉死单一主文件（``output_path`` / 默认 ``报告.md``）；
    主交付 `.md`；用户要 PDF/可分享时 brief 钉 ``md → md_to_pdf → handoff``（禁 HTML 顶替、
    禁 reportlab 主路径）。若 CEO 手写并行拆章，须另加 merge 步并把各章 brief 写死同一路径——见
    ``PAPER_PARALLEL_MERGE_DISCIPLINE``。
    """
    from agentcore.runtime.runs.research_quality import (
        MD_PDF_EXPORT_DISCIPLINE,
        PAPER_PARALLEL_MERGE_DISCIPLINE,
        research_report_main_artifact,
    )

    topic = clean_str(args.get("topic"))
    if not topic:
        return [], ["research_report 需要 slot『topic』（要调研并成文的主题）"]
    angles_raw = clean_str_list(args.get("angles"), cap=None)
    angle_slots, angle_fold_note = fold_fanout_slots(angles_raw, label="调研子方向")
    checkpoint = bool(args.get("checkpoint", True))
    audience = clean_str(args.get("audience"))
    deliverable = clean_str(args.get("deliverable")) or f"一篇关于【{topic}】的完整报告"
    main_path = research_report_main_artifact(clean_str(args.get("output_path")) or None)
    fold_hint = f" {angle_fold_note}" if angle_fold_note else ""
    outline_path = _RESEARCH_REPORT_OUTLINE_ARTIFACT

    tasks: list[dict[str, Any]] = []
    if angle_slots:
        research_ids = [f"research_{i}" for i in range(len(angle_slots))]
        for rid, parts in zip(research_ids, angle_slots, strict=True):
            merged = len(parts) > 1
            label = " + ".join(parts)
            artifact = _research_angle_artifact(label)
            scope = (
                f"专门调研以下合并子方向：{'、'.join(f'【{p}】' for p in parts)}。"
                f"本节点职责涵盖上述全部 {len(parts)} 个方向；须全部覆盖，勿只做第一项。"
                if merged
                else f"专门调研这一个子方向：{parts[0]}。"
            )
            task_body: dict[str, Any] = {
                "id": rid,
                "role": "调研员",
                # 成文综述：结构化学术检索挡位（偏论文站；junk → evidence_gap）。
                "search_policy": "academic_literature",
                "task": (
                    f"围绕主题【{topic}】，{scope}"
                    "给出该子方向的关键事实 / 现状 / 证据；关键数字 / 关键结论旁须就地标"
                    "台账 id（#rN，与工具「[已登记来源]」一致）或显式待核实语，"
                    "勿裸写无出处主张；"
                    "附来源（文件:行 或 链接）。"
                    "对关键法条、司法解释、判例等权威出处，须用 read_url 核对原文后再引用，"
                    "勿仅凭搜索摘要断言条文或裁判要旨。"
                    "聚焦本子方向、回报精炼结论而非整段原文，别铺开到其它角度。"
                    f"完整调研要点须用 file_write 落盘到 `{artifact}`"
                    "（内容=本子方向完整要点 + 来源，不是 handoff 摘要的复制）；"
                    "handoff 结构化简报照旧，落盘是叠加、不得替代 handoff。"
                    f"{RESEARCHER_SEARCH_DISCIPLINE}"
                    f"{RESEARCHER_ACADEMIC_SEARCH_DISCIPLINE}"
                    f"{RESEARCHER_NOTE_GUIDANCE}"
                    f"{fold_hint}"
                ),
                "deliverable": {
                    "form": "files",
                    "name": f"【{label}】方向的调研要点 + 来源（已落盘 {artifact}）",
                    "artifacts": [artifact],
                    "citation_mode": "two_phase",
                },
            }
            if angle_fold_note and merged:
                task_body["playbook_note"] = angle_fold_note
            tasks.append(task_body)
    else:
        research_ids = ["research_0"]
        artifact = _RESEARCH_REPORT_DEFAULT_ANGLE_ARTIFACT
        tasks.append(
            {
                "id": "research_0",
                "role": "调研员",
                "search_policy": "academic_literature",
                "task": (
                    f"调研主题【{topic}】：覆盖关键事实 / 现状 / 主要观点与证据；"
                    "关键数字 / 关键结论旁须就地标台账 id（#rN，与工具「[已登记来源]」一致）"
                    "或显式待核实语，勿裸写无出处主张；附来源。"
                    "对关键法条、司法解释、判例等权威出处，须用 read_url 核对原文后再引用，"
                    "勿仅凭搜索摘要断言条文或裁判要旨。"
                    "回报精炼结论 + 关键证据指引，别回贴整段原文。"
                    f"完整调研要点须用 file_write 落盘到 `{artifact}`"
                    "（内容=本主题完整要点 + 来源，不是 handoff 摘要的复制）；"
                    "handoff 结构化简报照旧，落盘是叠加、不得替代 handoff。"
                    f"{RESEARCHER_SEARCH_DISCIPLINE}"
                    f"{RESEARCHER_ACADEMIC_SEARCH_DISCIPLINE}"
                    f"{RESEARCHER_NOTE_GUIDANCE}"
                ),
                "deliverable": {
                    "form": "files",
                    "name": f"【{topic}】的调研要点 + 来源（已落盘 {artifact}）",
                    "artifacts": [artifact],
                    "citation_mode": "two_phase",
                },
            }
        )

    aud = f"，面向读者：{audience}" if audience else ""
    tasks.append(
        {
            "id": "outline",
            "role": "提纲编辑",
            "task": (
                f"综合上游各路调研，为主题【{topic}】拟一份报告提纲{aud}：列出章节结构与每节要点。"
                "据证据定结构（别凭空先写死），确保覆盖各调研方向、无重复无缺口。"
                f"可先 file_read `{RESEARCH_DIR}/` 下各路调研报告取完整要点；"
                f"结构化提纲须用 file_write 落盘到 `{outline_path}`"
                "（章节 + 每节要点全文，不是 handoff 摘要复制）；"
                "handoff 结构化简报照旧，落盘是叠加、不得替代 handoff。"
            ),
            "depends_on": research_ids,
            "deliverable": {
                "form": "files",
                "name": f"一份结构化报告提纲（已落盘 {outline_path}）",
                "artifacts": [outline_path],
                "citation_mode": "two_phase",
            },
            "checkpoint_after": checkpoint,
        }
    )
    tasks.append(
        {
            "id": "write",
            "role": "撰稿人",
            "task": (
                f"严格按上游定稿的提纲、结合各路调研，写成{deliverable}。"
                "忠于调研事实与来源、不杜撰。"
                f"【主文件】整篇落盘到 `{main_path}`（验收只认这一路径）；"
                f"{PAPER_PARALLEL_MERGE_DISCIPLINE}"
                f"{MD_PDF_EXPORT_DISCIPLINE}"
                "【成篇落盘纪律·Artifact-first】① 首写必须是短骨架（标题+各章小标题/"
                "锚点，一次短 file_write）——禁止首写半章散文再 append；② 再按章用 "
                "file_append 或 str_replace 填空，一章写完再下一章；③ 中等篇幅可一次 "
                "file_write 写完全文；④ 预算/token 不够写完下一章时，停在完整章边界，"
                "handoff 标明已完成章节与待续章节，勿在章中部截断；⑤ 禁止整篇 "
                "file_delete 后重写长文；修订优先 str_replace，整文件 file_write "
                "覆盖允许但须完整正文（勿惰性省略）；⑥ 写回执即 artifact manifest，禁止再对本文件 "
                "file_read 回读正文验真。"
            ),
            "depends_on": ["outline"],
            "deliverable": {
                "name": deliverable,
                "form": "files",
                "requires_files": True,
                "artifacts": [main_path],
                "citation_mode": "two_phase",
            },
        }
    )
    tasks.append(
        {
            "id": "review",
            "role": "学术审校员",
            "task": (
                f"对上游成稿（主文件 `{main_path}`）做学术审校（{deliverable}）："
                "核查学术准确性、逻辑完整性与引用规范；"
                "对成稿中的关键法条、司法解释、判例引用，须用 read_url 核对原文后再确认或指出问题，"
                "勿仅凭搜索摘要放行；"
                "指出具体问题并给出可操作的修改建议，不重写全文。"
                f"{DIRECTED_SEARCH_TASK_HINT}"
            ),
            "depends_on": ["write"],
            "deliverable": {"name": "审校报告 + 修改建议"},
            # 审校为依赖写作的收尾节点：通读长稿 + 核对出处。墙钟显式 300s（优先于统一
            # backstop）；token 顶走 worker_budget 统一回填。真纯丙：不再靠显式 tools
            # 名单收窄；定向检索纪律写在 task 正文（见 DIRECTED_SEARCH_TASK_HINT）。
            "timeout_ms": 300_000,
        }
    )
    return tasks, []


def multi_lens_research(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """N×异质透镜并行调研 → 汇总分析师 depends_on 全部透镜做交叉验证（可产 motion_card）.

    Companion shape for ``deep_multi_lens_research`` skill: parallel heterogeneous lenses
    then a synthesizer that cross-checks and may suggest a debate motion — not a compare table.

    幕 1 产物以 ``form=files`` + ``artifacts`` 落盘 ``AgentCore/文档/research/``（各透镜自写报告 +
    汇总员写「汇总与命题卡」）。开工授权（delegation grant）覆盖整次委派的
    file_mutation 工具面，四路并行写文件不会额外弹授权卡；handoff / motion_card
    链路照旧，落盘是叠加。

    lenses 超过扇出上限时折叠进末节点（合并不丢弃），首透镜仍独占公共底料分工。
    """
    topic = clean_str(args.get("topic"))
    if not topic:
        return [], ["multi_lens_research 需要 slot『topic』（要多视角调研的主题 / 事件）"]
    lenses_raw = clean_str_list(args.get("lenses"), cap=None)
    if not lenses_raw:
        lenses_raw = list(_DEFAULT_MULTI_LENSES)
    lens_slots, lens_fold_note = fold_fanout_slots(lenses_raw, label="透镜")
    fold_hint = f" {lens_fold_note}" if lens_fold_note else ""
    raw_um = args.get(USER_MESSAGE_MECH_KEY)
    user_anchor = _user_request_anchor_block(raw_um if isinstance(raw_um, str) else "")

    lens_ids = [f"lens_{i}" for i in range(len(lens_slots))]
    tasks: list[dict[str, Any]] = []

    for i, (lid, parts) in enumerate(zip(lens_ids, lens_slots, strict=True)):
        merged = len(parts) > 1
        label = " + ".join(parts)
        # Division pedagogy keys off the first name in the slot; fold always puts
        # overflow in the last slot so index-0 stays a single primary base owner.
        primary = parts[0]
        artifact = _lens_report_artifact_for_parts(parts)
        is_base = i == 0
        division = _lens_retrieval_division(primary, is_base_owner=is_base)
        scope = (
            f"从以下合并透镜深入调研：{'、'.join(f'【{p}】' for p in parts)}。"
            f"本节点职责涵盖上述全部 {len(parts)} 个透镜；须全部覆盖，勿只做第一项。"
            if merged
            else f"只从【{primary}】透镜深入调研："
        )
        task_body: dict[str, Any] = {
            "id": lid,
            "role": f"{label}视角",
            "task": (
                f"围绕主题 / 事件【{topic}】，{scope}"
                "关键事实、证据、各方主张与来源；聚焦本节点透镜、勿铺开到其它维度。"
                f"{division}"
                f"完整调研报告须用 file_write 落盘到 `{artifact}`"
                "（内容=本透镜完整报告正文，不是 handoff 摘要的复制；勿只写提纲）。"
                "正文引用检索来源时须就地标本回合台账 id（如 #r1，与工具结果末尾"
                "「[已登记来源]」号一致）——落盘文件必须可溯源到调研台账，勿只写自由出处。"
                "关键数字 / 关键结论旁须有 #rN 或显式待核实语，勿裸写无出处主张；"
                "不强迫辩词式【已核实·#eN】二分格式。"
                "handoff 结构化简报照旧（精炼结论 + 证据指针），落盘是叠加、不得替代 handoff。"
                f"{RESEARCHER_NOTE_GUIDANCE}"
                f"{fold_hint}"
            ),
            "deliverable": {
                "form": "files",
                "name": f"【{label}】透镜调研报告（已落盘 {artifact}）",
                "artifacts": [artifact],
                "citation_mode": "two_phase",
            },
        }
        if lens_fold_note and merged:
            task_body["playbook_note"] = lens_fold_note
        tasks.append(task_body)
    tasks.append(
        {
            "id": "synthesizer",
            "role": "汇总分析师",
            "task": (
                f"综合上游各透镜对【{topic}】的调研，做交叉验证："
                "列出共识、事实冲突、价值分歧与证据缺口；给出跨维度综述（非简单并列粘贴）。"
                f"可先 file_read `{_MULTI_LENS_RESEARCH_DIR}/` 下各透镜报告取完整正文。"
                f"完整综述须用 file_write 落盘到 `{_SYNTHESIZER_ARTIFACT}`"
                "（含交叉验证全文；若产命题卡则把命题 / 双方薄立场 / rationale 一并写入该文件；"
                "内容是完整案卷，不是 handoff 摘要复制）。"
                "沿用上游透镜报告中的 #rN 台账锚（或工具结果给出的本回合 id）；"
                "落盘综述须保留可解析的 #rN，勿抹成自由出处。"
                "继承上游关键数字 / 关键结论时须带上 #rN 或保留待核实语，勿抹成既定事实。"
                "handoff 结构化简报与 motion_card 对象照旧，落盘是叠加、不得替代。"
                f"{user_anchor}"
                f"{_SYNTHESIZER_MOTION_CARD_GUIDANCE}"
            ),
            "depends_on": lens_ids,
            "deliverable": {
                "form": "files",
                "name": (
                    "交叉验证综述 + 汇总与命题卡"
                    f"（已落盘 {_SYNTHESIZER_ARTIFACT}；必要时附建议开辩命题卡）"
                ),
                "artifacts": [_SYNTHESIZER_ARTIFACT],
                "citation_mode": "two_phase",
            },
        }
    )
    return tasks, []

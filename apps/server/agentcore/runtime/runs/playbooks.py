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

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentcore.runtime.runs.web_quality_rules import anti_slop_prompt_block
from agentcore.workspace.stage_dirs import RESEARCH_DIR

# Cap the slot-driven fan-out (调研子方向 / 待比较选项) so a playbook can't silently balloon a
# batch;
# build_run_plan still enforces the global MAX_DELEGATION_TASKS on the expanded result as the real
# net. Kept modest because a playbook is a STANDARD shape, not a place to launch a huge swarm.
MAX_PLAYBOOK_FANOUT = 6

PlaybookBuilder = Callable[[dict[str, Any]], "tuple[list[dict[str, Any]], list[str]]"]


@dataclass(frozen=True)
class Playbook:
    """One named, instantiable team shape: ``build(slots) -> (tasks, errors)``.

    ``summary`` / ``slots`` are the human-facing one-liners surfaced in the ``delegate`` schema
    and the ``team_orchestration_advanced`` skill so the CEO knows the shape exists and what to
    pass; ``build`` is the pure expander.
    """

    name: str
    summary: str
    slots: str
    build: PlaybookBuilder


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_str_list(value: Any, *, cap: int | None = None) -> list[str]:
    """Normalise a slot to a deduped list of non-empty strings (preserves order, drops
    non-strings / blanks). ``cap`` truncates when set; ``None`` keeps all. A non-list
    slot → ``[]`` so the builder's own required-slot check produces the user-facing
    error rather than a type crash."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = item.strip() if isinstance(item, str) else ""
        if s and s not in out:
            out.append(s)
        if cap is not None and len(out) >= cap:
            break
    return out


def _fold_fanout_slots(
    items: list[str],
    *,
    limit: int = MAX_PLAYBOOK_FANOUT,
    label: str = "项",
) -> tuple[list[list[str]], str | None]:
    """Pack ``items`` into ≤``limit`` slots; overflow is merged into the last slot (not dropped).

    Each slot is a non-empty list of names (usually length 1). When folding occurs, the
    second return is a CEO/user-facing note describing what was merged; otherwise ``None``.
    ``label`` customises the note noun（角度 / 透镜 / 分区…）.
    """
    if not items:
        return [], None
    if len(items) <= limit:
        return [[x] for x in items], None
    head = items[: limit - 1]
    tail = items[limit - 1 :]
    slots = [[x] for x in head] + [list(tail)]
    note = (
        f"【扇出折叠】共 {len(items)} 个{label}，超过扇出上限 {limit}；"
        f"已将末尾 {len(tail)} 个合并到最后一个节点"
        f"（{' · '.join(tail)}），未丢弃。"
        "末节点职责须覆盖上述全部合并项。"
        "请在对用户的计划/结果说明中点明本次折叠及明细。"
    )
    return slots, note


def _pair_adjacent(items: list[str]) -> list[list[str]]:
    """Adjacent pairs; odd leftover becomes a singleton last group."""
    groups: list[list[str]] = []
    i = 0
    while i < len(items):
        if i + 1 < len(items):
            groups.append([items[i], items[i + 1]])
            i += 2
        else:
            groups.append([items[i]])
            i += 1
    return groups


def _fold_group_slots(
    groups: list[list[str]], *, limit: int
) -> tuple[list[list[str]], list[str]]:
    """If ``groups`` exceed ``limit``, flatten overflow groups into the last slot.

    Returns ``(slots, folded_member_names)``; ``folded_member_names`` is empty when no fold.
    """
    if len(groups) <= limit:
        return groups, []
    head = groups[: limit - 1]
    tail_groups = groups[limit - 1 :]
    merged = [x for g in tail_groups for x in g]
    # Members that were not in the would-be first overflow group alone — for notes,
    # list every member now sitting in the last slot after the fold.
    return head + [merged], list(merged)


def _adaptive_partition_slots(
    items: list[str], *, max_width: int = MAX_PLAYBOOK_FANOUT
) -> tuple[list[list[str]], str | None]:
    """Deterministic section→worker mapping for catalog sites (no CEO knob).

    - N≤3: 1:1
    - N≥4: 相邻两段一组，再按 ``max_width`` 折叠（建站 / 工具台传 2；默认 6）
    """
    n = len(items)
    if n == 0:
        return [], None
    if n <= 3:
        return [[x] for x in items], None

    groups = _pair_adjacent(items)
    detail = "；".join(" + ".join(g) for g in groups)
    if len(groups) <= max_width:
        note = (
            f"【分区合并】共 {n} 个分区，按相邻两段一组合成 {len(groups)} 个实现节点"
            f"（{detail}），未丢弃。"
            "各节点职责须覆盖其组内全部段；仍遵守只补丁本区、禁整文件重写。"
            "请在对用户的计划/结果说明中点明本次分组及明细。"
        )
        return groups, note

    folded, last_members = _fold_group_slots(groups, limit=max_width)
    folded_detail = "；".join(" + ".join(g) for g in folded)
    note = (
        f"【分区合并】共 {n} 个分区，超过实现宽度上限 {max_width}；"
        f"先按相邻两段一组再将尾部折叠进末组，得到 {len(folded)} 个实现节点"
        f"（{folded_detail}），未丢弃。"
        f"末节点覆盖：{' · '.join(last_members)}。"
        "各节点职责须覆盖其组内全部段；仍遵守只补丁本区、禁整文件重写。"
        "请在对用户的计划/结果说明中点明本次分组及明细。"
    )
    return folded, note


# 建站 / 工具台分区实现宽度上限（调研 / compare 仍用 MAX_PLAYBOOK_FANOUT=6）
_BUILD_WEBSITE_SECTION_MAX_WIDTH = 2

# 文案包结构化板块（验收用 required_sections，替代高 min_length）
_BUILD_WEBSITE_COPY_SECTIONS = (
    "品牌一句话",
    "各分区标题与正文",
    "CTA",
    "SEO",
)

_BUILD_WEBSITE_VISUAL_THESIS = (
    "【首步·visual thesis + 文案先行】先书面钉死视觉 thesis（品牌气质 / 对比度策略 / "
    "字体方向 / 动效克制原则，各 1–2 句），再写分区文案；"
    "禁止未立 thesis 就堆板块或套默认模板皮。"
)

_BUILD_WEBSITE_DOMAIN_HINT = (
    "站点类型默认按营销/落地页审美；若 site 描述明显是产品控制台 / 工具页，"
    "按工具页信息架构优先。"
)


_RESEARCHER_NOTE_GUIDANCE = (
    "开始本子方向前先 read_notes 检查队友是否已覆盖；"
    "发现重要结论或关键数据点时用 post_note(kind=decision) 或 post_note(kind=heads_up) "
    "分享给团队，避免重复劳动。"
)

# 调研员检索纪律（通用；连续空结果换策略 + 少搜多读；暂不做无引用不得交卷）。
_RESEARCHER_SEARCH_DISCIPLINE = (
    "【检索纪律】少搜多读：有命中后优先 read_url 深读核对再开新搜；"
    "连续空结果必须换策略（缩短/同义改写 query、换权威域名/来源类型，或改读已有命中），"
    "禁止同一空转 query 反复烧预算；权威出处须 read_url 核对原文后再引用。"
)

# 审查 / 调查类 playbook 任务书检索纪律（与 worker_budget.DIRECTED_SEARCH_DISCIPLINE 同义；
# playbook 内联避免循环 import，测试可对 task 文案断言）。
_DIRECTED_SEARCH_TASK_HINT = (
    "【检索纪律】概念/意图先用 code_search，精确符号或字符串用 grep；"
    "命中后再 file_read（优先 offset/limit）；禁止无目标地整目录逐文件通读。"
)


def _research_report(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """N×并行调研 → 提纲（依赖调研，默认 checkpoint 让用户过目）→ 写作 → 学术审校.

    The doc's own named example (调研→提纲→checkpoint→写作→审校); mirrors the 进阶 skill「调研驱动的
    大型交付，让结构跟着证据走」as a one-call shape.

    成篇验收钉死单一主文件（``output_path`` / 默认 ``AgentCore/文档/research/报告.md``）；
    若 CEO 手写并行拆章，须另加 merge 步并把各章 brief 写死同一路径——见
    ``PAPER_PARALLEL_MERGE_DISCIPLINE``。
    """
    from agentcore.runtime.runs.research_quality import (
        PAPER_PARALLEL_MERGE_DISCIPLINE,
        research_report_main_artifact,
    )

    topic = _clean_str(args.get("topic"))
    if not topic:
        return [], ["research_report 需要 slot『topic』（要调研并成文的主题）"]
    angles_raw = _clean_str_list(args.get("angles"), cap=None)
    angle_slots, angle_fold_note = _fold_fanout_slots(angles_raw, label="调研子方向")
    checkpoint = bool(args.get("checkpoint", True))
    audience = _clean_str(args.get("audience"))
    deliverable = _clean_str(args.get("deliverable")) or f"一篇关于【{topic}】的完整报告"
    main_path = research_report_main_artifact(_clean_str(args.get("output_path")) or None)
    fold_hint = f" {angle_fold_note}" if angle_fold_note else ""

    tasks: list[dict[str, Any]] = []
    if angle_slots:
        research_ids = [f"research_{i}" for i in range(len(angle_slots))]
        for rid, parts in zip(research_ids, angle_slots, strict=True):
            merged = len(parts) > 1
            label = " + ".join(parts)
            scope = (
                f"专门调研以下合并子方向：{'、'.join(f'【{p}】' for p in parts)}。"
                f"本节点职责涵盖上述全部 {len(parts)} 个方向；须全部覆盖，勿只做第一项。"
                if merged
                else f"专门调研这一个子方向：{parts[0]}。"
            )
            task_body: dict[str, Any] = {
                "id": rid,
                "role": "调研员",
                "task": (
                    f"围绕主题【{topic}】，{scope}"
                    "给出该子方向的关键事实 / 现状 / 证据；关键数字 / 关键结论旁须就地标"
                    "台账 id（#rN，与工具「[已登记来源]」一致）或显式待核实语，"
                    "勿裸写无出处主张；"
                    "附来源（文件:行 或 链接）。"
                    "对关键法条、司法解释、判例等权威出处，须用 read_url 核对原文后再引用，"
                    "勿仅凭搜索摘要断言条文或裁判要旨。"
                    "聚焦本子方向、回报精炼结论而非整段原文，别铺开到其它角度。"
                    f"{_RESEARCHER_SEARCH_DISCIPLINE}"
                    f"{_RESEARCHER_NOTE_GUIDANCE}"
                    f"{fold_hint}"
                ),
                "deliverable": {"name": f"【{label}】方向的调研要点 + 来源"},
            }
            if angle_fold_note and merged:
                task_body["playbook_note"] = angle_fold_note
            tasks.append(task_body)
    else:
        research_ids = ["research_0"]
        tasks.append(
            {
                "id": "research_0",
                "role": "调研员",
                "task": (
                    f"调研主题【{topic}】：覆盖关键事实 / 现状 / 主要观点与证据；"
                    "关键数字 / 关键结论旁须就地标台账 id（#rN，与工具「[已登记来源]」一致）"
                    "或显式待核实语，勿裸写无出处主张；附来源。"
                    "对关键法条、司法解释、判例等权威出处，须用 read_url 核对原文后再引用，"
                    "勿仅凭搜索摘要断言条文或裁判要旨。"
                    "回报精炼结论 + 关键证据指引，别回贴整段原文。"
                    f"{_RESEARCHER_SEARCH_DISCIPLINE}"
                    f"{_RESEARCHER_NOTE_GUIDANCE}"
                ),
                "deliverable": {"name": f"【{topic}】的调研要点 + 来源"},
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
            ),
            "depends_on": research_ids,
            "deliverable": {"name": "一份结构化报告提纲（章节 + 每节要点）"},
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
                "【成篇落盘纪律·Artifact-first】① 首写必须是短骨架（标题+各章小标题/"
                "锚点，一次短 file_write）——禁止首写半章散文再 append；② 再按章用 "
                "file_append 或 str_replace 填空，一章写完再下一章；③ 中等篇幅可一次 "
                "file_write 写完全文；④ 预算/token 不够写完下一章时，停在完整章边界，"
                "handoff 标明已完成章节与待续章节，勿在章中部截断；⑤ 禁止整篇 "
                "file_delete 后重写长文，也禁止对已成篇草稿 file_write 全文覆盖——"
                "修订用 str_replace；⑥ 写回执即 artifact manifest，禁止再对本文件 "
                "file_read 回读正文验真。"
            ),
            "depends_on": ["outline"],
            "deliverable": {
                "name": deliverable,
                "form": "files",
                "requires_files": True,
                "artifacts": [main_path],
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
                f"{_DIRECTED_SEARCH_TASK_HINT}"
            ),
            "depends_on": ["write"],
            "deliverable": {"name": "审校报告 + 修改建议"},
            # 审校为依赖写作的收尾节点：通读长稿 + 核对出处。墙钟显式 300s（优先于统一
            # backstop）；token 顶走 worker_budget 统一回填。定向检索：显式装配
            # grep/code_search（+ 读文件 / 核对原文），避免 least-privilege 退化成只
            # file_list/file_read 整文件通读。
            "tools": [
                "file_list",
                "file_read",
                "grep",
                "code_search",
                "web_search",
                "read_url",
            ],
            "timeout_ms": 300_000,
        }
    )
    return tasks, []


def _build_feature(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """后端接口 →（前端页面 ‖ 测试）并行依赖接口；接口契约经便签墙对齐.

    The doc's recurring 登录 example, and a direct consumer of the just-shipped 4b 拼图边对账 —
    the parallel 页面 / 测试 share the api's broadcast interface contract."""
    feature = _clean_str(args.get("feature"))
    if not feature:
        return [], ["build_feature 需要 slot『feature』（要实现的功能）"]
    stack = _clean_str(args.get("stack"))
    stack_hint = f"（技术栈：{stack}）" if stack else ""
    include = _clean_str_list(args.get("include"), cap=2)
    want_ui = (not include) or ("ui" in include)
    want_test = (not include) or ("test" in include)

    tasks: list[dict[str, Any]] = [
        {
            "id": "api",
            "role": "后端工程师",
            "task": (
                f"实现【{feature}】的后端接口{stack_hint}。先把接口契约（路径 / 方法 / 入参 / "
                "返回结构 / 错误形状）用 post_note(kind=decision) 广播到团队便签墙，再实现；"
                "务必用 file_write 把代码写进工作区。"
            ),
            "deliverable": {
                "name": "可用的后端接口 + 已广播的接口契约",
                "requires_files": True,
            },
        }
    ]
    if want_ui:
        tasks.append(
            {
                "id": "ui",
                "role": "前端工程师",
                "task": (
                    f"实现【{feature}】的前端页面{stack_hint}，严格对接 api 步骤广播的接口契约"
                    "（路径 / 字段 / 返回）。发现契约对不上就按最新契约对齐、"
                    "必要时 post_note 提醒；"
                    "务必用 file_write 把代码写进工作区。"
                ),
                "depends_on": ["api"],
                "deliverable": {
                    "name": "可用的前端页面，对接后端接口",
                    "requires_files": True,
                },
            }
        )
    if want_test:
        tasks.append(
            {
                "id": "test",
                "role": "测试工程师",
                "task": (
                    f"为【{feature}】写测试，按便签墙上 api 广播的接口契约"
                    "覆盖正常 + 边界 + 错误形状；"
                    "务必用 file_write 把测试文件写进工作区。"
                ),
                "depends_on": ["api"],
                "deliverable": {
                    "name": "覆盖接口契约的测试",
                    "requires_files": True,
                },
            }
        )
    return tasks, []


# 建站 / 落地页产物约定（下游便签与 QA 回读共用；禁 CEO 手糊内容→单前端）。
_BUILD_WEBSITE_DIR = "site"
_BUILD_WEBSITE_COPY = f"{_BUILD_WEBSITE_DIR}/copy.md"
_BUILD_WEBSITE_COPY_DIR = f"{_BUILD_WEBSITE_DIR}/copy"
_BUILD_WEBSITE_COPY_A = f"{_BUILD_WEBSITE_COPY_DIR}/part_a.md"
_BUILD_WEBSITE_COPY_B = f"{_BUILD_WEBSITE_COPY_DIR}/part_b.md"
_BUILD_WEBSITE_HTML = f"{_BUILD_WEBSITE_DIR}/index.html"
_BUILD_WEBSITE_CSS = f"{_BUILD_WEBSITE_DIR}/styles.css"
_BUILD_WEBSITE_JS = f"{_BUILD_WEBSITE_DIR}/main.js"
_BUILD_WEBSITE_CONTRACT = f"{_BUILD_WEBSITE_DIR}/CONTRACT.md"
_BUILD_WEBSITE_DESIGN = f"{_BUILD_WEBSITE_DIR}/DESIGN.md"
_BUILD_WEBSITE_QA = f"{_BUILD_WEBSITE_DIR}/QA.md"
_BUILD_WEBSITE_SECTIONS_DIR = f"{_BUILD_WEBSITE_DIR}/sections"
_DEFAULT_WEBSITE_SECTIONS = ("首屏英雄区", "卖点能力区", "行动号召区")
_DEFAULT_TOOLSHED_SECTIONS = ("应用外壳", "侧栏导航", "数据表格")

_BUILD_TOOLSHED_VISUAL_THESIS = (
    "【首步·信息架构 + 文案先行】先书面钉死信息架构（主导航 / 主工作区 / "
    "筛选与详情层级，各 1–2 句），再写分区文案；"
    "禁止未立架构就堆板块，禁止套营销着陆页 hero / pricing 皮。"
)

_BUILD_TOOLSHED_DOMAIN_HINT = (
    "站点类型按产品控制台 / 工具台 dense UI；清晰信息架构与可读性优先，装饰克制。"
)

_BUILD_TOOLSHED_COPY_SECTIONS = (
    "产品一句话",
    "各分区标题与正文",
    "主操作 CTA",
    "空态说明",
)


def _section_marker_slug(section_index: int) -> str:
    return f"s{section_index}"


def _section_marker_comment(section_index: int, *, end: bool = False) -> str:
    slug = _section_marker_slug(section_index)
    tag = "END" if end else "START"
    return f"<!-- SECTION:{slug} {tag} -->"


def _section_fragment_html(section_index: int) -> str:
    """Independent HTML fragment path for one SECTION slot (Wave3 A)."""
    return f"{_BUILD_WEBSITE_SECTIONS_DIR}/{_section_marker_slug(section_index)}.html"


def _section_fragment_css(section_index: int) -> str:
    return f"{_BUILD_WEBSITE_SECTIONS_DIR}/{_section_marker_slug(section_index)}.css"


def _section_fragment_js(section_index: int) -> str:
    return f"{_BUILD_WEBSITE_SECTIONS_DIR}/{_section_marker_slug(section_index)}.js"


def _section_fragment_paths(parts: list[str], sections: list[str]) -> list[str]:
    """HTML fragment artifacts owned by a partition worker (one file per SECTION)."""
    paths: list[str] = []
    for part in parts:
        try:
            idx = sections.index(part)
        except ValueError:
            continue
        paths.append(_section_fragment_html(idx))
    return paths


def _section_fragment_guidance(parts: list[str], sections: list[str]) -> str:
    """Task-book: write independent fragments; never patch shared index.html."""
    bits: list[str] = []
    for part in parts:
        try:
            idx = sections.index(part)
        except ValueError:
            continue
        slug = _section_marker_slug(idx)
        html_p = _section_fragment_html(idx)
        css_p = _section_fragment_css(idx)
        js_p = _section_fragment_js(idx)
        bits.append(
            f"【{part}】→ `{html_p}`"
            f"（可选样式 `{css_p}` / 脚本 `{js_p}`；标记名 {slug}）"
        )
    if not bits:
        return ""
    return (
        "【分区独立片段】只 file_write 本区独立产物，禁止对共享 "
        f"`{_BUILD_WEBSITE_HTML}` / `{_BUILD_WEBSITE_CSS}` / `{_BUILD_WEBSITE_JS}` "
        "做 str_replace / file_append / file_write（并行写同文件会互相踩锚点）："
        + "；".join(bits)
        + "。"
        "HTML 片段须是可嵌入的区块正文（勿包 html/head/body）；"
        "组装节点稍后注入对应 SECTION 标记对。"
    )


def _partition_budget_guidance(parts: list[str], sections: list[str], copy_path: str) -> str:
    """Wave3 B: inject marker/path checklist + read discipline (少空转 file_read)."""
    marker_bits: list[str] = []
    for part in parts:
        try:
            idx = sections.index(part)
        except ValueError:
            continue
        slug = _section_marker_slug(idx)
        marker_bits.append(
            f"【{part}】标记 `{_section_marker_comment(idx)}`…"
            f"`{_section_marker_comment(idx, end=True)}` → 写 `{_section_fragment_html(idx)}`"
            f"（slug={slug}）"
        )
    markers = "；".join(marker_bits) if marker_bits else "（见分区清单）"
    return (
        "【分区上下文预算】开局已注入骨架契约/设计摘要（见「强制注入」块）；"
        f"文案键位优先读上游交接与 `{copy_path}` 指针。"
        f"写前确认目标片段路径与 SECTION 标记存在即可：{markers}。"
        "【禁止】反复 file_read 同一路径（含 DESIGN/CONTRACT/index）；"
        "同文件至多精读 1–2 次；缺条目再读一次 CONTRACT 即可，勿通读空转。"
        f"【禁止】为找锚点反复通读 `{_BUILD_WEBSITE_HTML}`——"
        "A 后分区只写独立片段，组装节点负责注入。"
    )


def _skeleton_section_markers_guidance(sections: list[str]) -> str:
    """Skeleton task: embed one START/END comment pair per section in index.html."""
    pairs = "、".join(
        f"【{name}】=`{_section_marker_comment(i)}`…`{_section_marker_comment(i, end=True)}`"
        for i, name in enumerate(sections)
    )
    return (
        f"在 `{_BUILD_WEBSITE_HTML}` 为每个分区埋唯一 SECTION 注释对（组装注入锚点）："
        f"{pairs}。"
        "各对之间放该分区的语义化容器占位（稳定 id/class）；"
        "对内可留空或极简占位——分区实现写独立片段，由 assemble 注入。"
        "CONTRACT.md 须同步列出各分区对应的 SECTION 标记名（s0/s1/…）、"
        f"片段路径（`{_BUILD_WEBSITE_SECTIONS_DIR}/sN.html`）与 id/class。"
    )


def _build_catalog_site(
    args: dict[str, Any],
    *,
    playbook_name: str,
    pack: str,
    anti_slop_domain: str,
    default_sections: tuple[str, ...],
    visual_thesis: str,
    domain_hint: str,
    copy_sections: tuple[str, ...],
    site_slot_hint: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Shared site pipeline (marketing ``build_website`` / toolshed ``build_toolshed``).

    文案 → 设计契约 → 骨架+契约 → N×分区独立片段 → assemble 注入 index → 独立 QA。
    Wave3 A：分区并行只写 ``site/sections/sN.*``，禁止并行 str_replace 同一 index.html；
    单写者 assemble 再组装。文件节点 ``strict=True``（Wave3 C：硬缺口/降级不得冒充完成）。

    分区粒度（D）：N≤3 保持 1:1；N≥4 相邻配对后再按 ``_BUILD_WEBSITE_SECTION_MAX_WIDTH``
    （=2）折叠。文案恒单 worker 落 ``site/copy.md``（取消双文案分裂）。
    """
    from agentcore.runtime.runs.website_catalog import (
        catalog_contract_stub,
        catalog_prompt_block_section,
        catalog_prompt_block_skeleton,
        catalog_shared_css_for_skeleton,
        catalog_shell_bodies_for_sections,
    )
    from agentcore.runtime.runs.website_style import (
        DESIGN_MD_PATH,
        design_prompt_block,
        get_style_confirmation,
    )

    site = _clean_str(args.get("site"))
    if not site:
        return [], [f"{playbook_name} 需要 slot『site』（{site_slot_hint}）"]
    sections = _clean_str_list(args.get("sections"), cap=None)
    if not sections:
        sections = list(default_sections)
    section_slots, merge_note = _adaptive_partition_slots(
        sections, max_width=_BUILD_WEBSITE_SECTION_MAX_WIDTH
    )
    stack = _clean_str(args.get("stack"))
    stack_hint = f"（技术栈：{stack}）" if stack else "（默认静态 HTML/CSS/JS，可按 stack 调整）"
    audience = _clean_str(args.get("audience"))
    aud = f"，面向读者 / 访客：{audience}" if audience else ""
    all_sections_label = "、".join(sections)
    merge_plan_hint = f" {merge_note}" if merge_note else ""
    anti_slop = anti_slop_prompt_block(domain=anti_slop_domain)
    catalog_skeleton = catalog_prompt_block_skeleton(sections, pack=pack)
    catalog_shells = catalog_shell_bodies_for_sections(sections, pack=pack)
    catalog_css = catalog_shared_css_for_skeleton(pack=pack)
    catalog_contract = catalog_contract_stub(sections, pack=pack)
    # Optional conversation_id for style ledger injection (delegate may pass via args).
    style_conf = get_style_confirmation(
        _clean_str(args.get("_conversation_id")) or None
    )
    design_block = design_prompt_block(style=style_conf)
    copy_common = (
        f"{visual_thesis}{domain_hint}"
        f"{anti_slop}"
        "任务书只消费事实输入（品牌 / 受众 / 素材 / 用户明示偏好）；"
        "禁止在文案包里自拟配色色板 / 动效清单当施工图（色板归 design 节点）。"
    )
    copy_deliverable = {
        "form": "files",
        "required_sections": list(copy_sections),
        "must_contain_soft": True,
        "web_quality_scan": False,
        "strict": True,
    }

    tasks: list[dict[str, Any]] = []
    copy_ids = ["copy"]
    copy_artifacts = [_BUILD_WEBSITE_COPY]
    section_copy_paths = [_BUILD_WEBSITE_COPY] * len(section_slots)
    tasks.append(
        {
            "id": "copy",
            "role": "内容文案",
            "task": (
                f"{copy_common}"
                f"为站点【{site}】撰写完整文案包{aud}：品牌一句话、各区块标题 / 正文 / CTA、"
                "SEO 标题与 meta description、可选的微文案（按钮 / 脚注）。"
                f"须覆盖这些分区：{all_sections_label}。"
                f"用 file_write 落盘 `{_BUILD_WEBSITE_COPY}`；"
                "关键主张须可核对（有出处或标待核实），勿堆空话。"
                "收尾用 post_note(kind=decision) 广播文案分区清单，供设计 / 骨架与分区实现对齐。"
                f"{merge_plan_hint}"
            ),
            "deliverable": {
                **copy_deliverable,
                "name": f"站点文案包（已落盘 {_BUILD_WEBSITE_COPY}）",
                "artifacts": [_BUILD_WEBSITE_COPY],
            },
        }
    )
    design_copy_hint = f"据上游文案（`{_BUILD_WEBSITE_COPY}`）"
    skeleton_copy_hint = (
        f"先 file_read `{DESIGN_MD_PATH}` 与文案（`{_BUILD_WEBSITE_COPY}`）；"
        "色板 / 字体 / 间距只引用 DESIGN tokens，禁止散写 hex。"
    )

    tasks.append(
        {
            "id": "design",
            "role": "设计契约",
            "task": (
                f"{design_copy_hint}为站点【{site}】落设计契约{aud}。"
                f"{design_block}"
                f"{anti_slop}"
                "可保留简短 visual thesis 作叙事摘要，但 tokens + 风格 id 是硬交付。"
                "收尾用 post_note(kind=decision) 广播 DESIGN 路径与风格 id。"
                f"{merge_plan_hint}"
            ),
            "depends_on": list(copy_ids),
            "deliverable": {
                "form": "files",
                "name": f"设计契约（已落盘 {_BUILD_WEBSITE_DESIGN}）",
                "artifacts": [_BUILD_WEBSITE_DESIGN],
                "placeholder_hard_exempt_artifacts": [_BUILD_WEBSITE_DESIGN],
                "web_quality_scan": False,
                "strict": True,
            },
        }
    )

    tasks.append(
        {
            "id": "skeleton",
            "role": "骨架工程师",
            "task": (
                f"{skeleton_copy_hint}为【{site}】落下可运行的页面骨架{stack_hint}："
                f"用 file_write 写 `{_BUILD_WEBSITE_HTML}`（语义化分区容器 + 占位，"
                "各区块有稳定 id/class）、"
                f"`{_BUILD_WEBSITE_CSS}`（基础排版 / CSS 变量须对齐 `{DESIGN_MD_PATH}` tokens；"
                "可并入 catalog `_shared.css` 变量桥）、"
                f"`{_BUILD_WEBSITE_JS}`（交互入口空壳或最小 wiring）。"
                f"分区清单（须全部建容器）：{all_sections_label}。"
                f"{_skeleton_section_markers_guidance(sections)}"
                f"{catalog_skeleton}"
                f"{catalog_shells}"
                f"{catalog_css}"
                f"{catalog_contract}"
                f"另用 file_write 写 `{_BUILD_WEBSITE_CONTRACT}`：列出每个分区的 "
                "SECTION 标记名、catalog id/指针、id/class/组件名、依赖的文案键、"
                "交互约定（点击 / 滚动 / 表单等）——"
                "可基于上方 CONTRACT 起步表扩写，这是下游分区实现的契约清单，禁止含糊。"
                f"{anti_slop}"
                "用 post_note(kind=decision) 广播契约要点与文件路径；"
                "骨架阶段只建结构与契约，勿把某一分区做到视觉终态。"
                f"{merge_plan_hint}"
            ),
            "depends_on": ["design"],
            "deliverable": {
                "form": "files",
                "name": (
                    "HTML 骨架 + CSS/JS 空壳 + 契约清单"
                    f"（{_BUILD_WEBSITE_HTML} / {_BUILD_WEBSITE_CONTRACT} 等）"
                ),
                "artifacts": [
                    _BUILD_WEBSITE_HTML,
                    _BUILD_WEBSITE_CSS,
                    _BUILD_WEBSITE_JS,
                    _BUILD_WEBSITE_CONTRACT,
                ],
                # CONTRACT + DESIGN (loaded for web_quality token gate) are meta docs.
                "placeholder_hard_exempt_artifacts": [
                    _BUILD_WEBSITE_CONTRACT,
                    _BUILD_WEBSITE_DESIGN,
                ],
                # Hard DESIGN / token gate only — empty shells skip anti-slop soft.
                "web_quality_scan": True,
                "web_quality_soft_exempt": True,
                "strict": True,
            },
        },
    )

    section_ids = [f"section_{i}" for i in range(len(section_slots))]
    all_fragment_html: list[str] = []
    for sid, parts, copy_path in zip(
        section_ids, section_slots, section_copy_paths, strict=True
    ):
        merged = len(parts) > 1
        label = " + ".join(parts)
        scope = (
            (
                f"实现以下合并分区（站点【{site}】）{stack_hint}："
                f"{'、'.join(f'【{p}】' for p in parts)}。"
                f"本节点职责涵盖上述全部 {len(parts)} 段；须全部补齐，勿只做第一段。"
            )
            if merged
            else f"只实现页面分区【{parts[0]}】（站点【{site}】）{stack_hint}。"
        )
        other_forbid = (
            "也禁止包办本节点职责以外的其它分区或另起平行整站。"
            if merged
            else "也禁止包办其它分区或另起平行整站。"
        )
        frag_paths = _section_fragment_paths(parts, sections)
        all_fragment_html.extend(frag_paths)
        frag_guidance = _section_fragment_guidance(parts, sections)
        budget_guidance = _partition_budget_guidance(parts, sections, copy_path)
        catalog_section = catalog_prompt_block_section(parts, pack=pack)
        task_body: dict[str, Any] = {
            "id": sid,
            "role": f"{label}实现",
            "task": (
                f"{scope}"
                f"{budget_guidance}"
                "严格按注入的契约摘要与文案键写出本区 HTML/CSS/JS 片段；"
                "颜色 / 字体只引用 DESIGN tokens，【禁止】散写未声明 hex。"
                f"{catalog_section}"
                f"{frag_guidance}"
                f"{other_forbid}"
                f"{anti_slop}"
                "发现契约缺口用 post_note(kind=heads_up) 提醒，勿静默改契约。"
                "本区交互须与契约一致；挂空 class/id 会被 web_seam 静态门禁拦下；"
                "坏 CSS / 编造联系方式 / 散色 / anti-slop 会被 web_quality 门禁拦下。"
            ),
            "depends_on": ["skeleton"],
            # Wave3 B：开局注入契约/设计/本组文案摘要，少依赖反复 file_read。
            "context_inject_files": [
                _BUILD_WEBSITE_CONTRACT,
                DESIGN_MD_PATH,
                copy_path,
            ],
            "deliverable": {
                "form": "files",
                "name": f"分区【{label}】独立片段（待 assemble 注入）",
                "artifacts": frag_paths,
                "web_quality_scan": True,
                "strict": True,
            },
        }
        if merge_note and merged:
            # Machine-readable note for delegate / tests; builder ignores unknown keys.
            task_body["playbook_note"] = merge_note
        tasks.append(task_body)

    frag_list = "、".join(f"`{p}`" for p in all_fragment_html) or "（无分区片段）"
    assemble_pairs = "；".join(
        f"`{_section_marker_comment(i)}`…`{_section_marker_comment(i, end=True)}`"
        f" ← `{_section_fragment_html(i)}`"
        for i in range(len(sections))
    )
    tasks.append(
        {
            "id": "assemble",
            "role": "页面组装",
            "task": (
                f"将各分区独立片段组装进站点【{site}】骨架（单写者，禁止与分区并行抢写）。"
                f"先 file_read `{_BUILD_WEBSITE_HTML}` 与全部片段：{frag_list}。"
                "对每个 SECTION 标记对，用 write_section（section=sN + from_file=片段路径）"
                "把 HTML 片段注入标记对之间——【禁止】用 str_replace 猜占位正文"
                f"（write_section 只认标记，不怕缩进漂移）：{assemble_pairs}。"
                f"若存在 `{_BUILD_WEBSITE_SECTIONS_DIR}/sN.css` / `.js`，"
                f"用 file_append 追加进 `{_BUILD_WEBSITE_CSS}` / `{_BUILD_WEBSITE_JS}`"
                "（加分区注释分隔）。"
                f"【禁止】file_write 整文件重写 `{_BUILD_WEBSITE_HTML}`；"
                "【禁止】改文案 / DESIGN / 契约正文。"
                f"{anti_slop}"
                "组装后抽查标记对齐全、无残留空壳占位；缺口用 post_note(kind=heads_up) 上报。"
            ),
            "depends_on": list(section_ids),
            # Wave3 D：交付预留窗口放行 assemble+QA，砍未开跑次要分区。
            "ceiling_priority": True,
            "deliverable": {
                "form": "files",
                "name": (
                    f"分区已组装进骨架（{_BUILD_WEBSITE_HTML} / "
                    f"{_BUILD_WEBSITE_CSS} / {_BUILD_WEBSITE_JS}）"
                ),
                "artifacts": [
                    _BUILD_WEBSITE_HTML,
                    _BUILD_WEBSITE_CSS,
                    _BUILD_WEBSITE_JS,
                ],
                "web_quality_scan": True,
                "strict": True,
            },
        }
    )

    copy_files_qa = " / ".join(f"`{p}`" for p in copy_artifacts)
    tasks.append(
        {
            "id": "qa",
            "role": "页面 QA",
            "task": _website_qa_task(
                site=site,
                copy_files_qa=copy_files_qa,
                tone_qa="",
                deferred_ok=True,
            ),
            "depends_on": ["assemble"],
            "ceiling_priority": True,
            "deliverable": {
                "form": "files",
                "name": f"QA 报告（已落盘 {_BUILD_WEBSITE_QA}）",
                "artifacts": [_BUILD_WEBSITE_QA],
                "web_seam_scope": f"{_BUILD_WEBSITE_DIR}/",
                "placeholder_hard_exempt": True,
                "web_quality_scan": True,
                "visual_critic": True,
                "strict": True,
            },
            "timeout_ms": 300_000,
        }
    )
    return tasks, []


def _build_website(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """文案 → 设计契约 → 骨架+契约 → N×分区实现 → 独立 QA（营销 / 落地页）.

    Lesson from GEO 官网事故：CEO 手糊「内容→前端」两节点、前端单 worker 包整站、无 QA
    波次 → 交付烂页。本 playbook 把五波次钉死（含独立 design），强制 marketing catalog。
    """
    from agentcore.runtime.runs.website_catalog import PACK_MARKETING

    return _build_catalog_site(
        args,
        playbook_name="build_website",
        pack=PACK_MARKETING,
        anti_slop_domain="marketing",
        default_sections=_DEFAULT_WEBSITE_SECTIONS,
        visual_thesis=_BUILD_WEBSITE_VISUAL_THESIS,
        domain_hint=_BUILD_WEBSITE_DOMAIN_HINT,
        copy_sections=_BUILD_WEBSITE_COPY_SECTIONS,
        site_slot_hint="要建的站点 / 落地页简述",
    )


def _build_toolshed(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """同五波；控制台 / 工具台 dense；强制 tool_dense pack + anti-slop domain=tool."""
    from agentcore.runtime.runs.website_catalog import PACK_TOOL_DENSE

    return _build_catalog_site(
        args,
        playbook_name="build_toolshed",
        pack=PACK_TOOL_DENSE,
        anti_slop_domain="tool",
        default_sections=_DEFAULT_TOOLSHED_SECTIONS,
        visual_thesis=_BUILD_TOOLSHED_VISUAL_THESIS,
        domain_hint=_BUILD_TOOLSHED_DOMAIN_HINT,
        copy_sections=_BUILD_TOOLSHED_COPY_SECTIONS,
        site_slot_hint="要建的控制台 / 工具台简述",
    )


def _website_qa_task(
    *,
    site: str,
    copy_files_qa: str,
    tone_qa: str,
    deferred_ok: bool,
) -> str:
    """Shared whole-page QA task book (build_website tail + build_website_verify)."""
    defer_line = (
        "（可与建站同波；若本回合预算不足可跳过，由下一回合续派本验收——"
        "区块自动检查仍在各分区落盘时执行）"
        if deferred_ok
        else "（本 playbook 专跑整页验收；工作区已有 site/ 产物，勿重做文案/骨架/整站）"
    )
    return (
        f"独立【整页验收】站点【{site}】{defer_line}："
        f"file_read 全部产物（"
        f"{copy_files_qa} / `{_BUILD_WEBSITE_DESIGN}` / `{_BUILD_WEBSITE_HTML}` / "
        f"`{_BUILD_WEBSITE_CSS}` / `{_BUILD_WEBSITE_JS}` / "
        f"`{_BUILD_WEBSITE_CONTRACT}`），核对 HTML↔CSS↔JS 接缝与交互方案一致性——"
        "契约列出的 class/id 均有实现、无挂空选择器；文案键已落地；"
        "实现色值 ⊆ DESIGN tokens；交互入口与契约一致。"
        f"{tone_qa}"
        "【接缝门禁】web_seam 静态门禁会拦挂空 class/id，验收时主动对照，"
        "勿留下死钩子。"
        "【视觉 QA·P1c】运行时在 web_quality hard 通过后自动多视口截图 → "
        "独立 VisionReader critic（对照 DESIGN.md + anti-slop）；"
        "有 critical findings 时至多 2 轮定向修补（str_replace/file_append）；"
        "无 browser_screenshot 或无 VisionReader 时产物明示『未目验』，"
        "【禁止】谎称视觉 QA 通过。"
        f"用 file_write 落盘 `{_BUILD_WEBSITE_QA}`："
        "通过项 / 缺陷 / 局限声明（含视觉是否目验）；只报告不重写整站"
        "（视觉 critic 回炉时除外：可按 findings 定向补丁）。"
    )


def _build_website_verify(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Second-act whole-page QA only — for qa_deferred_budget follow-up turns."""
    site = _clean_str(args.get("site"))
    if not site:
        return [], [
            "build_website_verify 需要 slot『site』（与建站时 site 简述一致，或写工作区站点名）"
        ]
    copy_files_qa = (
        f"`{_BUILD_WEBSITE_COPY}`（若存在）/ `{_BUILD_WEBSITE_COPY_A}` / "
        f"`{_BUILD_WEBSITE_COPY_B}`"
    )
    return [
        {
            "id": "qa",
            "role": "页面 QA",
            "task": _website_qa_task(
                site=site,
                copy_files_qa=copy_files_qa,
                tone_qa="",
                deferred_ok=False,
            ),
            "ceiling_priority": True,
            "deliverable": {
                "form": "files",
                "name": f"QA 报告（已落盘 {_BUILD_WEBSITE_QA}）",
                "artifacts": [_BUILD_WEBSITE_QA],
                "web_seam_scope": f"{_BUILD_WEBSITE_DIR}/",
                "placeholder_hard_exempt": True,
                "web_quality_scan": True,
                "visual_critic": True,
            },
            "timeout_ms": 300_000,
        }
    ], []


def _compare_options(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """N×并行评估各选项 → 汇总对比 + 推荐（依赖全部评估）.

    The decision-support shape: one evaluator per option (each stays objective on its own one),
    then a synthesiser produces the cross-option comparison the CEO relays.

    options 超过 ``MAX_PLAYBOOK_FANOUT`` 时显式拒绝（不折叠、不静默截断），引导 CEO 收敛短名单。
    """
    question = _clean_str(args.get("question"))
    options = _clean_str_list(args.get("options"), cap=None)
    errors: list[str] = []
    if not question:
        errors.append("compare_options 需要 slot『question』（要决策的问题）")
    if len(options) < 2:
        errors.append("compare_options 需要 slot『options』（>=2 个待比较选项）")
    elif len(options) > MAX_PLAYBOOK_FANOUT:
        errors.append(
            f"compare_options 的 options 共 {len(options)} 个，超过上限 "
            f"{MAX_PLAYBOOK_FANOUT}；请收敛为短名单后再试"
            "（本 playbook 不对选项做折叠或静默截断）。"
        )
    if errors:
        return [], errors
    criteria = _clean_str_list(args.get("criteria"), cap=8)
    crit_eval = ("，按这些维度评估：" + "、".join(criteria)) if criteria else ""
    crit_sum = (f"（维度：{'、'.join(criteria)}）") if criteria else ""

    eval_ids = [f"eval_{i}" for i in range(len(options))]
    tasks: list[dict[str, Any]] = []
    for eid, opt in zip(eval_ids, options, strict=True):
        tasks.append(
            {
                "id": eid,
                "role": "评估员",
                "task": (
                    f"针对决策问题【{question}】，深入评估这一个选项：{opt}{crit_eval}。"
                    "给出它的优点 / 缺点 / 适用与不适用场景，只评这一个、保持客观。"
                ),
                "deliverable": {"name": f"对选项【{opt}】的评估"},
            }
        )
    tasks.append(
        {
            "id": "summary",
            "role": "汇总分析师",
            "task": (
                f"对照上游对各选项的评估，针对【{question}】给出横向对比{crit_sum}："
                "一张对比表 + 明确推荐及理由；若各选项各有适用场景，说清分别何时选谁。"
            ),
            "depends_on": eval_ids,
            "deliverable": {"name": "对比表 + 推荐结论"},
        }
    )
    return tasks, []


def _organize_folder(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Single file-only worker for desktop organize (scan or apply)."""
    from agentcore.tools.builtin import file_only_tool_names

    task = _clean_str(args.get("task"))
    if not task:
        return [], ["organize_folder 需要 task（扫描或执行整理的具体说明）"]
    tools = sorted(file_only_tool_names())
    return (
        [
            {
                "id": "organizer",
                "role": "文件整理助手",
                "task": task,
                "tools": tools,
                "deliverable": {"form": "prose", "name": "整理结果报告"},
            }
        ],
        [],
    )


_DEFAULT_MULTI_LENSES = ("法律", "品牌商业", "舆情公关", "文化社会")

# 幕 1 案卷目录：各透镜报告 + 汇总与命题卡（多幕共享；辩论阶段将读这些文件）。
_MULTI_LENS_RESEARCH_DIR = RESEARCH_DIR
_SYNTHESIZER_ARTIFACT = f"{_MULTI_LENS_RESEARCH_DIR}/汇总与命题卡.md"


def _lens_report_artifact(lens: str) -> str:
    """Workspace-relative Chinese-readable path for one lens report."""
    return f"{_MULTI_LENS_RESEARCH_DIR}/{lens}透镜报告.md"


def _lens_report_artifact_for_parts(parts: list[str]) -> str:
    """Artifact path for a (possibly folded) lens slot — joined names when merged."""
    return _lens_report_artifact(" + ".join(parts))


def _lens_retrieval_division(lens: str, *, is_base_owner: bool) -> str:
    """Static retrieval-division pedagogy for one parallel lens task (no runtime deps).

    Lenses run in parallel and must not assume peer reports exist yet. Division is
    task-text only（职责分工）；检索额度走统一默认，playbook **不**再显式写入
    base/gap 两档 ``retrieval_budget``。

    Folded overflow always lands in the *last* slot (see ``_fold_fanout_slots``), so
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


# Mechanism-only key: inject turn ``user_message`` via ``expand_playbook(..., user_message=)``.
# Not a CEO-facing playbook slot — CEO must not be required to re-state the user line in topic.
_USER_MESSAGE_MECH_KEY = "__user_message__"
# Mechanism-only: conversation_id for website style ledger injection (build_website design node).
_CONVERSATION_ID_MECH_KEY = "_conversation_id"

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


def _user_request_anchor_block(user_message: str) -> str:
    """Mechanism block: full user line for synthesizer fidelity (empty → omit)."""
    um = _clean_str(user_message)
    if not um:
        return ""
    return (
        f"【用户原话·全文·机制注入】「{um}」——"
        "产卡时以这段原话为命题保真锚（不依赖上方 topic 摘要）；"
        "topic 仅为调研主题标签，不得覆盖原话中的对象与形态约束。"
    )


def _multi_lens_research(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """N×异质透镜并行调研 → 汇总分析师 depends_on 全部透镜做交叉验证（可产 motion_card）.

    Companion shape for ``deep_multi_lens_research`` skill: parallel heterogeneous lenses
    then a synthesizer that cross-checks and may suggest a debate motion — not a compare table.

    幕 1 产物以 ``form=files`` + ``artifacts`` 落盘 ``AgentCore/文档/research/``（各透镜自写报告 +
    汇总员写「汇总与命题卡」）。开工授权（delegation grant）覆盖整次委派的
    file_mutation 工具面，四路并行写文件不会额外弹授权卡；handoff / motion_card
    链路照旧，落盘是叠加。

    lenses 超过扇出上限时折叠进末节点（合并不丢弃），首透镜仍独占公共底料分工。
    """
    topic = _clean_str(args.get("topic"))
    if not topic:
        return [], ["multi_lens_research 需要 slot『topic』（要多视角调研的主题 / 事件）"]
    lenses_raw = _clean_str_list(args.get("lenses"), cap=None)
    if not lenses_raw:
        lenses_raw = list(_DEFAULT_MULTI_LENSES)
    lens_slots, lens_fold_note = _fold_fanout_slots(lenses_raw, label="透镜")
    fold_hint = f" {lens_fold_note}" if lens_fold_note else ""
    raw_um = args.get(_USER_MESSAGE_MECH_KEY)
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
                f"{_RESEARCHER_NOTE_GUIDANCE}"
                f"{fold_hint}"
            ),
            "deliverable": {
                "form": "files",
                "name": f"【{label}】透镜调研报告（已落盘 {artifact}）",
                "artifacts": [artifact],
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
            },
        }
    )
    return tasks, []


PLAYBOOKS: dict[str, Playbook] = {
    "research_report": Playbook(
        name="research_report",
        summary=(
            "调研→提纲→写作→审校的报告流水线（N 路并行调研，汇拢成纲再成文；"
            "成篇验收钉死单一主文件）"
        ),
        slots=(
            "topic(必填,主题) / angles(可选,调研子方向数组,各派一名调研员;"
            "超过扇出上限时末尾自动折叠到最后一节点并标注、不丢弃) / "
            "checkpoint(可选,成纲后写作前暂停过目,默认 true) / audience(可选,读者) / "
            "deliverable(可选,产出形态) / "
            "output_path(可选,成篇主文件路径,默认 AgentCore/文档/research/报告.md；验收只认此路径)"
        ),
        build=_research_report,
    ),
    "build_feature": Playbook(
        name="build_feature",
        summary="后端接口→（前端页面 ‖ 测试）并行的功能交付（接口契约经便签墙对齐）",
        slots=(
            "feature(必填,要实现的功能) / stack(可选,技术栈) / "
            "include(可选,['ui','test'] 子集,默认两者都要)"
        ),
        build=_build_feature,
    ),
    "build_website": Playbook(
        name="build_website",
        summary=(
            "文案→设计契约(DESIGN.md)→骨架+契约→N×分区独立片段→assemble组装→独立 QA"
            "（五波+组装不可减；禁单 worker 包整站；分区禁并行写同 index；营销 pack）"
        ),
        slots=(
            "site(必填,要建的站点/落地页简述——delegate 时填入 playbook 的 site 参数, "
            "例:site=\"面向企业客户的智能数据分析 SaaS 中文营销官网\") / "
            "sections(可选,页面分区数组;"
            "N≤3 各派一名实现,N≥4 相邻两段一组后再按宽≤2 折叠;"
            "文案恒单 worker;"
            "默认首屏英雄区·卖点能力区·行动号召区) / "
            "stack(可选,技术栈) / audience(可选,访客/读者)"
        ),
        build=_build_website,
    ),
    "build_toolshed": Playbook(
        name="build_toolshed",
        summary=(
            "文案→设计契约(DESIGN.md)→骨架+契约→N×分区独立片段→assemble组装→独立 QA"
            "（同流水线；强制 pack=tool_dense；anti-slop domain=tool；禁营销 hero/pricing 皮）"
        ),
        slots=(
            "site(必填,要建的控制台/工具台简述——"
            "例:site=\"面向运营的订单管理后台 dense 控制台\") / "
            "sections(可选,页面分区数组;合并规则同 build_website;"
            "默认应用外壳·侧栏导航·数据表格) / "
            "stack(可选,技术栈) / audience(可选,使用者)"
        ),
        build=_build_toolshed,
    ),
    "build_website_verify": Playbook(
        name="build_website_verify",
        summary=(
            "第二段整页/视觉验收（qa_deferred_budget 续派）：只跑 QA，要求已有 site/；"
            "勿重建文案/骨架/分区"
        ),
        slots=(
            "site(必填,与建站时 site 简述一致或写工作区站点名——"
            "例:site=\"面向企业客户的智能数据分析 SaaS 中文营销官网\")"
        ),
        build=_build_website_verify,
    ),
    "compare_options": Playbook(
        name="compare_options",
        summary="N 路并行评估各选项→汇总对比推荐的决策支持",
        slots=(
            "question(必填,要决策的问题) / options(必填,>=2 且≤扇出上限个待比较选项;"
            "超上限显式拒绝、不折叠不截断) / "
            "criteria(可选,评估维度数组)"
        ),
        build=_compare_options,
    ),
    "organize_folder": Playbook(
        name="organize_folder",
        summary="桌面整理单 worker：只装配文件工具（无 code_execute/terminal）",
        slots="task(必填,扫描或执行整理的具体说明)",
        build=_organize_folder,
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
        build=_multi_lens_research,
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
    um = _clean_str(user_message)
    if um:
        slot_args[_USER_MESSAGE_MECH_KEY] = um
    cid = _clean_str(conversation_id)
    if cid:
        slot_args[_CONVERSATION_ID_MECH_KEY] = cid
    return pb.build(slot_args)

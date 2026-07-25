"""拆·playbook 固化 (§2.1) — the playbook registry + expansion.

Covers each固化形状's slot validation + emitted DAG shape, the registry's reject paths
(unknown name / bad args / missing required slot), and — most importantly — that every
expanded ``tasks`` list is actually runnable: it round-trips through the REAL
``build_run_plan`` with no errors, so an emitted id / depends_on mismatch can't slip through.
"""

from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.playbooks import (
    PLAYBOOKS,
    available_playbooks,
    expand_playbook,
)


def _roles(tasks: list[dict]) -> list[str]:
    return [t["role"] for t in tasks]


def _by_id(tasks: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in tasks}


# ── research_report ───────────────────────────────────────────────────────────


def test_research_report_fans_out_one_researcher_per_angle_then_outline_then_write():
    tasks, errors = expand_playbook(
        "research_report",
        {"topic": "向量数据库", "angles": ["原理", "选型", "成本"], "checkpoint": True},
    )
    assert errors == []
    by_id = _by_id(tasks)
    # one 调研员 per angle, then 提纲(依赖全部调研), then 写作(依赖提纲).
    research_ids = [f"research_{i}" for i in range(3)]
    assert all(rid in by_id for rid in research_ids)
    assert set(by_id["outline"]["depends_on"]) == set(research_ids)
    assert by_id["write"]["depends_on"] == ["outline"]
    assert by_id["review"]["depends_on"] == ["write"]
    assert by_id["review"]["role"] == "学术审校员"
    # 审校节点显式墙钟 300s（CEO 显式 timeout_ms 恒优先于统一 backstop）。
    assert by_id["review"]["timeout_ms"] == 300_000
    # checkpoint flag rides the 提纲 step (成纲后写作前过目); the write step requires file landing.
    assert by_id["outline"]["checkpoint_after"] is True
    assert by_id["write"]["deliverable"]["requires_files"] is True
    assert by_id["write"]["deliverable"]["form"] == "files"
    assert by_id["write"]["deliverable"]["artifacts"] == ["research/报告.md"]
    assert "单主文件" in by_id["write"]["task"]
    assert "research/报告.md" in by_id["write"]["task"]
    assert "research/报告.md" in by_id["review"]["task"]
    # Artifact-first writer brief: skeleton first; ban half-chapter prose then append.
    write_task = by_id["write"]["task"]
    assert "短骨架" in write_task or "首写必须是短骨架" in write_task
    assert "禁止首写半章散文" in write_task
    assert "artifact manifest" in write_task or "禁止再对本文件" in write_task
    assert "file_read" in write_task
    # each angle is named into its researcher's task so the fan-out doesn't run blind/overlapping.
    assert "选型" in by_id["research_1"]["task"]
    assert "read_notes" in by_id["research_1"]["task"]
    assert "post_note" in by_id["research_1"]["task"]
    # 引用即出处 P3：调研员成稿主张须证（#rN 或待核实）。
    assert "#rN" in by_id["research_1"]["task"]
    assert "待核实" in by_id["research_1"]["task"]
    # 深读姿态：关键法条 / 司法解释 / 判例须 read_url 核对原文。
    assert "read_url" in by_id["research_1"]["task"]
    assert "法条" in by_id["research_1"]["task"]
    assert "read_url" in by_id["review"]["task"]
    assert "法条" in by_id["review"]["task"]
    # 审校工具面含定向检索 + 检索纪律（勿退化成只 file_list/file_read）。
    review_tools = by_id["review"]["tools"]
    assert "grep" in review_tools
    assert "code_search" in review_tools
    assert "file_read" in review_tools
    assert "检索纪律" in by_id["review"]["task"]
    assert "grep" in by_id["review"]["task"]
    assert "code_search" in by_id["review"]["task"]
    assert "整目录" in by_id["review"]["task"]


def test_research_report_without_angles_uses_single_researcher():
    tasks, errors = expand_playbook("research_report", {"topic": "X"})
    assert errors == []
    by_id = _by_id(tasks)
    assert by_id["outline"]["depends_on"] == ["research_0"]
    assert by_id["outline"]["checkpoint_after"] is True  # default: checkpoint on outline
    assert by_id["review"]["depends_on"] == ["write"]
    # 单调研员路径同样钉住主张须证教法。
    assert "#rN" in by_id["research_0"]["task"]
    assert "待核实" in by_id["research_0"]["task"]


def test_research_report_output_path_overrides_main_artifact():
    tasks, errors = expand_playbook(
        "research_report",
        {"topic": "T", "output_path": "paper/main.md"},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert by_id["write"]["deliverable"]["artifacts"] == ["paper/main.md"]
    assert "paper/main.md" in by_id["write"]["task"]
    assert "paper/main.md" in by_id["review"]["task"]


def test_research_report_checkpoint_can_be_disabled():
    tasks, errors = expand_playbook("research_report", {"topic": "X", "checkpoint": False})
    assert errors == []
    assert _by_id(tasks)["outline"]["checkpoint_after"] is False


def test_research_report_review_explicit_wall_clock_survives_build():
    """审校节点显式 timeout_ms=300000 经真实 builder 落成 policy.timeout_s=300；
    token 顶走统一 backstop（200k）。"""
    from agentcore.runtime.runs.worker_budget import WORKER_TIMEOUT_BACKSTOP_S

    tasks, errors = expand_playbook(
        "research_report", {"topic": "T", "angles": ["a", "b"]}
    )
    assert errors == []
    assert _by_id(tasks)["review"]["timeout_ms"] == 300_000
    plan, plan_errors = build_run_plan(tasks, id_prefix="pb_rr_review_to")
    assert plan_errors == []
    by_role = {n.role: n for n in plan.nodes}
    # review 有上游；墙钟显式 300s；token 顶走统一 backstop。
    assert by_role["学术审校员"].policy.timeout_s == 300
    assert by_role["学术审校员"].token_ceiling == 600_000
    # 提纲同为依赖上游的 prose 节点、未显式声明 → 统一 backstop 600s / 200k。
    assert by_role["提纲编辑"].policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S
    assert by_role["提纲编辑"].token_ceiling == 600_000


def test_research_report_requires_topic():
    tasks, errors = expand_playbook("research_report", {})
    assert tasks == []
    assert errors and "topic" in errors[0]


def test_research_report_folds_angle_fanout_with_note():
    """angles 超扇出上限：折叠进末节点（合并不丢弃），带 playbook_note。"""
    from agentcore.runtime.runs.playbooks import MAX_PLAYBOOK_FANOUT, collect_playbook_notes

    n = MAX_PLAYBOOK_FANOUT + 5
    tasks, errors = expand_playbook(
        "research_report", {"topic": "X", "angles": [f"a{i}" for i in range(n)]}
    )
    assert errors == []
    researchers = [t for t in tasks if t["role"] == "调研员"]
    assert len(researchers) == MAX_PLAYBOOK_FANOUT
    last = researchers[-1]
    # Tail angles folded into last researcher (not silently dropped).
    for i in range(MAX_PLAYBOOK_FANOUT - 1, n):
        assert f"a{i}" in last["task"] or f"a{i}" in last["deliverable"]["name"]
    notes = collect_playbook_notes(tasks)
    assert notes and "扇出折叠" in notes[0]
    assert f"a{MAX_PLAYBOOK_FANOUT}" in notes[0]


# ── build_feature ─────────────────────────────────────────────────────────────


def test_build_feature_defaults_to_api_plus_parallel_ui_and_test():
    tasks, errors = expand_playbook("build_feature", {"feature": "用户登录", "stack": "FastAPI+React"})
    assert errors == []
    by_id = _by_id(tasks)
    assert set(by_id) == {"api", "ui", "test"}
    # ui & test both fan out from api (share its dep set → parallel siblings on the same seam).
    assert by_id["ui"]["depends_on"] == ["api"]
    assert by_id["test"]["depends_on"] == ["api"]
    # the api task tells the worker to broadcast its interface contract on the note wall (4b 对账 hook).
    assert "post_note" in by_id["api"]["task"]
    assert "FastAPI+React" in by_id["api"]["task"]


def test_build_feature_include_filters_steps():
    tasks, _ = expand_playbook("build_feature", {"feature": "X", "include": ["ui"]})
    assert set(_by_id(tasks)) == {"api", "ui"}
    tasks, _ = expand_playbook("build_feature", {"feature": "X", "include": ["test"]})
    assert set(_by_id(tasks)) == {"api", "test"}


def test_build_feature_requires_feature():
    tasks, errors = expand_playbook("build_feature", {})
    assert tasks == []
    assert errors and "feature" in errors[0]


# ── build_website ─────────────────────────────────────────────────────────────


def test_build_website_five_waves_default_sections():
    tasks, errors = expand_playbook(
        "build_website",
        {"site": "GEO 官网落地页", "stack": "静态 HTML", "audience": "中小商家"},
    )
    assert errors == []
    by_id = _by_id(tasks)
    section_ids = [f"section_{i}" for i in range(3)]
    assert set(by_id) == {"copy", "design", "skeleton", *section_ids, "assemble", "qa"}
    assert by_id["design"]["depends_on"] == ["copy"]
    assert by_id["skeleton"]["depends_on"] == ["design"]
    assert by_id["design"]["deliverable"]["artifacts"] == ["site/DESIGN.md"]
    assert "site/DESIGN.md" in by_id["design"]["task"] or "DESIGN" in by_id["design"]["task"]
    assert "DESIGN" in by_id["skeleton"]["task"] or "site/DESIGN.md" in by_id["skeleton"]["task"]
    assert "DESIGN" in by_id["section_0"]["task"] or "site/DESIGN.md" in by_id["section_0"]["task"]
    for sid in section_ids:
        assert by_id[sid]["depends_on"] == ["skeleton"]
    assert by_id["assemble"]["depends_on"] == section_ids
    assert by_id["qa"]["depends_on"] == ["assemble"]
    # 全节点 form=files + 约定路径
    assert by_id["copy"]["deliverable"]["form"] == "files"
    assert by_id["copy"]["deliverable"]["artifacts"] == ["site/copy.md"]
    assert by_id["copy"]["deliverable"].get("strict") is True
    assert "品牌一句话" in by_id["copy"]["deliverable"]["required_sections"]
    assert by_id["copy"]["deliverable"].get("must_contain_soft") is True
    assert "visual thesis" in by_id["copy"]["task"]
    assert "anti-slop" in by_id["copy"]["task"]
    assert by_id["skeleton"]["deliverable"].get("web_quality_scan") is True
    assert by_id["skeleton"]["deliverable"].get("web_quality_soft_exempt") is True
    assert by_id["skeleton"]["deliverable"].get("strict") is True
    assert by_id["section_0"]["deliverable"].get("web_quality_scan") is True
    assert by_id["section_0"]["deliverable"].get("strict") is True
    assert by_id["section_0"]["deliverable"]["artifacts"] == ["site/sections/s0.html"]
    assert by_id["assemble"]["deliverable"]["artifacts"] == [
        "site/index.html",
        "site/styles.css",
        "site/main.js",
    ]
    assert by_id["assemble"]["deliverable"].get("strict") is True
    assert by_id["qa"]["deliverable"].get("web_quality_scan") is True
    assert by_id["qa"]["deliverable"].get("visual_critic") is True
    assert by_id["qa"]["deliverable"].get("strict") is True
    assert by_id["qa"].get("ceiling_priority") is True
    # Wave3 D：assemble+QA 均 ceiling_priority，交付预留窗口保验收路径
    assert by_id["assemble"].get("ceiling_priority") is True
    # Wave3 B：分区强制注入契约/设计/文案摘要路径 + 少空转读纪律
    assert by_id["section_0"].get("context_inject_files") == [
        "site/CONTRACT.md",
        "site/DESIGN.md",
        "site/copy.md",
    ]
    assert "分区上下文预算" in by_id["section_0"]["task"]
    assert "禁止" in by_id["section_0"]["task"] and "反复 file_read" in by_id["section_0"]["task"]
    assert "写前确认" in by_id["section_0"]["task"]
    assert by_id["skeleton"]["deliverable"]["form"] == "files"
    assert "site/CONTRACT.md" in by_id["skeleton"]["deliverable"]["artifacts"]
    assert "site/index.html" in by_id["skeleton"]["deliverable"]["artifacts"]
    assert by_id["qa"]["deliverable"]["form"] == "files"
    assert by_id["qa"]["deliverable"]["artifacts"] == ["site/QA.md"]
    assert by_id["qa"]["deliverable"]["web_seam_scope"] == "site/"
    # 文案 / 栈 / 受众嵌入任务书
    assert "GEO 官网落地页" in by_id["copy"]["task"]
    assert "中小商家" in by_id["copy"]["task"]
    assert "静态 HTML" in by_id["skeleton"]["task"]
    # Wave3 A：分区只写独立片段；assemble 单写者注入；QA 接缝 / 截图诚实
    assert "site/sections/s0.html" in by_id["section_0"]["task"]
    assert "分区独立片段" in by_id["section_0"]["task"]
    assert "site/index.html" in by_id["section_0"]["task"]  # forbid mention
    assert "禁止" in by_id["section_0"]["task"]
    assert "write_section" in by_id["assemble"]["task"]
    assert "str_replace" in by_id["assemble"]["task"]  # forbidden for placeholder guess
    assert "site/sections/s0.html" in by_id["assemble"]["task"]
    assert "web_seam" in by_id["qa"]["task"]
    assert "browser_screenshot" in by_id["qa"]["task"]
    assert "未目验" in by_id["qa"]["task"] or "谎称" in by_id["qa"]["task"]
    assert by_id["qa"]["timeout_ms"] == 300_000
    # 默认三分区角色名
    assert by_id["section_0"]["role"] == "首屏英雄区实现"
    assert by_id["section_1"]["role"] == "卖点能力区实现"
    assert by_id["section_2"]["role"] == "行动号召区实现"
    # 骨架埋 SECTION 标记对；分区写片段；assemble 注入
    assert "SECTION" in by_id["skeleton"]["task"]
    assert "SECTION:s0 START" in by_id["skeleton"]["task"]
    assert "SECTION:s0 START" in by_id["assemble"]["task"]
    # 三分区 artifacts 互不交叉（并行不撞同文件）
    arts = [tuple(by_id[sid]["deliverable"]["artifacts"]) for sid in section_ids]
    assert len(arts) == len(set(arts))
    assert all("site/index.html" not in a for a in arts)
    # 内部协调产物占位符硬扫豁免
    assert by_id["skeleton"]["deliverable"]["placeholder_hard_exempt_artifacts"] == [
        "site/CONTRACT.md",
        "site/DESIGN.md",
    ]
    assert by_id["qa"]["deliverable"]["placeholder_hard_exempt"] is True


# Back-compat name used by older docs / external refs.
test_build_website_four_waves_default_sections = test_build_website_five_waves_default_sections


def test_build_website_section_marker_guidance_per_slot():
    """Merged section slots list every constituent fragment path."""
    tasks, _ = expand_playbook(
        "build_website",
        {"site": "S", "sections": ["导航", "定价", "FAQ"]},
    )
    by_id = _by_id(tasks)
    # N=3 → 1:1; section_1 is 定价 alone → s1 fragment only
    assert "site/sections/s1.html" in by_id["section_1"]["task"]
    assert "【定价】" in by_id["section_1"]["task"]
    assert by_id["section_1"]["deliverable"]["artifacts"] == ["site/sections/s1.html"]
    # N=8 merge: section_0 covers 区0+区1 → s0 and s1 fragments
    eight = [f"区{i}" for i in range(8)]
    tasks8, _ = expand_playbook("build_website", {"site": "S", "sections": eight})
    by_id8 = _by_id(tasks8)
    assert "site/sections/s0.html" in by_id8["section_0"]["task"]
    assert "site/sections/s1.html" in by_id8["section_0"]["task"]
    assert by_id8["section_0"]["deliverable"]["artifacts"] == [
        "site/sections/s0.html",
        "site/sections/s1.html",
    ]


def test_build_website_n3_unchanged_single_copy():
    """N=3：1:1 分区、单文案 worker、无合并 note；含 assemble。"""
    from agentcore.runtime.runs.playbooks import collect_playbook_notes

    sections = ["首屏英雄区", "卖点能力区", "行动号召区"]
    tasks, errors = expand_playbook(
        "build_website",
        {"site": "S", "sections": sections, "audience": "访客"},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert set(by_id) == {
        "copy",
        "design",
        "skeleton",
        "section_0",
        "section_1",
        "section_2",
        "assemble",
        "qa",
    }
    assert by_id["design"]["depends_on"] == ["copy"]
    assert by_id["skeleton"]["depends_on"] == ["design"]
    assert by_id["copy"]["deliverable"]["artifacts"] == ["site/copy.md"]
    assert "site/copy/" not in by_id["copy"]["task"]
    assert collect_playbook_notes(tasks) == []
    assert by_id["section_0"]["role"] == "首屏英雄区实现"
    assert "site/copy.md" in by_id["section_0"]["task"]
    assert "跨段口吻一致性" not in by_id["qa"]["task"]
    assert by_id["qa"]["depends_on"] == ["assemble"]


def test_build_website_n8_pairs_then_width2_single_copy():
    """N=8 → 相邻配对后再按 width=2 折叠为 2 分区节点；单文案；带 note。"""
    from agentcore.runtime.runs.playbooks import collect_playbook_notes

    eight = [
        "首屏英雄区",
        "卖点能力区",
        "案例证明区",
        "定价方案区",
        "信任背书区",
        "对比表区",
        "常见 FAQ",
        "底部 CTA + 联系表单区",
    ]
    tasks, errors = expand_playbook(
        "build_website",
        {"site": "S", "sections": eight, "audience": "中小商家"},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert "copy_a" not in by_id and "copy_b" not in by_id
    assert set(by_id) >= {"copy", "design", "skeleton", "assemble", "qa"}
    section_nodes = [t for t in tasks if t["id"].startswith("section_")]
    assert len(section_nodes) == 2
    assert by_id["design"]["depends_on"] == ["copy"]
    assert by_id["skeleton"]["depends_on"] == ["design"]
    assert by_id["copy"]["deliverable"]["artifacts"] == ["site/copy.md"]
    assert "中小商家" in by_id["copy"]["task"]
    assert "site/DESIGN.md" in by_id["skeleton"]["task"] or "DESIGN" in by_id["skeleton"]["task"]
    assert "site/copy.md" in by_id["qa"]["task"]
    assert "跨段口吻一致性" not in by_id["qa"]["task"]
    # 所有分区节点读同一文案包
    assert "site/copy.md" in by_id["section_0"]["task"]
    assert "site/copy.md" in by_id["section_1"]["task"]
    # width=2 折叠：首节点保留首对，末节点吞尾
    assert "首屏英雄区" in by_id["section_0"]["role"] and "卖点能力区" in by_id["section_0"]["role"]
    assert "常见 FAQ" in by_id["section_1"]["role"] or "常见 FAQ" in by_id["section_1"]["task"]
    assert (
        "底部 CTA + 联系表单区" in by_id["section_1"]["role"]
        or "底部 CTA + 联系表单区" in by_id["section_1"]["task"]
    )
    assert "分区独立片段" in by_id["section_0"]["task"]
    assert "site/index.html" not in by_id["section_0"]["deliverable"]["artifacts"]
    assert by_id["assemble"]["depends_on"] == ["section_0", "section_1"]
    notes = collect_playbook_notes(tasks)
    assert notes and "分区合并" in notes[0]
    assert "宽度上限" in notes[0] or "折叠" in notes[0]
    assert "首屏英雄区" in by_id["copy"]["task"]
    assert "底部 CTA + 联系表单区" in by_id["copy"]["task"]
    assert "常见 FAQ" in by_id["skeleton"]["task"]


def test_build_website_n13_width2_capped_with_tail_fold():
    """N=13 → 配对后宽度封顶 2，尾部折叠进末组；单文案。"""
    from agentcore.runtime.runs.playbooks import (
        _BUILD_WEBSITE_SECTION_MAX_WIDTH,
        collect_playbook_notes,
    )

    thirteen = [f"区{i}" for i in range(13)]
    tasks, errors = expand_playbook(
        "build_website", {"site": "S", "sections": thirteen}
    )
    assert errors == []
    section_nodes = [t for t in tasks if t["id"].startswith("section_")]
    assert len(section_nodes) == _BUILD_WEBSITE_SECTION_MAX_WIDTH
    by_id = _by_id(tasks)
    last = by_id[f"section_{_BUILD_WEBSITE_SECTION_MAX_WIDTH - 1}"]
    # Pair-then-fold: last group absorbs the odd 13th + its pair mate(s).
    assert "区12" in last["role"] or "区12" in last["task"]
    assert "区10" in last["role"] or "区10" in last["task"]
    notes = collect_playbook_notes(tasks)
    assert notes and "分区合并" in notes[0]
    assert "宽度上限" in notes[0] or "折叠" in notes[0]
    assert "copy" in by_id
    assert "copy_a" not in by_id and "copy_b" not in by_id
    assert by_id["design"]["depends_on"] == ["copy"]
    assert by_id["skeleton"]["depends_on"] == ["design"]
    assert "assemble" in by_id
    assert by_id["qa"]["depends_on"] == ["assemble"]
    # 全局 MAX_PLAYBOOK_FANOUT 仍为 6（调研/compare）；建站分区宽独立为 2
    from agentcore.runtime.runs.playbooks import MAX_PLAYBOOK_FANOUT

    assert MAX_PLAYBOOK_FANOUT == 6
    assert _BUILD_WEBSITE_SECTION_MAX_WIDTH == 2
    assert len(section_nodes) < MAX_PLAYBOOK_FANOUT

def test_build_website_custom_sections_small_no_merge():
    from agentcore.runtime.runs.playbooks import collect_playbook_notes

    tasks, errors = expand_playbook(
        "build_website",
        {"site": "S", "sections": ["导航", "定价"]},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert by_id["assemble"]["depends_on"] == ["section_0", "section_1"]
    assert by_id["qa"]["depends_on"] == ["assemble"]
    assert by_id["section_1"]["role"] == "定价实现"
    assert "定价" in by_id["section_1"]["task"]
    assert collect_playbook_notes(tasks) == []
    assert by_id["copy"]["deliverable"]["artifacts"] == ["site/copy.md"]


def test_build_website_partition_artifacts_disjoint():
    """验收 A：三分区并行 artifacts 互不交叉，且均不含共享 index.html。"""
    tasks, errors = expand_playbook(
        "build_website",
        {"site": "S", "sections": ["首屏英雄区", "卖点能力区", "行动号召区"]},
    )
    assert errors == []
    by_id = _by_id(tasks)
    section_arts = [
        set(by_id[f"section_{i}"]["deliverable"]["artifacts"]) for i in range(3)
    ]
    for arts in section_arts:
        assert arts
        assert "site/index.html" not in arts
        assert all(p.startswith("site/sections/") for p in arts)
    # pairwise disjoint
    assert not (section_arts[0] & section_arts[1])
    assert not (section_arts[0] & section_arts[2])
    assert not (section_arts[1] & section_arts[2])
    assert by_id["assemble"]["depends_on"] == ["section_0", "section_1", "section_2"]


def test_build_website_requires_site():
    tasks, errors = expand_playbook("build_website", {})
    assert tasks == []
    assert errors and "site" in errors[0]


def test_build_toolshed_five_waves_injects_tool_dense():
    """build_toolshed mirrors website waves; forces tool_dense + domain=tool."""
    from agentcore.runtime.runs.website_catalog import (
        PACK_TOOL_DENSE,
        TOOL_DENSE_POINTER_PREFIX,
    )

    tasks, errors = expand_playbook(
        "build_toolshed",
        {"site": "订单运营控制台", "sections": ["应用外壳", "侧栏导航", "数据表格"]},
    )
    assert errors == []
    by_id = {t["id"]: t for t in tasks}
    assert set(by_id) >= {
        "copy",
        "design",
        "skeleton",
        "section_0",
        "section_1",
        "section_2",
        "assemble",
        "qa",
    }
    assert by_id["qa"]["depends_on"] == ["assemble"]
    assert by_id["assemble"]["depends_on"] == ["section_0", "section_1", "section_2"]
    sk = by_id["skeleton"]["task"]
    assert f"pack={PACK_TOOL_DENSE}" in sk
    assert "catalog:app_shell" in sk
    assert f"{TOOL_DENSE_POINTER_PREFIX}/app_shell.html" in sk
    assert "catalog:sidebar" in sk
    assert "catalog:data_table" in sk
    assert "审美域·工具页" in by_id["copy"]["task"]
    assert "hero" not in sk.lower() or "禁营销" in sk or "禁止" in sk
    assert "website_catalog/marketing/" not in sk
    s0 = by_id["section_0"]["task"]
    assert "catalog:app_shell" in s0
    assert TOOL_DENSE_POINTER_PREFIX in s0
    assert "site/sections/s0.html" in s0
    assert "site/index.html" not in by_id["section_0"]["deliverable"]["artifacts"]


def test_build_toolshed_requires_site():
    tasks, errors = expand_playbook("build_toolshed", {})
    assert tasks == []
    assert errors and "site" in errors[0]
    assert "build_toolshed" in errors[0]


def test_build_website_verify_qa_only_no_rebuild():
    """Second-act verify: single QA node, deferred_ok=False, requires site."""
    tasks, errors = expand_playbook("build_website_verify", {"site": "GEO 官网"})
    assert errors == []
    assert len(tasks) == 1
    qa = tasks[0]
    assert qa["id"] == "qa"
    assert qa.get("depends_on") in (None, [], ())
    assert "勿重做文案" in qa["task"] or "勿重做" in qa["task"]
    assert "预算不足可跳过" not in qa["task"]
    assert qa["deliverable"]["artifacts"] == ["site/QA.md"]
    assert qa["deliverable"].get("visual_critic") is True
    assert qa.get("ceiling_priority") is True

    empty, err = expand_playbook("build_website_verify", {})
    assert empty == []
    assert err and "site" in err[0]


def test_build_website_qa_shares_helper_deferred_ok():
    tasks, _ = expand_playbook("build_website", {"site": "S", "sections": ["A"]})
    qa = next(t for t in tasks if t["id"] == "qa")
    assert "预算不足可跳过" in qa["task"]
    assert "站点【S】" in qa["task"]


def test_build_website_files_form_builds_run_plan():
    """form=files + artifacts 经真实 builder 接通；五波次 DAG 可 waves()。"""
    tasks, errors = expand_playbook(
        "build_website", {"site": "T", "sections": ["A", "B"]}
    )
    assert errors == []
    plan, plan_errors = build_run_plan(tasks, id_prefix="pb_bw")
    assert plan_errors == []
    assert len(plan.nodes) == 7  # copy + design + skeleton + 2 sections + assemble + qa
    waves = plan.waves()
    assert waves  # no cycle
    by_role = {n.role: n for n in plan.nodes}
    assert by_role["内容文案"].deliverable is not None
    assert by_role["内容文案"].deliverable.form == "files"
    assert by_role["内容文案"].deliverable.requires_files is True
    assert by_role["内容文案"].deliverable.strict is True
    assert by_role["设计契约"].deliverable.artifacts == ["site/DESIGN.md"]
    assert by_role["骨架工程师"].deliverable.artifacts is not None
    assert "site/CONTRACT.md" in by_role["骨架工程师"].deliverable.artifacts
    assert by_role["骨架工程师"].deliverable.placeholder_hard_exempt_artifacts == [
        "site/CONTRACT.md",
        "site/DESIGN.md",
    ]
    assert by_role["页面组装"].deliverable.artifacts is not None
    assert "site/index.html" in by_role["页面组装"].deliverable.artifacts
    assert by_role["页面 QA"].deliverable.form == "files"
    assert by_role["页面 QA"].deliverable.placeholder_hard_exempt is True
    assert by_role["页面 QA"].policy.timeout_s == 300
    assert by_role["页面 QA"].ceiling_priority is True
    assert by_role["页面组装"].ceiling_priority is True
    section_nodes = [n for n in plan.nodes if "实现" in (n.role or "")]
    assert section_nodes
    assert section_nodes[0].context_inject_files == [
        "site/CONTRACT.md",
        "site/DESIGN.md",
        "site/copy.md",
    ]


def test_build_website_single_copy_builds_run_plan():
    """单文案 + width=2 分区经真实 builder 接通。"""
    eight = [f"区{i}" for i in range(8)]
    tasks, errors = expand_playbook("build_website", {"site": "T", "sections": eight})
    assert errors == []
    plan, plan_errors = build_run_plan(tasks, id_prefix="pb_bw8")
    assert plan_errors == []
    # copy + design + skeleton + 2 sections + assemble + qa = 7
    assert len(plan.nodes) == 7
    assert plan.waves()
    by_role = {n.role: n for n in plan.nodes}
    assert by_role["内容文案"].deliverable.artifacts == ["site/copy.md"]
    assert "内容文案·前半" not in by_role and "内容文案·后半" not in by_role
    assert by_role["设计契约"].deliverable.artifacts == ["site/DESIGN.md"]
    assert "页面组装" in by_role
    section_nodes = [n for n in plan.nodes if "实现" in (n.role or "")]
    assert len(section_nodes) == 2


# ── compare_options ───────────────────────────────────────────────────────────


def test_compare_options_evaluates_each_then_summarises():
    tasks, errors = expand_playbook(
        "compare_options",
        {"question": "选 Postgres 还是 MySQL", "options": ["Postgres", "MySQL"], "criteria": ["性能", "生态"]},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert {"eval_0", "eval_1", "summary"} == set(by_id)
    assert set(by_id["summary"]["depends_on"]) == {"eval_0", "eval_1"}
    # each evaluator is pinned to ONE option and carries the criteria.
    assert "Postgres" in by_id["eval_0"]["task"] and "性能" in by_id["eval_0"]["task"]


def test_compare_options_requires_question_and_two_options():
    _, errors = expand_playbook("compare_options", {"options": ["only-one"]})
    joined = "；".join(errors)
    assert "question" in joined and "options" in joined


def test_compare_options_rejects_over_fanout():
    """options>6：显式拒绝，不折叠、不静默截断。"""
    from agentcore.runtime.runs.playbooks import MAX_PLAYBOOK_FANOUT

    opts = [f"opt{i}" for i in range(MAX_PLAYBOOK_FANOUT + 1)]
    tasks, errors = expand_playbook(
        "compare_options", {"question": "Q", "options": opts}
    )
    assert tasks == []
    assert errors and "上限" in errors[0]
    assert "短名单" in errors[0] or "收敛" in errors[0]
    assert str(MAX_PLAYBOOK_FANOUT + 1) in errors[0] or str(len(opts)) in errors[0]
    # Exactly at cap still works.
    tasks_ok, errors_ok = expand_playbook(
        "compare_options",
        {"question": "Q", "options": [f"opt{i}" for i in range(MAX_PLAYBOOK_FANOUT)]},
    )
    assert errors_ok == []
    assert len([t for t in tasks_ok if t["id"].startswith("eval_")]) == MAX_PLAYBOOK_FANOUT


# ── multi_lens_research ───────────────────────────────────────────────────────


def test_multi_lens_research_default_four_lenses_plus_synthesizer():
    tasks, errors = expand_playbook(
        "multi_lens_research", {"topic": "LV 诉茉莉奶白商标案"}
    )
    assert errors == []
    by_id = _by_id(tasks)
    lens_ids = [f"lens_{i}" for i in range(4)]
    assert set(by_id) == {*lens_ids, "synthesizer"}
    assert set(by_id["synthesizer"]["depends_on"]) == set(lens_ids)
    assert by_id["synthesizer"]["role"] == "汇总分析师"
    # 默认四异质透镜角色名嵌入 role
    roles = {by_id[lid]["role"] for lid in lens_ids}
    assert roles == {"法律视角", "品牌商业视角", "舆情公关视角", "文化社会视角"}
    # 幕 1 案卷：各透镜自写 research/{透镜}透镜报告.md（form=files + artifacts）
    expected_lens_artifacts = {
        "research/法律透镜报告.md",
        "research/品牌商业透镜报告.md",
        "research/舆情公关透镜报告.md",
        "research/文化社会透镜报告.md",
    }
    for lid in lens_ids:
        d = by_id[lid]["deliverable"]
        assert d["form"] == "files"
        assert d["artifacts"] and d["artifacts"][0] in expected_lens_artifacts
        assert "file_write" in by_id[lid]["task"]
        assert d["artifacts"][0] in by_id[lid]["task"]
        assert "完整" in by_id[lid]["task"]  # 完整报告，非摘要复制
        assert "handoff" in by_id[lid]["task"]  # 落盘叠加，不得替代 handoff
        # 引用即出处 P3：透镜成稿主张须证（#rN 或待核实；不强迫辩词二分）。
        assert "#rN" in by_id[lid]["task"] or "#r1" in by_id[lid]["task"]
        assert "待核实" in by_id[lid]["task"]
        assert "不强迫" in by_id[lid]["task"]
    # 汇总员落盘汇总与命题卡；motion_card 仍走 handoff
    synth_d = by_id["synthesizer"]["deliverable"]
    assert synth_d["form"] == "files"
    assert synth_d["artifacts"] == ["research/汇总与命题卡.md"]
    synth_task = by_id["synthesizer"]["task"]
    assert "research/汇总与命题卡.md" in synth_task
    assert "file_write" in synth_task
    assert "motion_card" in synth_task
    assert "handoff" in synth_task
    assert "继续调研" in synth_task or "对抗" in synth_task
    assert "见分歧" in synth_task
    # 存在真对立轴则必须产卡（升格条款）
    assert "真对立轴" in synth_task
    assert "必须" in synth_task and "motion_card" in synth_task
    # 结构化字段唯一载体：禁止正文表 / 散文 / 自写 Followups 冒充
    assert "对象" in synth_task or "结构化" in synth_task
    assert "Followups" in synth_task or "芯片" in synth_task
    # 命题保真教法：锚定对象/形态；模拟法庭=本案对抗；禁抬制度层
    assert "命题保真" in synth_task
    assert "模拟法庭" in synth_task or "庭审" in synth_task
    assert "制度" in synth_task
    assert "替换命题对象" in synth_task or "抬成制度层" in synth_task
    # P3：汇总继承关键数字须带 #rN 或待核实语
    assert "待核实" in synth_task
    assert "#rN" in synth_task


def test_multi_lens_research_injects_user_message_into_synthesizer():
    """机制：expand 时注入用户原话全文到汇总员任务书（不依赖 CEO topic）。"""
    user_line = "茉莉奶白使用四叶花卉图形是否侵犯 LV 商标权，进行模拟法庭"
    tasks, errors = expand_playbook(
        "multi_lens_research",
        {"topic": "LV 诉茉莉奶白"},  # 故意丢「模拟法庭」——任务书仍须含原话
        user_message=user_line,
    )
    assert errors == []
    synth_task = _by_id(tasks)["synthesizer"]["task"]
    assert user_line in synth_task
    assert "用户原话" in synth_task or "机制注入" in synth_task
    # 透镜任务书不强制塞全文（只汇总员需要保真锚）
    assert user_line not in _by_id(tasks)["lens_0"]["task"]


def test_multi_lens_research_without_user_message_omits_anchor_block():
    tasks, errors = expand_playbook("multi_lens_research", {"topic": "X"})
    assert errors == []
    synth_task = _by_id(tasks)["synthesizer"]["task"]
    assert "机制注入" not in synth_task
    # 教法条款仍在（不依赖原话块）
    assert "命题保真" in synth_task


def test_multi_lens_research_custom_lenses():
    tasks, errors = expand_playbook(
        "multi_lens_research",
        {"topic": "X", "lenses": ["技术", "伦理", "监管"]},
    )
    assert errors == []
    by_id = _by_id(tasks)
    assert set(by_id["synthesizer"]["depends_on"]) == {"lens_0", "lens_1", "lens_2"}
    assert by_id["lens_1"]["role"] == "伦理视角"
    assert "伦理" in by_id["lens_1"]["task"]
    assert by_id["lens_1"]["deliverable"]["artifacts"] == ["research/伦理透镜报告.md"]


def test_multi_lens_research_folds_lenses_with_note_keeps_base_owner():
    """lenses 超扇出：折叠进末节点带 note；首透镜仍独占公共底料分工。"""
    from agentcore.runtime.runs.playbooks import MAX_PLAYBOOK_FANOUT, collect_playbook_notes
    from agentcore.runtime.runs.retrieval_budget import (
        DEFAULT_RETRIEVAL_BUDGET_LENS_BASE,
        DEFAULT_RETRIEVAL_BUDGET_LENS_GAP,
    )

    n = MAX_PLAYBOOK_FANOUT + 2
    lenses = [f"透镜{i}" for i in range(n)]
    tasks, errors = expand_playbook(
        "multi_lens_research", {"topic": "T", "lenses": lenses}
    )
    assert errors == []
    by_id = _by_id(tasks)
    lens_nodes = [t for t in tasks if t["id"].startswith("lens_")]
    assert len(lens_nodes) == MAX_PLAYBOOK_FANOUT
    last = by_id[f"lens_{MAX_PLAYBOOK_FANOUT - 1}"]
    for name in lenses[MAX_PLAYBOOK_FANOUT - 1 :]:
        assert name in last["role"] or name in last["task"]
    notes = collect_playbook_notes(tasks)
    assert notes and "扇出折叠" in notes[0]
    # First lens remains single primary base owner (fold only hits the last slot).
    assert by_id["lens_0"]["role"] == "透镜0视角"
    assert "负责人" in by_id["lens_0"]["task"] or "查全" in by_id["lens_0"]["task"]
    assert by_id["lens_0"]["retrieval_budget"] == DEFAULT_RETRIEVAL_BUDGET_LENS_BASE
    assert by_id[f"lens_{MAX_PLAYBOOK_FANOUT - 1}"]["retrieval_budget"] == (
        DEFAULT_RETRIEVAL_BUDGET_LENS_GAP
    )
    assert "负责人" not in last["task"]


def test_multi_lens_research_lens_retrieval_division():
    """教法：首透镜查全公共底料；其余透镜简要确认、预算盯独有缺口；并行无运行时依赖。"""
    from agentcore.runtime.runs.retrieval_budget import (
        DEFAULT_RETRIEVAL_BUDGET_LENS_BASE,
        DEFAULT_RETRIEVAL_BUDGET_LENS_GAP,
    )

    tasks, errors = expand_playbook(
        "multi_lens_research", {"topic": "LV 诉茉莉奶白商标案"}
    )
    assert errors == []
    by_id = _by_id(tasks)
    base = by_id["lens_0"]["task"]
    assert "检索分工" in base
    assert "公共基础事实" in base or "公共底料" in base
    assert "时间线" in base and "主体" in base
    assert "负责人" in base or "查全" in base
    assert "并行" in base or "互不等待" in base
    assert by_id["lens_0"]["retrieval_budget"] == DEFAULT_RETRIEVAL_BUDGET_LENS_BASE
    assert str(DEFAULT_RETRIEVAL_BUDGET_LENS_BASE) in base
    for lid in ("lens_1", "lens_2", "lens_3"):
        task = by_id[lid]["task"]
        assert "检索分工" in task
        assert "简要确认" in task
        assert "独有" in task
        assert "负责人" not in task  # 非首透镜不背公共底料全责
        assert by_id[lid]["retrieval_budget"] == DEFAULT_RETRIEVAL_BUDGET_LENS_GAP
        assert str(DEFAULT_RETRIEVAL_BUDGET_LENS_GAP) in task
    # 汇总员任务不动（命题保真已定案；本条只改透镜）
    synth = by_id["synthesizer"]["task"]
    assert "检索分工" not in synth
    assert "命题保真" in synth
    assert "retrieval_budget" not in by_id["synthesizer"]


def test_multi_lens_research_lens_budgets_survive_build_run_plan():
    """透镜差异化 retrieval_budget 经 builder 保留（CEO 显式优先于结构化默认）。"""
    from agentcore.runtime.runs.retrieval_budget import (
        DEFAULT_RETRIEVAL_BUDGET_LENS_BASE,
        DEFAULT_RETRIEVAL_BUDGET_LENS_GAP,
    )

    tasks, errors = expand_playbook(
        "multi_lens_research", {"topic": "T", "lenses": ["法律", "品牌商业"]}
    )
    assert errors == []
    plan, plan_errors = build_run_plan(tasks, id_prefix="pb_mlr_budget")
    assert plan_errors == []
    by_role = {n.role: n for n in plan.nodes}
    assert by_role["法律视角"].retrieval_budget == DEFAULT_RETRIEVAL_BUDGET_LENS_BASE
    assert by_role["品牌商业视角"].retrieval_budget == DEFAULT_RETRIEVAL_BUDGET_LENS_GAP


def test_multi_lens_research_files_form_builds_run_plan_with_artifacts():
    """form=files + artifacts 经真实 builder 接通验收闸（requires_files 隐含）。"""
    tasks, errors = expand_playbook(
        "multi_lens_research", {"topic": "T", "lenses": ["法律", "品牌商业"]}
    )
    assert errors == []
    plan, plan_errors = build_run_plan(tasks, id_prefix="pb_mlr_files")
    assert plan_errors == []
    by_role = {n.role: n for n in plan.nodes}
    legal = by_role["法律视角"]
    assert legal.deliverable is not None
    assert legal.deliverable.form == "files"
    assert legal.deliverable.requires_files is True
    assert legal.deliverable.artifacts == ["research/法律透镜报告.md"]
    synth = by_role["汇总分析师"]
    assert synth.deliverable is not None
    assert synth.deliverable.form == "files"
    assert synth.deliverable.artifacts == ["research/汇总与命题卡.md"]


def test_multi_lens_research_requires_topic():
    tasks, errors = expand_playbook("multi_lens_research", {})
    assert tasks == []
    assert errors and "topic" in errors[0]


# ── registry reject paths ─────────────────────────────────────────────────────


def test_expand_unknown_playbook_lists_available():
    tasks, errors = expand_playbook("nope", {})
    assert tasks == []
    assert errors and "未知 playbook" in errors[0]
    for name in PLAYBOOKS:
        assert name in errors[0]


def test_expand_rejects_non_object_args():
    tasks, errors = expand_playbook("research_report", ["not", "a", "dict"])  # type: ignore[arg-type]
    assert tasks == []
    assert errors and "playbook_args" in errors[0]


def test_available_playbooks_lists_all_registered():
    listing = available_playbooks()
    assert set(PLAYBOOKS) == {
        "research_report",
        "build_feature",
        "build_website",
        "build_toolshed",
        "build_website_verify",
        "compare_options",
        "organize_folder",
        "multi_lens_research",
    }
    for name in PLAYBOOKS:
        assert name in listing


# ── every expansion is a runnable plan (the real builder, not a mock) ──────────


def test_every_playbook_expansion_builds_a_valid_run_plan():
    samples = {
        "research_report": {"topic": "T", "angles": ["a", "b"], "checkpoint": True},
        "build_feature": {"feature": "F", "stack": "S"},
        "build_website": {"site": "Landing", "sections": ["hero", "cta"]},
        "build_toolshed": {"site": "Ops console", "sections": ["应用外壳", "数据表格"]},
        "build_website_verify": {"site": "Landing"},
        "compare_options": {"question": "Q", "options": ["A", "B", "C"]},
        "organize_folder": {"task": "扫描下载文件夹并给出整理方案"},
        "multi_lens_research": {"topic": "T"},
    }
    expected_nodes = {
        "research_report": 5,
        "build_feature": 3,
        "build_website": 7,  # copy + design + skeleton + 2 sections + assemble + qa
        "build_toolshed": 7,  # same shape, 2 sections
        "build_website_verify": 1,  # qa only
        "compare_options": 4,
        "organize_folder": 1,
        "multi_lens_research": 5,  # 4 lenses + synthesizer
    }
    assert set(samples) == set(PLAYBOOKS)  # 名副其实的 every：新增 playbook 必须补样本
    for name, args in samples.items():
        tasks, errors = expand_playbook(name, args)
        assert errors == [], name
        plan, plan_errors = build_run_plan(tasks, id_prefix=f"pb_{name}")
        assert plan_errors == [], (name, plan_errors)
        assert len(plan.nodes) == expected_nodes[name], name
        # waves() raises on a cycle / dangling edge — a clean call proves the DAG is sound.
        assert plan.waves()

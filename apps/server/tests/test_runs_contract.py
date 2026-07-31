"""Tests for the contract gate's mechanical checks (阶段2 第一刀).

Covers the always-on non-empty baseline, each declared rule (length / keyword /
section / json), failure collection order, and the feedback / requirements
rendering the executor uses for the retry prompt.
"""

from agentcore.runtime.runs.contract import (
    check_contract,
    debrief_meets_minimum,
    describe_deliverable,
    format_feedback,
    format_light_repair_feedback,
    format_write_pass_feedback,
    has_salvageable_half_product,
    is_file_deliverable,
    is_format_repairable,
    is_zero_files_gap,
    needs_file_contents,
    node_has_dependents,
    synthesize_debrief,
)
from agentcore.runtime.runs.types import Deliverable, RunContract


def test_empty_fails_baseline_without_contract():
    v = check_contract("   ", None)
    assert not v.ok
    assert "空" in v.failures[0]


def test_empty_passes_when_files_written():
    v = check_contract("", None, files_written=1)
    assert v.ok


def test_empty_passes_when_handoff_debrief_present():
    v = check_contract("", None, debrief={"summary": "已完成写入 index.html"})
    assert v.ok


def test_empty_passes_when_handoff_has_key_points_only():
    v = check_contract("", None, debrief={"key_points": ["要点一"]})
    assert v.ok


def test_empty_still_fails_with_no_alternate_signals():
    v = check_contract("", None, files_written=0, debrief=None)
    assert not v.ok
    assert "空" in v.failures[0]


def test_non_empty_passes_without_contract():
    v = check_contract("有内容", None)
    assert v.ok
    assert v.failures == []


def test_min_length_failure_and_pass():
    assert not check_contract("短", RunContract(min_length=10)).ok
    assert check_contract("这是一段足够长的产出内容", RunContract(min_length=5)).ok


def test_max_length_failure():
    v = check_contract("一二三四五六", RunContract(max_length=3))
    assert not v.ok
    assert any("超过" in f for f in v.failures)


def test_must_contain_failure_and_pass():
    contract = RunContract(must_contain=["风险", "结论"])
    v = check_contract("这里只讨论了结论", contract)
    assert not v.ok
    assert any("风险" in f for f in v.failures)
    assert check_contract("既有风险也有结论", contract).ok


def test_must_contain_case_insensitive():
    # Mirrors required_sections' casefold match: casing must not flip the verdict.
    contract = RunContract(must_contain=["API", "ROI"])
    assert check_contract("本方案的 api 设计与 roi 测算如下", contract).ok
    # A genuinely missing keyword still fails, and the reason shows原始大小写.
    v = check_contract("只提到了 api 设计", contract)
    assert not v.ok
    assert any("ROI" in f for f in v.failures)


def test_required_section_heading_shapes_detected():
    contract = RunContract(required_sections=["结论"])
    assert check_contract("# 结论\n内容", contract).ok
    assert check_contract("## 结论\n内容", contract).ok
    assert check_contract("**结论**\n内容", contract).ok
    assert check_contract("结论：完成了", contract).ok


def test_required_section_missing():
    v = check_contract("# 结论\n正文很长", RunContract(required_sections=["参考来源"]))
    assert not v.ok
    assert any("参考来源" in f for f in v.failures)


def test_required_section_incidental_mention_not_enough():
    # A keyword buried in prose is not a section heading.
    v = check_contract("我们在文中得出结论这件事很复杂", RunContract(required_sections=["结论"]))
    assert not v.ok


def test_json_format_pass_plain_and_fenced():
    contract = RunContract(output_format="json")
    assert check_contract('{"a": 1}', contract).ok
    assert check_contract('```json\n{"a": 1}\n```', contract).ok


def test_json_format_failure_on_prose():
    v = check_contract("这不是 JSON", RunContract(output_format="json"))
    assert not v.ok
    assert any("JSON" in f for f in v.failures)


def test_multiple_failures_collected():
    v = check_contract("短文本", RunContract(min_length=100, must_contain=["X"]))
    assert len(v.failures) == 2


def test_format_feedback_lists_reasons():
    fb = format_feedback(check_contract("短", RunContract(min_length=10, must_contain=["X"])))
    assert "少于" in fb
    assert "X" in fb
    assert fb.startswith("你上一次")


def test_format_feedback_steers_worker_to_skip_meta_commentary():
    # The worker has a single rework shot — spend it on the corrected product,
    # not on apologies or explanations.
    fb = format_feedback(check_contract("短", RunContract(min_length=10)))
    assert "完整最终产出" in fb
    assert "不要解释" in fb
    assert "不要道歉" in fb


def test_format_feedback_empty_when_ok():
    assert format_feedback(check_contract("ok 内容", None)) == ""


def test_is_format_repairable_for_section_and_short():
    section = check_contract(
        "正文里没有章节", RunContract(required_sections=["结论"])
    )
    assert is_format_repairable(section)
    short = check_contract("短", RunContract(min_length=10))
    assert is_format_repairable(short)
    keyword = check_contract("只有别的", RunContract(must_contain=["风险"]))
    assert is_format_repairable(keyword)
    mixed = check_contract(
        "短", RunContract(min_length=10, output_format="json")
    )
    assert not is_format_repairable(mixed)
    empty = check_contract("", None)
    assert not is_format_repairable(empty)
    assert not is_format_repairable(check_contract("ok 内容足够长", None))


def test_format_light_repair_feedback_carries_prior_and_skips_reinvestigate():
    v = check_contract("草稿缺章", RunContract(required_sections=["结论"], min_length=5))
    fb = format_light_repair_feedback(v, prior_content="草稿缺章\n更多正文")
    assert "不必重新调查" in fb
    assert "缺少必备章节" in fb
    assert "草稿缺章" in fb
    assert "不要重新检索" in fb
    assert "str_replace" in fb
    assert "file_read" in fb  # soft tip: prefer manifest, avoid thrash re-read
    assert format_light_repair_feedback(
        check_contract("ok 内容", None), prior_content="x"
    ) == ""


def test_zero_files_gap_and_write_pass_feedback():
    v = check_contract(
        "只有文字", Deliverable(requires_files=True), files_written=0
    )
    assert is_zero_files_gap(v)
    assert not is_format_repairable(v)
    fb = format_write_pass_feedback(v)
    assert "短写盘 pass" in fb
    assert "file_write" in fb
    assert not is_zero_files_gap(
        check_contract("ok", Deliverable(requires_files=True), files_written=1)
    )


def test_has_salvageable_half_product_gates_empty_synth():
    assert not has_salvageable_half_product("", [], None)
    assert not has_salvageable_half_product("  ", [], {"summary": "x", "degraded": True})
    assert has_salvageable_half_product("有正文", [], None)
    assert has_salvageable_half_product("", ["a.py"], None)
    assert has_salvageable_half_product(
        "",
        [],
        {
            "summary": (
                "足够长的合格交接简报内容用于下游接力——"
                "根因与拟改路径、风险假设与建议下一步均已写清，满足交接信息量地板。"
            )
        },
    )
    # Empty inventory → synthesize still returns a shell, but callers must not use it.
    empty = synthesize_debrief("", [])
    assert empty.get("degraded") is True
    assert "无正文" in empty["summary"]


def test_force_finalize_salvage_accepts_tool_inventory_without_widening_half_product():
    from agentcore.llm.provider.protocol import LLMMessage
    from agentcore.runtime.engine.tool_exec import with_tool_failed_marker
    from agentcore.runtime.runs.contract import (
        has_salvageable_half_product,
        should_attempt_force_finalize_salvage,
        transcript_has_tool_inventory,
    )

    msgs = [
        LLMMessage(role="user", content="go"),
        LLMMessage(role="tool", content="file body here", tool_call_id="c1"),
    ]
    assert transcript_has_tool_inventory(msgs)
    assert not has_salvageable_half_product("", [], None)
    assert should_attempt_force_finalize_salvage("", [], None, messages=msgs)
    assert not should_attempt_force_finalize_salvage(
        "", [], None, messages=[LLMMessage(role="user", content="go")]
    )
    failed_only = [
        LLMMessage(
            role="tool",
            content=with_tool_failed_marker("boom"),
            tool_call_id="f1",
        )
    ]
    assert not transcript_has_tool_inventory(failed_only)
    assert not should_attempt_force_finalize_salvage("", [], None, messages=failed_only)


def test_describe_deliverable_renders_rules():
    desc = describe_deliverable(
        Deliverable(
            required_sections=["结论"], must_contain=["风险"], min_length=200, output_format="json"
        )
    )
    # json + required_sections: describe only surfaces JSON (Markdown sections skipped)
    assert "JSON" in desc
    assert "风险" in desc
    assert "200" in desc
    assert "小标题" not in desc


def test_describe_deliverable_none_is_empty():
    assert describe_deliverable(None) == ""


def test_describe_deliverable_renders_section_skeleton():
    """required_sections appear both as acceptance list and as Markdown skeleton."""
    desc = describe_deliverable(
        Deliverable(required_sections=["Bug清单", "每个Bug的详情"], min_length=50)
    )
    assert "Bug清单" in desc
    assert "每个Bug的详情" in desc
    assert "## Bug清单" in desc
    assert "## 每个Bug的详情" in desc
    assert "建议正文骨架" in desc


def test_describe_deliverable_json_file_channel():
    desc = describe_deliverable(
        Deliverable(
            form="files",
            output_format="json",
            artifacts=["AgentCore/文档/reviews/legal.json"],
            name="结构化审查",
        )
    )
    assert "JSON" in desc
    assert "AgentCore/文档/reviews/legal.json" in desc
    assert "文件存在" in desc or "可解析" in desc


# --- Mix defense: output_format=json vs required_sections (Markdown) -------------


def test_json_skips_required_sections_mix():
    # JSON field names stuffed into required_sections must not cause false failure.
    contract = RunContract(
        output_format="json",
        required_sections=["problems", "suggestions", "score"],
    )
    v = check_contract('{"problems": [], "suggestions": [], "score": 8}', contract)
    assert v.ok
    assert v.failures == []


def test_json_file_channel_accepts_prose_chat_when_file_valid():
    contract = RunContract(
        output_format="json",
        artifacts=["review.json"],
        requires_files=True,
    )
    v = check_contract(
        "已写入审查结果",
        contract,
        files_written=1,
        workspace_paths=["review.json"],
        artifact_contents={"review.json": '{"problems": [], "score": 7}'},
    )
    assert v.ok


def test_json_file_channel_fails_when_file_not_json():
    contract = RunContract(
        output_format="json",
        artifacts=["review.json"],
        requires_files=True,
    )
    v = check_contract(
        "已写入",
        contract,
        files_written=1,
        workspace_paths=["review.json"],
        artifact_contents={"review.json": "这不是 JSON"},
    )
    assert not v.ok
    assert any("JSON" in f for f in v.failures)


def test_json_file_channel_without_contents_still_checks_existence():
    # Callers that only have a path index still get existence failures.
    contract = RunContract(output_format="json", artifacts=["review.json"], requires_files=True)
    v = check_contract(
        "贴了",
        contract,
        files_written=1,
        workspace_paths=[],
        artifact_contents=None,
    )
    assert not v.ok
    assert any("review.json" in f for f in v.failures)


# --- requires_files: the deliverable-landed gate over files_written -------------


def test_requires_files_fails_when_none_written():
    v = check_contract("我把整份代码贴在这里", RunContract(requires_files=True), files_written=0)
    assert not v.ok
    assert any("工作区" in f for f in v.failures)


def test_requires_files_passes_when_a_file_was_written():
    assert check_contract("已写入 index.html", RunContract(requires_files=True), files_written=1).ok


def test_requires_files_passes_when_str_replace_landed():
    """str_replace / file_append 成功落盘须计入 files_written（分区 worker 增量补丁）。"""
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
    from agentcore.runtime.runs.serialize import files_touched_from_transcript

    transcript = [
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="s1",
                    function=ToolCallFunction(
                        name="str_replace",
                        arguments='{"path": "site/index.html", "old_string": "a", "new_string": "b"}',
                    ),
                )
            ],
        ),
        LLMMessage(role="tool", content="已替换 site/index.html", tool_call_id="s1"),
    ]
    touched = files_touched_from_transcript(transcript)
    assert touched == ["site/index.html"]
    v = check_contract(
        "",
        Deliverable(form="files", requires_files=True, artifacts=["site/index.html"]),
        files_written=len(touched),
        workspace_paths=["site/index.html", "site/styles.css"],
        artifact_contents={"site/index.html": "<html></html>"},
    )
    assert v.ok
    assert not any("未把产物写入工作区" in f for f in v.failures)


def test_file_deliverable_empty_body_passes_when_artifact_text_loaded():
    """QA 等 file_write 收尾 + 空 streamed 正文：契约应读落盘文件，勿判「产出为空」。"""
    qa_body = "# QA\n\n## 通过项\n- HTML 结构完整\n"
    v = check_contract(
        "",
        Deliverable(form="files", artifacts=["site/QA.md"], requires_files=True),
        files_written=1,
        workspace_paths=["site/QA.md"],
        artifact_contents={"site/QA.md": qa_body},
    )
    assert v.ok
    assert "产出为空" not in str(v.failures)


def test_file_deliverable_still_fails_when_nothing_landed():
    v = check_contract(
        "",
        Deliverable(form="files", artifacts=["site/QA.md"], requires_files=True),
        files_written=0,
        workspace_paths=["site/index.html"],
        artifact_contents=None,
    )
    assert not v.ok
    assert any("产出为空" in f or "工作区" in f for f in v.failures)


def test_requires_files_off_by_default_ignores_file_count():
    # A prose contract (requires_files unset) never fails for lack of a file write.
    assert check_contract("纯文字分析", RunContract(min_length=2), files_written=0).ok


def test_describe_deliverable_renders_requires_files():
    desc = describe_deliverable(Deliverable(requires_files=True))
    assert "file_write" in desc
    assert "str_replace" in desc
    assert "工作区" in desc


# --- artifacts: declarative path reconciliation ---------------------------------


def test_artifacts_pass_when_exact_path_present():
    v = check_contract(
        "done",
        RunContract(artifacts=["README.md"]),
        files_written=1,
        workspace_paths=["README.md", "src/main.py"],
    )
    assert v.ok


def test_artifacts_fail_when_path_missing():
    v = check_contract(
        "done",
        RunContract(artifacts=["README.md", "examples/demo.py"]),
        files_written=1,
        workspace_paths=["src/main.py"],
    )
    assert not v.ok
    assert any("README.md" in f for f in v.failures)
    assert any("examples/demo.py" in f for f in v.failures)


def test_artifacts_glob_and_directory_match():
    d = RunContract(artifacts=["src/**/*.py", "examples/", "pkg/"])
    assert check_contract(
        "ok",
        d,
        files_written=2,
        workspace_paths=["src/a/b.py", "examples/x.txt", "pkg/__init__.py"],
    ).ok
    v = check_contract(
        "ok",
        d,
        files_written=1,
        workspace_paths=["src/a/b.py"],
    )
    assert not v.ok
    assert any("examples/" in f for f in v.failures)


def test_artifacts_empty_workspace_all_missing():
    v = check_contract(
        "贴了代码",
        RunContract(artifacts=["a.py"]),
        files_written=0,
        workspace_paths=[],
    )
    assert not v.ok
    # requires_files is implied by artifacts in builder; here we set artifacts alone
    # so both the files_written and path checks can fire depending on flags.
    assert any("a.py" in f for f in v.failures)


def test_artifacts_workspace_prefix_vs_relative_index_no_false_missing():
    """Accident shape: handoff declares /workspace/… while index/touched are relative.

    Bare ``lstrip("./")`` used to rewrite ``/workspace/index.html`` → ``workspace/index.html``,
    which never equals ``index.html`` → false「声明的交付物路径未落盘」despite a real write.
    """
    landed = ["index.html", "css/style.css", "js/main.js"]
    # Absolute sandbox prefix on one path + relatives (trace 7dbb0174… mix).
    declared = ["/workspace/index.html", "css/style.css", "js/main.js"]
    assert check_contract(
        "done",
        RunContract(artifacts=declared),
        files_written=len(landed),
        workspace_paths=landed,
    ).ok
    # Reverse: relative declaration, absolute-shaped index/touched entries.
    assert check_contract(
        "done",
        RunContract(artifacts=["index.html", "css/style.css", "js/main.js"]),
        files_written=3,
        workspace_paths=[
            "/workspace/index.html",
            "/workspace/css/style.css",
            "/workspace/js/main.js",
        ],
    ).ok
    # All-absolute declaration against relative index.
    assert check_contract(
        "done",
        RunContract(
            artifacts=[
                "/workspace/index.html",
                "/workspace/css/style.css",
                "/workspace/js/main.js",
            ]
        ),
        files_written=3,
        workspace_paths=landed,
    ).ok


def test_artifacts_workspace_prefix_still_fails_when_truly_missing():
    """Prefix rewrite must not invent a hit — absent relative files still fail."""
    v = check_contract(
        "done",
        RunContract(artifacts=["/workspace/index.html", "/workspace/missing.css"]),
        files_written=1,
        workspace_paths=["index.html"],
    )
    assert not v.ok
    assert any("missing.css" in f for f in v.failures)
    assert not any("index.html" in f for f in v.failures)


def test_describe_deliverable_renders_artifacts():
    desc = describe_deliverable(Deliverable(artifacts=["README.md", "examples/*"]))
    assert "README.md" in desc
    assert "examples/*" in desc


def test_debrief_meets_minimum_summary_or_key_points():
    assert not debrief_meets_minimum(None)
    assert not debrief_meets_minimum({"summary": "太短"})
    assert debrief_meets_minimum({"summary": "x" * 50})
    assert debrief_meets_minimum({"summary": "短", "key_points": ["a", "b"]})


def test_synthesize_debrief_marks_degraded():
    d = synthesize_debrief("正文结论一段", ["a.py", "b.py"])
    assert d["degraded"] is True
    assert "正文结论" in d["summary"]
    assert d["key_points"]


def test_node_has_dependents():
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec

    plan = RunPlan(
        nodes=[
            RunSpec(run_id="a", task="t"),
            RunSpec(run_id="b", task="t", depends_on=["a"]),
        ]
    )
    assert node_has_dependents(plan, "a")
    assert not node_has_dependents(plan, "b")


# --- 交付形态对齐: file-form deliverables check body + landed files ------------------


def test_is_file_deliverable_predicate():
    assert is_file_deliverable(Deliverable(form="files"))
    assert is_file_deliverable(Deliverable(requires_files=True))
    assert is_file_deliverable(Deliverable(artifacts=["a.md"]))
    assert not is_file_deliverable(Deliverable(form="prose"))
    assert not is_file_deliverable(Deliverable(min_length=10))
    assert not is_file_deliverable(None)


def test_needs_file_contents_predicate():
    # file-form + a content check → must read the file
    assert needs_file_contents(Deliverable(form="files", min_length=10))
    assert needs_file_contents(Deliverable(artifacts=["a.md"], required_sections=["X"]))
    assert needs_file_contents(Deliverable(requires_files=True, must_contain=["k"]))
    # JSON file gate still needs contents
    assert needs_file_contents(Deliverable(output_format="json", artifacts=["a.json"]))
    # file-form but existence-only (no content rule) → no read needed
    assert not needs_file_contents(Deliverable(form="files", requires_files=True))
    assert not needs_file_contents(Deliverable(artifacts=["a.md"]))
    # prose (body-only) → no file read
    assert not needs_file_contents(Deliverable(min_length=10))
    assert not needs_file_contents(None)
    # web batch (HTML+CSS/JS) → read even for existence-only / no deliverable
    assert needs_file_contents(
        Deliverable(form="files", requires_files=True),
        landed_paths=["index.html", "style.css"],
    )
    assert needs_file_contents(None, landed_paths=["index.html", "app.js"])
    # content surface (Markdown) → placeholder scan needs a read
    assert needs_file_contents(
        Deliverable(form="files", requires_files=True),
        landed_paths=["report.md"],
    )
    # code-only landing → still no read for existence-only deliverable
    assert not needs_file_contents(
        Deliverable(form="files", requires_files=True),
        landed_paths=["main.py"],
    )


def test_file_form_section_satisfied_by_file_only():
    # The paper's sections live ONLY in the landed file; the chat body is a terse note.
    contract = Deliverable(
        form="files", requires_files=True, required_sections=["方法", "结论"]
    )
    v = check_contract(
        "论文已写入 paper.md",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "# 方法\n做法……\n\n# 结论\n结果……"},
    )
    assert v.ok
    assert v.failures == []


def test_file_form_section_missing_in_both_fails():
    contract = Deliverable(
        form="files", requires_files=True, required_sections=["参考文献"]
    )
    v = check_contract(
        "论文已写入",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "# 方法\n# 结论"},
    )
    assert not v.ok
    assert any("参考文献" in f for f in v.failures)


def test_file_form_must_contain_satisfied_by_file():
    contract = Deliverable(form="files", requires_files=True, must_contain=["风险", "结论"])
    v = check_contract(
        "见 paper.md",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "本文讨论了风险，并给出结论。"},
    )
    assert v.ok


def test_file_form_length_uses_max_of_body_and_files_not_sum():
    # min_length satisfied by the file alone (body is short); NOT by concatenation.
    contract = Deliverable(form="files", requires_files=True, min_length=100)
    v = check_contract(
        "短说明",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "正" * 200},
    )
    assert v.ok
    # Two short texts must NOT add up past the floor — max, not sum.
    v2 = check_contract(
        "正" * 60,
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "正" * 60},
    )
    assert not v2.ok
    assert any("少于" in f for f in v2.failures)


def test_file_form_max_length_trips_on_long_file():
    contract = Deliverable(form="files", requires_files=True, max_length=50)
    v = check_contract(
        "短说明",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "正" * 200},
    )
    assert not v.ok
    assert any("超过" in f for f in v.failures)


def test_prose_deliverable_ignores_file_contents():
    # A prose (non-file) deliverable keeps body-only semantics even if contents are passed.
    contract = Deliverable(form="prose", required_sections=["结论"])
    v = check_contract(
        "正文没有结论章节",
        contract,
        artifact_contents={"note.md": "# 结论\n有的"},
    )
    assert not v.ok
    assert any("结论" in f for f in v.failures)


def test_artifacts_deliverable_section_from_file_without_form():
    # artifacts (non-empty) alone marks it file-form → sections read the file.
    contract = Deliverable(artifacts=["report.md"], required_sections=["结论"])
    v = check_contract(
        "已写入",
        contract,
        files_written=1,
        workspace_paths=["report.md"],
        artifact_contents={"report.md": "# 结论\n完成"},
    )
    assert v.ok


def test_file_form_falls_back_to_body_when_contents_unavailable():
    # A read failure (no artifact_contents) degrades to body-only rather than crashing.
    contract = Deliverable(form="files", requires_files=True, required_sections=["结论"])
    ok_body = check_contract(
        "# 结论\n正文里有章节", contract, files_written=1, workspace_paths=["p.md"]
    )
    assert ok_body.ok
    miss = check_contract(
        "正文里没有章节", contract, files_written=1, workspace_paths=["p.md"]
    )
    assert not miss.ok


def test_format_feedback_annotates_checked_channels():
    v = check_contract(
        "缺章节",
        Deliverable(form="files", requires_files=True, required_sections=["结论"]),
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "# 方法"},
    )
    fb = format_feedback(v, checked_files=["paper.md"])
    assert "paper.md" in fb
    assert "回复正文" in fb
    assert "落盘文件" in fb


def test_format_feedback_no_channel_note_for_prose():
    fb = format_feedback(check_contract("短", RunContract(min_length=10)))
    assert "落盘文件" not in fb


def test_artifact_unbound_bibliography_fails_when_ledger_connected():
    """File deliverable with GB/T [D] and no #rN fails contract when ledger is on."""
    contract = Deliverable(form="files", requires_files=True, min_length=5)
    body = "郝万鑫. 某问题研究[D]. 长江大学, 2026."
    v = check_contract(
        "已写入综述",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": body},
        ledger_entries=[],
        citable_ids=frozenset(),
    )
    assert not v.ok
    assert any("paper.md" in f and ("#rN" in f or "编造" in f or "未核验" in f) for f in v.failures)


def test_artifact_bound_bibliography_passes():
    contract = Deliverable(form="files", requires_files=True, min_length=5)
    entries = [
        {
            "id": "#r1",
            "url": "https://example.com/paper",
            "title": "正式论文",
            "snippet": "",
            "deep_read": True,
            "doc_kind": "thesis",
        }
    ]
    v = check_contract(
        "已写入",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "张三. 某问题研究[D]. #r1\n\n正文足够长了。"},
        ledger_entries=entries,
        citable_ids=frozenset({"#r1"}),
    )
    assert v.ok


def test_artifact_bibliography_skipped_without_ledger():
    """Without ledger connection, unbound [D] in files does not fail (legacy scope)."""
    contract = Deliverable(form="files", requires_files=True, min_length=5)
    v = check_contract(
        "已写入综述",
        contract,
        files_written=1,
        workspace_paths=["paper.md"],
        artifact_contents={"paper.md": "郝万鑫. 某问题研究[D]. 长江大学, 2026."},
    )
    assert v.ok


def test_artifact_invalid_r_ref_fails():
    contract = Deliverable(form="files", requires_files=True, min_length=5)
    v = check_contract(
        "已写入",
        contract,
        files_written=1,
        workspace_paths=["note.md"],
        artifact_contents={"note.md": "结论见 #r99，详见上文分析。"},
        ledger_entries=[],
        citable_ids=frozenset({"#r1"}),
    )
    assert not v.ok
    assert any("note.md" in f and "#r99" in f for f in v.failures)


def test_phase_a_skips_citation_gate():
    """调研阶段 A：enforce_citations=False → unbound #rN 不过成稿引用闸。"""
    from agentcore.runtime.runs.contract import partition_citation_failures

    contract = Deliverable(
        form="files",
        requires_files=True,
        min_length=5,
        citation_mode="two_phase",
    )
    body = "结论见 #r99，广搜摘要。"
    skipped = check_contract(
        "已落盘草案",
        contract,
        files_written=1,
        workspace_paths=["AgentCore/文档/research/角度.md"],
        artifact_contents={"AgentCore/文档/research/角度.md": body},
        ledger_entries=[],
        citable_ids=frozenset({"#r1"}),
        enforce_citations=False,
    )
    assert skipped.ok
    enforced = check_contract(
        "已落盘草案",
        contract,
        files_written=1,
        workspace_paths=["AgentCore/文档/research/角度.md"],
        artifact_contents={"AgentCore/文档/research/角度.md": body},
        ledger_entries=[],
        citable_ids=frozenset({"#r1"}),
        enforce_citations=True,
    )
    assert not enforced.ok
    cite, other = partition_citation_failures(enforced.failures)
    assert cite and not other


def test_non_research_citation_gate_unchanged():
    """非调研路径（citation_mode 默认）仍立刻跑引用闸。"""
    contract = Deliverable(form="files", requires_files=True, min_length=5)
    v = check_contract(
        "已写入",
        contract,
        files_written=1,
        workspace_paths=["site/copy.md"],
        artifact_contents={"site/copy.md": "售价 99 元#r99。"},
        ledger_entries=[],
        citable_ids=frozenset({"#r1"}),
    )
    assert not v.ok
    assert any("#r99" in f for f in v.failures)


def test_needs_file_contents_loads_md_for_citation_surfaces():
    assert needs_file_contents(
        Deliverable(requires_files=True),
        landed_paths=["AgentCore/文档/research/综述.md"],
    )

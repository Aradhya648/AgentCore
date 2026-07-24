"""Tests for deliverable placeholder / unverified-content scan (hard fail / soft warn)."""

from agentcore.runtime.runs.contract import (
    check_contract,
    format_soft_reminders,
    needs_file_contents,
)
from agentcore.runtime.runs.placeholder_scan import (
    is_code_deliverable_path,
    is_content_deliverable_path,
    needs_placeholder_scan,
    scan_placeholder_signals,
)
from agentcore.runtime.runs.types import Deliverable


def test_hard_placeholder_phone_fails_with_location():
    # GEO-style: marketing HTML ships a 400-XXX-XXXX placeholder phone.
    html = (
        "<html><body><h1>联系我们</h1>"
        "<p>客服热线：400-XXX-XXXX</p>"
        "</body></html>"
    )
    result = scan_placeholder_signals({"index.html": html})
    assert result.failures
    assert any("400-XXX-XXXX" in f or "占位电话" in f for f in result.failures)
    assert any(h.label == "占位电话段" for h in result.hits if h.kind == "hard")
    assert result.warnings == []

    v = check_contract(
        "官网已写入",
        Deliverable(form="files", requires_files=True, artifacts=["index.html"]),
        files_written=1,
        workspace_paths=["index.html"],
        artifact_contents={"index.html": html},
    )
    assert not v.ok
    assert any("占位" in f or "400" in f for f in v.failures)
    assert v.warnings == []


def test_soft_unverified_self_note_warns_only():
    # Author self-note: 示例数据 / 发布前核实 — warn, do not fail acceptance.
    md = (
        "# 增长报告\n\n"
        "本页客户证言为示例，关键指标为示例数据（发布前核实）。\n\n"
        "转化率提升 37%。\n"
    )
    result = scan_placeholder_signals({"report.md": md})
    assert result.failures == []
    assert result.warnings
    assert any("示例" in w or "核实" in w for w in result.warnings)

    v = check_contract(
        "报告已写入",
        Deliverable(form="files", requires_files=True, artifacts=["report.md"]),
        files_written=1,
        workspace_paths=["report.md"],
        artifact_contents={"report.md": md},
    )
    assert v.ok
    assert v.failures == []
    assert v.warnings
    reminder = format_soft_reminders(v)
    assert "未阻断" in reminder
    assert "示例" in reminder or "核实" in reminder


def test_code_file_todo_xxx_exempt_from_hard():
    # Normal coding habits in .py / .ts must not trip the hard gate.
    py = (
        "# TODO: wire real metrics\n"
        "PHONE = '400-XXX-XXXX'  # XXX placeholder for tests\n"
        "PLACEHOLDER = True\n"
    )
    ts = "// FIXME: remove before ship\nexport const x = 'PLACEHOLDER';\n"
    result = scan_placeholder_signals({"svc.py": py, "ui.ts": ts})
    assert result.failures == []
    assert result.warnings == []
    assert result.hits == []

    v = check_contract(
        "代码已写入",
        Deliverable(form="files", requires_files=True),
        files_written=2,
        workspace_paths=["svc.py", "ui.ts"],
        artifact_contents={"svc.py": py, "ui.ts": ts},
    )
    assert v.ok
    assert v.failures == []
    assert v.warnings == []


def test_needs_file_contents_true_for_content_surface_paths():
    assert needs_placeholder_scan(["index.html"])
    assert needs_placeholder_scan(["docs/report.md", "app.py"])
    assert not needs_placeholder_scan(["app.py", "lib.ts"])
    assert is_content_deliverable_path("site/index.html")
    assert is_code_deliverable_path("src/main.py")
    assert needs_file_contents(
        Deliverable(form="files", requires_files=True),
        landed_paths=["report.md"],
    )
    assert needs_file_contents(None, landed_paths=["about.html"])
    assert not needs_file_contents(
        Deliverable(form="files", requires_files=True),
        landed_paths=["main.py"],
    )


def test_clean_content_passes():
    html = "<html><body><p>客服热线：400-800-1234</p></body></html>"
    assert scan_placeholder_signals({"index.html": html}).failures == []
    assert scan_placeholder_signals({"index.html": html}).warnings == []
    assert scan_placeholder_signals(None).failures == []
    assert scan_placeholder_signals({}).failures == []


def test_lorem_prohibition_restatement_not_hard_fail():
    """DESIGN / anti-slop rules that say『禁止 lorem ipsum』must not self-trigger."""
    md = (
        "# DESIGN\n\n"
        "- 禁止 lorem ipsum 占位文案\n"
        "- 禁假拉丁填充段\n"
    )
    assert scan_placeholder_signals({"site/DESIGN.md": md}).failures == []
    # Real filler still fails.
    bad = "# 正文\n\nlorem ipsum dolor sit amet\n"
    result = scan_placeholder_signals({"site/copy.md": bad})
    assert result.failures
    assert any(h.label == "lorem ipsum" for h in result.hits if h.kind == "hard")


def test_html_form_placeholder_attribute_not_hard_signal():
    # Native input placeholder hints are legitimate UI copy, not PLACEHOLDER tokens.
    html = (
        '<html><body><form>'
        '<input type="text" placeholder="请输入您的姓名" />'
        '<input type="email" placeholder="请输入邮箱地址" />'
        "</form></body></html>"
    )
    result = scan_placeholder_signals({"index.html": html})
    assert result.failures == []
    assert result.warnings == []
    assert result.hits == []


def test_html_placeholder_value_with_hard_phone_still_fails():
    html = (
        '<html><body><input type="tel" placeholder="400-XXX-XXXX" />'
        "</body></html>"
    )
    result = scan_placeholder_signals({"index.html": html})
    assert result.failures
    assert any(h.label == "占位电话段" for h in result.hits if h.kind == "hard")


def test_html_placeholder_value_with_placeholder_token_still_fails():
    html = '<html><body><input placeholder="PLACEHOLDER" /></body></html>'
    result = scan_placeholder_signals({"index.html": html})
    assert result.failures
    assert any(h.label == "PLACEHOLDER" for h in result.hits if h.kind == "hard")


def test_css_js_placeholder_syntax_not_hard_signal():
    html = (
        "<html><head><style>"
        "input::placeholder { color: #999; }"
        ".placeholder-text { font-style: italic; }"
        "</style></head><body>"
        "<script>"
        "const el = document.querySelector('input');"
        "el.placeholder = '请输入';"
        "const cfg = { placeholder: 'hint' };"
        "el.setAttribute('placeholder', '姓名');"
        "</script>"
        '<input placeholder="请输入您的姓名" />'
        "</body></html>"
    )
    result = scan_placeholder_signals({"index.html": html})
    assert result.failures == []
    assert result.hits == []


def test_placeholder_hard_exempt_artifact_skips_fail_keeps_soft():
    """Internal coordination docs (CONTRACT.md) may carry TODO — hard exempt only."""
    contract_md = (
        "# 契约\n\n"
        "## hero\n"
        "- id: #hero\n"
        "- TODO: wire scroll spy after sections land\n"
    )
    result = scan_placeholder_signals(
        {"site/CONTRACT.md": contract_md},
        hard_exempt_paths=["site/CONTRACT.md"],
    )
    assert result.failures == []
    assert not any(h.kind == "hard" for h in result.hits)

    v = check_contract(
        "契约已写入",
        Deliverable(
            form="files",
            requires_files=True,
            artifacts=["site/CONTRACT.md"],
            placeholder_hard_exempt_artifacts=["site/CONTRACT.md"],
        ),
        files_written=1,
        workspace_paths=["site/CONTRACT.md"],
        artifact_contents={"site/CONTRACT.md": contract_md},
    )
    assert v.ok
    assert v.failures == []


def test_placeholder_exempt_does_not_shield_user_html():
    """Exempt CONTRACT.md only — index.html TODO still hard-fails."""
    html = "<html><body><!-- TODO: replace --></body></html>"
    contract_md = "# TODO: internal note\n"
    v = check_contract(
        "骨架已落盘",
        Deliverable(
            form="files",
            requires_files=True,
            artifacts=["site/index.html", "site/CONTRACT.md"],
            placeholder_hard_exempt_artifacts=["site/CONTRACT.md"],
        ),
        files_written=2,
        workspace_paths=["site/index.html", "site/CONTRACT.md"],
        artifact_contents={
            "site/index.html": html,
            "site/CONTRACT.md": contract_md,
        },
    )
    assert not v.ok
    assert any("TODO" in f or "占位" in f for f in v.failures)


def test_placeholder_hard_exempt_bool_covers_all_artifacts():
    """QA node style: placeholder_hard_exempt=True skips hard scan on whole batch."""
    qa_md = "# QA\n\n- [ ] TODO: verify form submit\n"
    v = check_contract(
        "QA 已写入",
        Deliverable(
            form="files",
            requires_files=True,
            artifacts=["site/QA.md"],
            placeholder_hard_exempt=True,
        ),
        files_written=1,
        workspace_paths=["site/QA.md"],
        artifact_contents={"site/QA.md": qa_md},
    )
    assert v.ok
    assert v.failures == []


def test_path_matches_placeholder_exempt():
    from agentcore.runtime.runs.placeholder_scan import path_matches_placeholder_exempt

    assert path_matches_placeholder_exempt("site/CONTRACT.md", ["site/CONTRACT.md"])
    assert path_matches_placeholder_exempt("./site/QA.md", ["site/QA.md"])
    assert not path_matches_placeholder_exempt("site/index.html", ["site/CONTRACT.md"])

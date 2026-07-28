"""确定性 Check 单测（评估体系 §十二）：每个 Check 的过/不过分支，零真实 LLM.

走 ``build_check`` 的 spec 路径（顺带覆盖注册表映射），对构造的 ``TurnOutcome`` 断言。
"""

import sys

from agentcore.evals.checks import CHECK_NAMES, build_check
from agentcore.evals.types import EvalCase, TurnOutcome


def _case(**kw) -> EvalCase:
    base = {"id": "c", "category": "qa", "user_message": "q"}
    base.update(kw)
    return EvalCase(**base)


def _outcome(**kw) -> TurnOutcome:
    base = {"content": "hello", "finish_reason": "end_turn", "rounds": 1}
    base.update(kw)
    return TurnOutcome(**base)


def _run(spec: dict, outcome: TurnOutcome, case: EvalCase | None = None):
    return build_check(spec).run(case or _case(), outcome)


def test_finish_reason_pass_and_fail():
    assert _run({"name": "FinishReason"}, _outcome(finish_reason="end_turn")).passed
    assert not _run({"name": "FinishReason"}, _outcome(finish_reason="error")).passed
    assert not _run({"name": "FinishReason"}, _outcome(finish_reason="max_rounds")).passed
    # 自定义期望值
    assert _run(
        {"name": "FinishReason", "args": {"expected": "max_rounds"}},
        _outcome(finish_reason="max_rounds"),
    ).passed


def test_non_empty_threshold():
    assert _run({"name": "NonEmpty", "args": {"min_len": 3}}, _outcome(content="abc")).passed
    assert not _run({"name": "NonEmpty", "args": {"min_len": 10}}, _outcome(content="abc")).passed
    assert not _run({"name": "NonEmpty"}, _outcome(content="   ")).passed


def test_tool_called():
    oc = _outcome(tool_calls=[("web_search", '{"query": "x"}')])
    assert _run({"name": "ToolCalled", "args": {"tool": "web_search"}}, oc).passed
    assert not _run({"name": "ToolCalled", "args": {"tool": "file_read"}}, oc).passed


def test_tool_args_valid():
    oc = _outcome(tool_calls=[("web_search", '{"query": "x"}')])
    assert _run(
        {"name": "ToolArgsValid", "args": {"tool": "web_search", "required": ["query"]}}, oc
    ).passed
    # 缺必填键
    assert not _run(
        {"name": "ToolArgsValid", "args": {"tool": "web_search", "required": ["q"]}}, oc
    ).passed
    # 非法 JSON
    bad = _outcome(tool_calls=[("web_search", "{not json}")])
    assert not _run({"name": "ToolArgsValid", "args": {"tool": "web_search"}}, bad).passed
    # 未调用该工具
    assert not _run(
        {"name": "ToolArgsValid", "args": {"tool": "file_read"}},
        _outcome(tool_calls=[]),
    ).passed


def test_tool_arg_non_empty():
    spec = {"name": "ToolArgNonEmpty", "args": {"tool": "escalate", "arg": "questions"}}
    # escalate 真带了结构化 questions（非空数组）→ 过
    full = '{"question": "选 A 还是 B", "questions": [{"prompt": "选哪个"}]}'
    assert _run(spec, _outcome(tool_calls=[("escalate", full)])).passed
    # 键缺失（只发了自由文本升级）→ 不过
    assert not _run(spec, _outcome(tool_calls=[("escalate", '{"question": "q"}')])).passed
    # 空数组 = 没真结构化 → 不过
    empty = '{"question": "q", "questions": []}'
    assert not _run(spec, _outcome(tool_calls=[("escalate", empty)])).passed
    # 根本没调用该工具 → 不过
    assert not _run(spec, _outcome(tool_calls=[])).passed


def test_has_citations():
    oc = _outcome(citations=[{"url": "a"}, {"url": "b"}])
    assert _run({"name": "HasCitations", "args": {"min": 2}}, oc).passed
    assert not _run({"name": "HasCitations", "args": {"min": 3}}, oc).passed


def test_delegated():
    assert _run({"name": "Delegated"}, _outcome(delegated=True)).passed
    assert not _run({"name": "Delegated"}, _outcome(delegated=False)).passed


def test_not_delegated():
    assert _run({"name": "NotDelegated"}, _outcome(delegated=False)).passed
    assert not _run({"name": "NotDelegated"}, _outcome(delegated=True)).passed


def test_roster_matches_superset():
    oc = _outcome(roster=["研究员", "撰稿人", "CEO"])
    assert _run({"name": "RosterMatches", "args": {"expected": ["研究员", "撰稿人"]}}, oc).passed
    assert not _run(
        {"name": "RosterMatches", "args": {"expected": ["研究员", "测试员"]}}, oc
    ).passed


def test_max_rounds_budget():
    assert _run({"name": "MaxRounds", "args": {"budget": 3}}, _outcome(rounds=2)).passed
    assert not _run({"name": "MaxRounds", "args": {"budget": 3}}, _outcome(rounds=5)).passed


def test_max_tool_calls_budget():
    oc = _outcome(tool_calls=[("web_search", "{}")] * 5)
    assert _run({"name": "MaxToolCalls", "args": {"budget": 5}}, oc).passed
    assert not _run({"name": "MaxToolCalls", "args": {"budget": 4}}, oc).passed


def test_no_fabrication_marker():
    oc = _outcome(content="我无法确认这个信息。")
    assert _run({"name": "NoFabricationMarker", "args": {"forbidden": ["你的猫叫"]}}, oc).passed
    hit = _outcome(content="你的猫叫咪咪。")
    assert not _run(
        {"name": "NoFabricationMarker", "args": {"forbidden": ["你的猫叫"]}}, hit
    ).passed
    # 空 forbidden 恒过
    assert _run({"name": "NoFabricationMarker"}, hit).passed


def test_content_matches():
    # 命中（正确答案出现）→ 过；未命中 → 不过
    assert _run({"name": "ContentMatches", "args": {"pattern": "541"}}, _outcome(content="第 100 个素数是 541。")).passed
    assert not _run({"name": "ContentMatches", "args": {"pattern": "541"}}, _outcome(content="答案是 540。")).passed

    # negate：要求某个错误答案**不**出现（探测「没答成简单利息 11200」）
    neg = {"name": "ContentMatches", "args": {"pattern": "11200", "negate": True}}
    assert _run(neg, _outcome(content="本息合计 11268.25 元")).passed
    assert not _run(neg, _outcome(content="本息合计 11200 元")).passed

    # flags=i 忽略大小写
    assert _run(
        {"name": "ContentMatches", "args": {"pattern": "saturday", "flags": "i"}},
        _outcome(content="It is Saturday."),
    ).passed

    # 数字 pattern 容忍真实分隔符（无 / 逗号 / LaTeX \,）—— 探针 ground-truth 的健壮性
    digit = {"name": "ContentMatches", "args": {"pattern": "15\\D{0,3}592\\D{0,3}984"}}
    for c in ["15592984", "15,592,984", r"15\,592\,984"]:
        assert _run(digit, _outcome(content=c)).passed, c

    # 坏正则不抛异常、判不过并在 detail 标注
    bad = _run({"name": "ContentMatches", "args": {"pattern": "("}}, _outcome(content="x"))
    assert not bad.passed and "bad regex" in bad.detail


def test_deliverable_integrity_omission_in_content():
    marker = "正文……（中间省略，已保留首尾）……续"
    r = _run({"name": "DeliverableIntegrity"}, _outcome(content=marker))
    assert not r.passed
    assert "omission in content" in r.detail


def test_deliverable_integrity_omission_in_file_write():
    import json

    body = "首段\n……（中间省略，已保留首尾）……\n末段"
    oc = _outcome(
        content="已落盘",
        tool_calls=[("file_write", json.dumps({"path": "report.md", "content": body}))],
    )
    r = _run({"name": "DeliverableIntegrity"}, oc)
    assert not r.passed
    assert "omission in file_write" in r.detail


def test_deliverable_integrity_severe_shrink():
    import json

    old = "x" * 1000
    new = "y" * 100  # < 60% of old → severe shrink
    oc = _outcome(
        content="ok",
        tool_calls=[
            ("file_write", json.dumps({"path": "a.md", "content": old})),
            ("file_write", json.dumps({"path": "a.md", "content": new})),
        ],
    )
    r = _run({"name": "DeliverableIntegrity"}, oc)
    assert not r.passed
    assert "severe shrink" in r.detail


def test_deliverable_integrity_clean_sample_passes():
    import json

    body = "完整报告正文，无省略标记，论证自洽。"
    oc = _outcome(
        content=body,
        tool_calls=[
            ("file_write", json.dumps({"path": "out.md", "content": body})),
            ("file_write", json.dumps({"path": "out.md", "content": body + "\n修订补一段。"})),
        ],
    )
    assert _run({"name": "DeliverableIntegrity"}, oc).passed


def test_deliverable_integrity_no_prior_draft_skips_shrink():
    """首写无旧稿：即便很短也不走 shrink 维（不误报）。"""
    import json

    oc = _outcome(
        content="短答",
        tool_calls=[("file_write", json.dumps({"path": "short.md", "content": "短"}))],
    )
    assert _run({"name": "DeliverableIntegrity"}, oc).passed


def test_registry_contains_all_documented_checks():
    expected = {
        "FinishReason",
        "NonEmpty",
        "ToolCalled",
        "ToolArgsValid",
        "ToolArgNonEmpty",
        "HasCitations",
        "Delegated",
        "RosterMatches",
        "MaxRounds",
        "NoFabricationMarker",
        "ContentMatches",
        "DeliverableIntegrity",
        "TestExitCode",
        "TestsUnchanged",
    }
    assert expected <= CHECK_NAMES


def test_test_exit_code_pass_and_fail(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "ok.py").write_text("print('hi')\n", encoding="utf-8")
    oc = _outcome(workspace_root=str(good))
    assert _run(
        {"name": "TestExitCode", "args": {"command": [sys.executable, "ok.py"]}},
        oc,
    ).passed

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "fail.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    oc2 = _outcome(workspace_root=str(bad))
    assert not _run(
        {"name": "TestExitCode", "args": {"command": [sys.executable, "fail.py"]}},
        oc2,
    ).passed
    assert not _run(
        {"name": "TestExitCode", "args": {"command": [sys.executable, "-c", "pass"]}},
        _outcome(workspace_root=None),
    ).passed


def test_tests_unchanged_detects_cheat(tmp_path):
    ref = tmp_path / "ref"
    ws = tmp_path / "ws"
    for root in (ref, ws):
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "t.py").write_text("assert True\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    # 生产代码可改
    (ws / "src" / "a.py").write_text("x=2\n", encoding="utf-8")
    oc = _outcome(workspace_root=str(ws), reference_root=str(ref))
    assert _run({"name": "TestsUnchanged", "args": {"paths": ["tests"]}}, oc).passed
    # 改测 = 作弊
    (ws / "tests" / "t.py").write_text("assert False\n", encoding="utf-8")
    assert not _run({"name": "TestsUnchanged", "args": {"paths": ["tests"]}}, oc).passed


def test_tests_unchanged_allow_extra_golden(tmp_path):
    """Extend：追加 GOLDEN 测文件可白名单；仍禁改 upstream 测。"""
    ref = tmp_path / "ref"
    ws = tmp_path / "ws"
    for root in (ref, ws):
        (root / "tests").mkdir(parents=True)
        (root / "tests" / "t.py").write_text("assert True\n", encoding="utf-8")
    golden = "tests/test_agentcore_extend_x.py"
    (ws / "tests" / "test_agentcore_extend_x.py").write_text("assert 1\n", encoding="utf-8")
    oc = _outcome(workspace_root=str(ws), reference_root=str(ref))
    # 无白名单 → extra 失败
    assert not _run({"name": "TestsUnchanged", "args": {"paths": ["tests"]}}, oc).passed
    # 白名单 → 过
    assert _run(
        {
            "name": "TestsUnchanged",
            "args": {"paths": ["tests"], "allow_extra": [golden]},
        },
        oc,
    ).passed
    # 改 upstream 仍失败
    (ws / "tests" / "t.py").write_text("assert False\n", encoding="utf-8")
    assert not _run(
        {
            "name": "TestsUnchanged",
            "args": {"paths": ["tests"], "allow_extra": [golden]},
        },
        oc,
    ).passed

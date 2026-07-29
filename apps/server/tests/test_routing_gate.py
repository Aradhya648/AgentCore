"""Worker 内部路由 Phase 1 — Escalation Gate。"""

from __future__ import annotations

from agentcore.runtime.loop_controller import ToolAttempt
from agentcore.runtime.routing import (
    EscalationKind,
    ProblemLayer,
    classify_problem,
    evaluate_after_tools,
    signals_as_dicts,
)


def test_execution_layer_tool_failure_continues():
    attempts = [ToolAttempt("fp1", "code_execute", success=False)]
    outputs = ["Traceback (most recent call last):\nFileNotFoundError: No such file"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs, run_id="r1")
    assert verdict.layer is ProblemLayer.EXECUTION
    assert verdict.action == "continue"
    assert not verdict.should_escalate
    assert verdict.signals == []


def test_scheme_contract_escalates():
    attempts = [ToolAttempt("fp1", "file_write", success=False)]
    outputs = ["继续执行会破坏对外契约 / 改接口契约，超出权限"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs, run_id="r1")
    assert verdict.should_escalate
    assert verdict.layer is ProblemLayer.SCHEME
    assert len(verdict.signals) == 1
    assert verdict.signals[0].kind is EscalationKind.CONTRACT
    assert "契约" in verdict.signals[0].question or "权限" in verdict.signals[0].question


def test_scheme_contradiction_escalates():
    attempts = [ToolAttempt("fp1", "str_replace", success=True)]
    outputs = ["需求矛盾：无法同时满足 A 与 B"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.CONTRADICTION


def test_scheme_dep_escalates():
    attempts = [ToolAttempt("fp1", "str_replace", success=False)]
    outputs = ["卡在缺输入：依赖不存在，还没人产出"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.DEP


def test_file_read_corpus_with_contradict_does_not_escalate():
    """工作区正文含裸词 contradict / 需求矛盾 ≠ 本任务矛盾（与 web_search 同理）。"""
    attempts = [ToolAttempt("fp1", "file_read", success=True)]
    outputs = [
        "// courtroom: the witness may contradict earlier testimony\n"
        "export function noteContradict() { /* 需求矛盾仅作剧情文案 */ }"
    ]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs, run_id="r1")
    assert not verdict.should_escalate
    assert verdict.layer is ProblemLayer.EXECUTION


def test_grep_corpus_with_scheme_phrase_does_not_escalate():
    attempts = [ToolAttempt("fp1", "grep", success=True)]
    outputs = ["src/a.ts:12: 无法同时满足 A 与 B（剧情选项）"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert not verdict.should_escalate


def test_code_search_corpus_with_scope_phrase_does_not_escalate():
    attempts = [ToolAttempt("fp1", "code_search", success=True)]
    outputs = ["hit: out of scope comment in legacy module"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert not verdict.should_escalate


def test_bare_contradict_in_tool_output_does_not_escalate():
    """裸词 contradict 不再当方案层；须任务口语短语。"""
    attempts = [ToolAttempt("fp1", "str_replace", success=True)]
    outputs = ["note: do not contradict the prior patch style"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert not verdict.should_escalate


def test_requirements_contradict_phrase_still_escalates():
    attempts = [ToolAttempt("fp1", "str_replace", success=True)]
    outputs = ["these requirements contradict each other; cannot ship both"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.CONTRADICTION


def test_escalate_tool_skipped():
    attempts = [ToolAttempt("fp1", "escalate", success=True)]
    outputs = ["需求矛盾：故意写在 escalate 结果里也不该再 Gate"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert not verdict.should_escalate


def test_classify_problem_helpers():
    assert classify_problem("ModuleNotFoundError: x") is ProblemLayer.EXECUTION
    assert classify_problem("超出权限，需改接口契约") is ProblemLayer.SCHEME


def test_signals_wire_kind_maps_contract_to_scope():
    attempts = [ToolAttempt("fp1", "file_write", success=False)]
    outputs = ["breaking change to api contract"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    payloads = signals_as_dicts(verdict.signals)
    assert payloads[0]["kind"] == "scope"  # wire for CEO/wave
    assert payloads[0]["gate_kind"] == "contract"
    assert payloads[0]["source"] == "escalation_gate"
    assert payloads[0]["layer"] == "scheme"


def test_scheme_scope_escalates():
    attempts = [ToolAttempt("fp1", "file_write", success=True)]
    outputs = ["职责偏离：真正该做的是改文档而非改代码"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs, run_id="r1")
    assert verdict.should_escalate
    assert verdict.layer is ProblemLayer.SCHEME
    assert verdict.signals[0].kind is EscalationKind.SCOPE
    assert "职责" in verdict.signals[0].question or "范围" in verdict.signals[0].question


def test_scheme_scope_english_wrong_scope():
    attempts = [ToolAttempt("fp1", "str_replace", success=False)]
    outputs = ["this is the wrong scope for the worker"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.SCOPE


def test_coordination_tools_skipped_even_with_scheme_text():
    for name in ("post_note", "read_notes", "amend_note", "handoff", "delegate"):
        attempts = [ToolAttempt("fp1", name, success=False)]
        outputs = ["需求矛盾：故意写在协调工具结果里"]
        verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
        assert not verdict.should_escalate, name


def test_web_search_snippet_with_contradiction_does_not_escalate():
    """检索原文含「互相矛盾」≠ 任务本身矛盾 —— 勿误触 Escalation Gate。"""
    attempts = [ToolAttempt("fp1", "web_search", success=True)]
    outputs = [
        "标题：两派观点互相矛盾 / 冲突的要求无法同时满足\n"
        "摘要：报道称双方需求矛盾，无法同时满足 A 与 B。"
    ]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs, run_id="r1")
    assert not verdict.should_escalate
    assert verdict.layer is ProblemLayer.EXECUTION
    assert verdict.action == "continue"


def test_read_url_body_with_scope_phrase_does_not_escalate():
    attempts = [ToolAttempt("fp1", "read_url", success=True)]
    outputs = ["网页正文：有人认为这是职责偏离、与初始计划不符，属于 out of scope。"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert not verdict.should_escalate


def test_non_retrieval_tool_with_contradiction_still_escalates():
    """非语料工具输出仍可触发方案层（回归：跳过仅限语料类输出）。"""
    attempts = [ToolAttempt("fp1", "str_replace", success=True)]
    outputs = ["需求矛盾：无法同时满足 A 与 B"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.CONTRADICTION
    assert verdict.signals[0].tool_name == "str_replace"


def test_mixed_attempts_only_scheme_tools_escalate():
    attempts = [
        ToolAttempt("fp1", "code_execute", success=False),
        ToolAttempt("fp2", "file_write", success=False),
    ]
    outputs = [
        "Traceback (most recent call last):\nFileNotFoundError: No such file",
        "继续执行会破坏对外契约",
    ]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert len(verdict.signals) == 1
    assert verdict.signals[0].kind is EscalationKind.CONTRACT
    assert verdict.signals[0].tool_name == "file_write"


def test_failure_without_output_stays_execution():
    """Failed attempt + missing output → execution continue (never silent scheme escalate)."""
    attempts = [ToolAttempt("fp1", "code_execute", success=False)]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=None)
    assert verdict.layer is ProblemLayer.EXECUTION
    assert verdict.action == "continue"
    assert not verdict.should_escalate


def test_classify_problem_scope_and_unknown_bias_execution():
    assert classify_problem("范围不对，与初始计划不符") is ProblemLayer.SCHEME
    assert classify_problem("completely opaque gibberish xyz") is ProblemLayer.EXECUTION


def test_out_of_scope_phrase_classifies_as_scope():
    """Regression: ``out of scope`` used to be double-listed in the CONTRACT pattern
    (first match won) and got mis-labeled ``gate_kind=contract``. Scope-flavored
    wording must yield SCOPE; genuinely contract-flavored wording stays CONTRACT."""
    attempts = [ToolAttempt("fp1", "file_write", success=False)]
    outputs = ["this change is out of scope for the worker"]
    verdict = evaluate_after_tools(attempts=attempts, tool_outputs=outputs)
    assert verdict.should_escalate
    assert verdict.signals[0].kind is EscalationKind.SCOPE
    payloads = signals_as_dicts(verdict.signals)
    assert payloads[0]["kind"] == "scope"
    assert payloads[0]["gate_kind"] == "scope"


def test_contract_context_phrases_still_classify_as_contract():
    for text in (
        "this is a breaking change to the api contract",
        "that is beyond my authority",
        "违反接口契约，接口不兼容",
    ):
        attempts = [ToolAttempt("fp1", "file_write", success=False)]
        verdict = evaluate_after_tools(attempts=attempts, tool_outputs=[text])
        assert verdict.should_escalate, text
        assert verdict.signals[0].kind is EscalationKind.CONTRACT, text

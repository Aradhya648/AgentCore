"""MAST 离线评测集自测（学·度量 §2.5：按 MAST 14 类打标签的多 Agent 评测集）.

零 LLM、零真模型：只验证「打标签 + 聚合」这套机器本身——MAST 分类法完整、用例的 ``mast``
标签合法且三组齐备、report 按组/类聚合正确。真模型回合（出 pass_rate 数字）是 nightly、需
``EVAL_DEEPSEEK_API_KEY``，不在本测范围。
"""

from __future__ import annotations

from agentcore.evals.mast import (
    MAST_CODES,
    MAST_GROUPS,
    MAST_MODES,
    group_of,
    is_valid_mast_code,
    label_of,
)
from agentcore.evals.report import format_report, mast_breakdown, report_to_dict
from agentcore.evals.runner import load_cases
from agentcore.evals.seed_lint import lint_case
from agentcore.evals.types import CaseReport, CheckOutcome, EvalReport, TurnOutcome

# --- 分类法本身 --------------------------------------------------------------


def test_mast_taxonomy_has_14_modes_in_3_groups():
    # MAST = 14 类 / 三大组，组内数 5/6/3（与论文逐条对齐）。键 = 码、且 mode.code 自洽。
    assert len(MAST_MODES) == 14
    assert len(MAST_CODES) == 14
    assert set(MAST_GROUPS) == {"FC1", "FC2", "FC3"}
    for code, mode in MAST_MODES.items():
        assert mode.code == code
        assert mode.group in MAST_GROUPS
        assert group_of(code) == mode.group
    sizes = {g: sum(1 for m in MAST_MODES.values() if m.group == g) for g in MAST_GROUPS}
    assert sizes == {"FC1": 5, "FC2": 6, "FC3": 3}


def test_mast_helpers():
    assert is_valid_mast_code("1.3") is True
    assert is_valid_mast_code("9.9") is False
    assert group_of("3.1") == "FC3"
    assert group_of("9.9") is None
    assert label_of("1.3") == "1.3 步骤重复"
    assert label_of("9.9") == "9.9"  # 未知码原样返回


# --- 标签校验（seed_lint） ----------------------------------------------------


def _base_case(**extra) -> dict:
    raw = {"id": "x", "category": "team", "user_message": "q", "checks": [{"name": "FinishReason"}]}
    raw.update(extra)
    return raw


def test_lint_accepts_valid_mast_code():
    assert lint_case(_base_case(mast="2.3")) == []


def test_lint_rejects_unknown_mast_code():
    errors = lint_case(_base_case(mast="9.9"))
    assert any("mast" in e for e in errors)


def test_lint_allows_absent_mast():
    # 非 MAST 套件（core/routing）不挂标签——平凡通过，不强制。
    assert lint_case(_base_case()) == []


# --- 按 MAST 组/类聚合（report） ---------------------------------------------


def _case_report(cid: str, code: str | None, passed: bool) -> CaseReport:
    outcome = TurnOutcome(
        content="ok" if passed else "",
        finish_reason="end_turn" if passed else "error",
        rounds=1,
        error=None if passed else "x",
    )
    return CaseReport(
        case_id=cid,
        category="team",
        outcome=outcome,
        checks=[CheckOutcome("FinishReason", passed)],
        mast=code,
    )


def _labeled_report() -> EvalReport:
    return EvalReport(
        cases=[
            _case_report("a", "1.3", True),
            _case_report("b", "1.5", False),
            _case_report("c", "2.3", True),
            _case_report("d", None, True),  # 无标签：完全不计入 MAST 聚合
        ]
    )


def test_mast_breakdown_aggregates_by_group_and_mode():
    mb = mast_breakdown(_labeled_report())
    # FC1 两条（1.3 过 / 1.5 挂）→ 1/2；FC2 一条（2.3 过）→ 1/1；无 FC3 标签。
    assert mb["by_group"]["FC1"] == {"total": 2, "passed": 1, "pass_rate": 0.5}
    assert mb["by_group"]["FC2"] == {"total": 1, "passed": 1, "pass_rate": 1.0}
    assert "FC3" not in mb["by_group"]
    assert mb["by_mode"]["1.3"]["pass_rate"] == 1.0
    assert mb["by_mode"]["1.5"]["pass_rate"] == 0.0
    # 无标签用例 d 被完全排除（总计 3 而非 4）。
    assert sum(b["total"] for b in mb["by_group"].values()) == 3


def test_report_to_dict_carries_mast_and_format_shows_section():
    report = _labeled_report()
    data = report_to_dict(report)
    assert data["summary"]["by_mast"]["by_group"]["FC1"]["total"] == 2
    assert next(c for c in data["cases"] if c["case_id"] == "a")["mast"] == "1.3"
    text = format_report(report)
    assert "MAST 失败标签通过率" in text
    assert "步骤重复" in text  # label_of 渲染到逐类行


def test_format_report_omits_mast_section_when_unlabeled():
    outcome = TurnOutcome(content="ok", finish_reason="end_turn", rounds=1)
    report = EvalReport(
        cases=[
            CaseReport(
                case_id="x",
                category="qa",
                outcome=outcome,
                checks=[CheckOutcome("FinishReason", True)],
            )
        ]
    )
    assert "MAST 失败标签通过率" not in format_report(report)


# --- 评测集本身（数据） ------------------------------------------------------


def test_mast_suite_cases_are_clean_labeled_and_cover_all_groups():
    # load_cases 先 lint 再解析：能返回即证明整套结构合法（含 mast 码合法）。再断言每条都挂了
    # 合法标签、且三大组齐备（评测集真覆盖 MAST 全谱、不偏科）。
    cases = load_cases(suite="mast")
    assert cases, "mast 套件不应为空"
    for c in cases:
        assert c.mast in MAST_CODES, f"{c.id} 的 mast 标签非法/缺失: {c.mast!r}"
    assert {group_of(c.mast) for c in cases} == {"FC1", "FC2", "FC3"}

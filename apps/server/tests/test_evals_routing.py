"""路由准确率聚合 + 路由用例 lint 的确定性单测（方向③，零 LLM）.

聚合器（``routing.py``）的混淆矩阵 / 比率全是纯算术，用合成 ``CaseReport`` 直接喂、断言数值；
新增的 routing-用例 lint 规则（``seed_lint.py``）也在此守。**度量本身**需真模型 CEO 回合
（属已延后的 eval 主线），不在本测覆盖——这里只证「跑完之后怎么算 / 用例标签合法性」这层。
"""

from __future__ import annotations

import pytest

from agentcore.evals.routing import (
    RoutingMetrics,
    format_routing_report,
    routing_metrics,
    routing_metrics_to_dict,
)
from agentcore.evals.runner import load_cases
from agentcore.evals.seed_lint import lint_case
from agentcore.evals.types import CaseReport, CheckOutcome, TurnOutcome


def _report(cid: str, *, expected: bool, observed: bool, error: str | None = None) -> CaseReport:
    """合成一条带路由标签的 CaseReport：expected 经 Delegated/NotDelegated 这个 check 名编码。"""
    label = "Delegated" if expected else "NotDelegated"
    return CaseReport(
        case_id=cid,
        category="routing",
        outcome=TurnOutcome(
            content="",
            finish_reason="end_turn",
            rounds=1,
            delegated=observed,
            error=error,
        ),
        checks=[CheckOutcome(name=label, passed=(observed == expected))],
    )


def test_confusion_matrix_counts_each_quadrant() -> None:
    reports = [
        _report("tp", expected=True, observed=True),
        _report("fn", expected=True, observed=False),
        _report("fp", expected=False, observed=True),
        _report("tn", expected=False, observed=False),
    ]
    m = routing_metrics(reports)
    assert (m.tp, m.fn, m.fp, m.tn, m.total) == (1, 1, 1, 1, 4)
    assert m.accuracy == pytest.approx(0.5)
    assert m.precision == pytest.approx(0.5)
    assert m.recall == pytest.approx(0.5)
    assert m.f1 == pytest.approx(0.5)
    assert m.over_delegation_rate == pytest.approx(0.5)
    assert m.under_delegation_rate == pytest.approx(0.5)
    # 只有 FP / FN 进 misroutes，TP / TN 不进。
    assert sorted(cid for cid, _, _ in m.misroutes) == ["fn", "fp"]


def test_business_rates_isolate_over_vs_under_delegation() -> None:
    # 3 TP, 1 FN, 2 TN, 0 FP：召回欠一点、过度编排为零。
    reports = [
        _report("d1", expected=True, observed=True),
        _report("d2", expected=True, observed=True),
        _report("d3", expected=True, observed=True),
        _report("d4_missed", expected=True, observed=False),
        _report("s1", expected=False, observed=False),
        _report("s2", expected=False, observed=False),
    ]
    m = routing_metrics(reports)
    assert m.precision == pytest.approx(1.0)  # 委派的全对（无 FP）
    assert m.recall == pytest.approx(0.75)  # 4 个该委派的漏了 1
    assert m.over_delegation_rate == pytest.approx(0.0)  # 该自答的没一个被过度拆
    assert m.under_delegation_rate == pytest.approx(0.25)  # 该委派的 1/4 被自己做了
    assert m.accuracy == pytest.approx(5 / 6)


def test_errored_case_excluded_from_matrix_but_counted() -> None:
    reports = [
        _report("ok", expected=True, observed=True),
        _report("boom", expected=True, observed=False, error="provider exploded"),
    ]
    m = routing_metrics(reports)
    assert m.errors == 1
    assert m.total == 1  # errored 不计入混淆矩阵
    assert (m.tp, m.fn) == (1, 0)  # boom 没被算成 FN
    assert m.recall == pytest.approx(1.0)


def test_unlabeled_report_is_skipped() -> None:
    unlabeled = CaseReport(
        case_id="qa1",
        category="qa",
        outcome=TurnOutcome(content="", finish_reason="end_turn", rounds=1, delegated=False),
        checks=[CheckOutcome(name="FinishReason", passed=True)],
    )
    m = routing_metrics([unlabeled, _report("tp", expected=True, observed=True)])
    assert m.total == 1  # 只算了带标签那条


def test_empty_metrics_are_none_not_zero() -> None:
    m = routing_metrics([])
    assert m.total == 0
    assert m.accuracy is None
    assert m.precision is None
    assert m.recall is None
    assert m.f1 is None
    assert m.over_delegation_rate is None
    assert m.under_delegation_rate is None


def test_metrics_to_dict_is_json_shaped() -> None:
    m = routing_metrics([_report("fp", expected=False, observed=True)])
    d = routing_metrics_to_dict(m)
    assert d["confusion"] == {"tp": 0, "fp": 1, "fn": 0, "tn": 0}
    assert d["over_delegation_rate"] == pytest.approx(1.0)
    assert d["misroutes"] == [
        {"case_id": "fp", "expected_delegate": False, "observed_delegate": True}
    ]


def test_format_report_renders_matrix_and_misroutes() -> None:
    m = routing_metrics(
        [
            _report("tp", expected=True, observed=True),
            _report("over", expected=False, observed=True),
        ]
    )
    text = format_routing_report(m)
    assert "路由准确率" in text
    assert "过度编排" in text
    assert "over" in text  # 错判逐条列出


# --- 新增 lint 规则：category=routing 须恰好一个标签 + path=team ---


def _routing_raw(**overrides: object) -> dict:
    raw = {
        "id": "r1",
        "category": "routing",
        "user_message": "u",
        "path": "team",
        "checks": [{"name": "Delegated"}],
        "rubric": "r",
    }
    raw.update(overrides)
    return raw


def test_lint_routing_ok_with_single_label_and_team() -> None:
    assert lint_case(_routing_raw()) == []
    assert lint_case(_routing_raw(checks=[{"name": "NotDelegated"}])) == []


def test_lint_routing_rejects_missing_label() -> None:
    errs = lint_case(_routing_raw(checks=[{"name": "FinishReason"}]))
    assert any("恰好声明" in e for e in errs)


def test_lint_routing_rejects_both_labels() -> None:
    errs = lint_case(_routing_raw(checks=[{"name": "Delegated"}, {"name": "NotDelegated"}]))
    assert any("恰好声明" in e for e in errs)


def test_lint_routing_rejects_single_path() -> None:
    errs = lint_case(_routing_raw(path="single"))
    assert any("path='team'" in e for e in errs)


def test_non_routing_category_unaffected_by_label_rule() -> None:
    raw = {
        "id": "qa1",
        "category": "qa",
        "user_message": "u",
        "path": "team",
        "checks": [{"name": "FinishReason"}],
        "rubric": "r",
    }
    assert lint_case(raw) == []


def test_seeded_routing_suite_loads_and_lints_clean() -> None:
    cases = load_cases(suite="routing")
    assert len(cases) >= 6
    assert all(c.category == "routing" and c.path == "team" for c in cases)
    # 每条恰好一个路由标签（与聚合器单一标签源契约一致）。
    for c in cases:
        names = {spec["name"] for spec in c.checks}
        assert len(names & {"Delegated", "NotDelegated"}) == 1


def test_routing_metrics_dataclass_defaults() -> None:
    m = RoutingMetrics()
    assert (m.tp, m.fp, m.fn, m.tn, m.total, m.errors) == (0, 0, 0, 0, 0, 0)
    assert m.misroutes == []

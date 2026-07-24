"""裁判校准回路单测（后端架构.md §五）.

三层零真实 LLM 验证：
1. 纯统计（Cohen's kappa / 二次加权 kappa / Spearman）对教科书值；
2. gold-set 加载器对结构错误的早失败；
3. ``calibrate`` 用脚本化假裁判验证判↔人一致度聚合、kappa 门、分歧排序、偏置。

真模型留给手动 / 夜跑校准。
"""

import asyncio
import json

import pytest

from agentcore.evals.calibration import (
    CalibrationMetrics,
    GoldLabel,
    JudgeOnLabel,
    calibrate,
    calibration_to_dict,
    cohens_kappa,
    format_calibration_report,
    load_gold_set,
    quadratic_weighted_kappa,
    spearman_rho,
)
from agentcore.evals.types import EvalConfigError, JudgeVerdict

# --- 脚本化假裁判（实现 Judge 协议，零 LLM）---------------------------------


class _ScriptedJudge:
    """按 ``case.id`` 返回预设分，模拟裁判对每条 gold 答案的打分。"""

    def __init__(self, scores: dict[str, float], *, threshold: float = 4.0) -> None:
        self._scores = scores
        self._t = threshold

    async def score(self, case, outcome):  # noqa: ANN001
        s = self._scores[case.id]
        return JudgeVerdict(score=s, passed=s >= self._t, rationale=f"scripted {s}")


def _label(cid: str, human: float, *, human_pass: bool | None = None) -> GoldLabel:
    return GoldLabel(
        id=cid,
        user_message="q",
        rubric="好不好",
        answer="答案",
        human_score=human,
        human_pass=human_pass,
    )


# --- 纯统计：Cohen's kappa ---------------------------------------------------


def test_cohens_kappa_textbook_value():
    # 经典 2x2：both-yes=20, r1yes/r2no=5, r1no/r2yes=10, both-no=15 → kappa=0.4
    a = [1] * 20 + [1] * 5 + [0] * 10 + [0] * 15
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert abs(cohens_kappa(a, b) - 0.4) < 1e-9


def test_cohens_kappa_perfect_agreement():
    assert cohens_kappa([1, 0, 1, 1, 0], [1, 0, 1, 1, 0]) == 1.0


def test_cohens_kappa_total_disagreement_is_zero_not_negative_floor():
    # 全反但两类边际不重叠 → pe=0、po=0 → kappa=0.0
    assert cohens_kappa([1, 1, 1, 1], [0, 0, 0, 0]) == 0.0


def test_cohens_kappa_inverted_binary_is_minus_one():
    a = [1, 1, 1, 0, 0, 0]
    b = [0, 0, 0, 1, 1, 1]
    assert abs(cohens_kappa(a, b) - (-1.0)) < 1e-9


def test_cohens_kappa_degenerate_constant_perfect():
    # 两序均常量且相等 → pe>=1 分支 → 完全一致 1.0
    assert cohens_kappa([2, 2, 2], [2, 2, 2]) == 1.0


def test_cohens_kappa_length_mismatch_raises():
    with pytest.raises(ValueError):
        cohens_kappa([1, 2], [1])


# --- 纯统计：二次加权 kappa --------------------------------------------------


def test_qwk_perfect_agreement():
    assert quadratic_weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0


def test_qwk_equals_cohens_on_binary():
    # 二分（档 {1,2}）上 QWK 应与无加权 Cohen's kappa 等价（均为 0.4）
    a = [2] * 20 + [2] * 5 + [1] * 10 + [1] * 15
    b = [2] * 20 + [1] * 5 + [2] * 10 + [1] * 15
    qwk = quadratic_weighted_kappa(a, b, max_cat=2)
    assert abs(qwk - 0.4) < 1e-9
    assert abs(qwk - cohens_kappa(a, b)) < 1e-9


def test_qwk_chance_level_is_zero():
    # [1,1,2,2] vs [1,2,1,2]（档 {1,2}）= 完全偶然 → 0.0
    assert abs(quadratic_weighted_kappa([1, 1, 2, 2], [1, 2, 1, 2], max_cat=2)) < 1e-9


def test_qwk_clamps_out_of_range_scores():
    # 解析失败的 0 压到档 1，不抛错；与显式 1 等价
    assert quadratic_weighted_kappa([0, 5], [1, 5]) == 1.0


# --- 纯统计：Spearman --------------------------------------------------------


def test_spearman_perfect_monotonic():
    assert abs(spearman_rho([1, 2, 3], [10, 20, 30]) - 1.0) < 1e-9


def test_spearman_perfect_inverse():
    assert abs(spearman_rho([1, 2, 3], [30, 20, 10]) - (-1.0)) < 1e-9


def test_spearman_known_value():
    # d^2=4, n=5 → rho = 1 - 6*4/(5*24) = 0.8
    assert abs(spearman_rho([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) - 0.8) < 1e-9


def test_spearman_zero_variance_returns_zero():
    assert spearman_rho([1, 1, 1], [1, 2, 3]) == 0.0


# --- gold-set 加载 -----------------------------------------------------------


def _write(tmp_path, payload) -> str:
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_gold_set_ok(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "a", "user_message": "q", "rubric": "r", "answer": "x", "human_score": 5}],
    )
    labels = load_gold_set(path)
    assert len(labels) == 1
    assert labels[0].id == "a"
    assert labels[0].human_score == 5.0
    assert labels[0].human_pass is None  # 未给则保留 None（由阈值推导）


def test_load_gold_set_missing_field_raises(tmp_path):
    path = _write(tmp_path, [{"id": "a", "user_message": "q", "rubric": "r", "human_score": 5}])
    with pytest.raises(EvalConfigError, match="缺字段"):
        load_gold_set(path)


def test_load_gold_set_score_out_of_range_raises(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "a", "user_message": "q", "rubric": "r", "answer": "x", "human_score": 6}],
    )
    with pytest.raises(EvalConfigError, match="1–5"):
        load_gold_set(path)


def test_load_gold_set_non_numeric_score_raises(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "a", "user_message": "q", "rubric": "r", "answer": "x", "human_score": "好"}],
    )
    with pytest.raises(EvalConfigError, match="非数值"):
        load_gold_set(path)


def test_load_gold_set_empty_answer_raises(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "a", "user_message": "q", "rubric": "r", "answer": "   ", "human_score": 4}],
    )
    with pytest.raises(EvalConfigError, match="answer"):
        load_gold_set(path)


def test_load_gold_set_duplicate_id_raises(tmp_path):
    path = _write(
        tmp_path,
        [
            {"id": "a", "user_message": "q", "rubric": "r", "answer": "x", "human_score": 5},
            {"id": "a", "user_message": "q", "rubric": "r", "answer": "y", "human_score": 3},
        ],
    )
    with pytest.raises(EvalConfigError, match="id 重复"):
        load_gold_set(path)


def test_load_gold_set_not_a_list_raises(tmp_path):
    path = _write(tmp_path, {"id": "a"})
    with pytest.raises(EvalConfigError, match="数组"):
        load_gold_set(path)


def test_load_gold_set_empty_list_raises(tmp_path):
    path = _write(tmp_path, [])
    with pytest.raises(EvalConfigError, match="为空"):
        load_gold_set(path)


def test_load_gold_set_missing_file_raises(tmp_path):
    with pytest.raises(EvalConfigError, match="不存在"):
        load_gold_set(str(tmp_path / "nope.json"))


# --- calibrate（脚本化假裁判）-----------------------------------------------


def test_calibrate_perfect_agreement_is_trustworthy():
    labels = [_label(f"c{i}", h) for i, h in enumerate([5, 4, 4, 2, 1, 3])]
    judge = _ScriptedJudge({lb.id: lb.human_score for lb in labels})
    m = asyncio.run(calibrate(judge, labels, kappa_gate=0.6))
    assert m.n == 6
    assert m.cohens_kappa == 1.0
    assert m.weighted_kappa == 1.0
    assert abs(m.spearman - 1.0) < 1e-9
    assert m.raw_agreement == 1.0
    assert m.mean_bias == 0.0
    assert m.disagreements == []
    assert m.trustworthy is True


def test_calibrate_inverted_judge_not_trustworthy_and_lists_disagreements():
    labels = [_label(f"c{i}", h) for i, h in enumerate([5, 5, 5, 1, 1, 1])]
    inverted = {f"c{i}": s for i, s in enumerate([1, 1, 1, 5, 5, 5])}
    judge = _ScriptedJudge(inverted)
    m = asyncio.run(calibrate(judge, labels, kappa_gate=0.6))
    assert abs(m.cohens_kappa - (-1.0)) < 1e-9
    assert m.trustworthy is False
    assert len(m.disagreements) == 6  # 每条 pass/fail 都反了


def test_calibrate_detects_systematic_lenience_bias():
    # 裁判一律比人高 1 分 → mean_bias=+1.0（偏宽松）
    labels = [_label(f"c{i}", h) for i, h in enumerate([3, 3, 2, 2])]
    judge = _ScriptedJudge({f"c{i}": h + 1 for i, h in enumerate([3, 3, 2, 2])})
    m = asyncio.run(calibrate(judge, labels))
    assert m.mean_bias == 1.0


def test_calibrate_respects_explicit_human_pass():
    # human_score=3（<4 阈值）但显式 human_pass=True → 该条人判过
    labels = [_label("c0", 3, human_pass=True)]
    judge = _ScriptedJudge({"c0": 5})  # 判过
    m = asyncio.run(calibrate(judge, labels))
    assert m.per_label[0].human_pass is True
    assert m.per_label[0].judge_pass is True


def test_calibrate_empty_raises():
    judge = _ScriptedJudge({})
    with pytest.raises(EvalConfigError):
        asyncio.run(calibrate(judge, []))


def test_calibrate_disagreements_sorted_by_score_gap_desc():
    labels = [_label("near", 4), _label("far", 1)]
    # near：人 4(过) vs 判 3(否) 差 1；far：人 1(否) vs 判 5(过) 差 4
    judge = _ScriptedJudge({"near": 3, "far": 5})
    m = asyncio.run(calibrate(judge, labels))
    ids = [x.id for x in m.disagreements]
    assert ids == ["far", "near"]  # 差距大的在前


# --- 序列化 + 报告 -----------------------------------------------------------


def test_calibration_to_dict_shape():
    m = CalibrationMetrics(
        pass_threshold=4.0,
        kappa_gate=0.6,
        per_label=[JudgeOnLabel("a", 5, 2, True, False, "r")],
    )
    d = calibration_to_dict(m)
    assert set(d) >= {
        "n",
        "cohens_kappa",
        "weighted_kappa",
        "spearman",
        "raw_agreement",
        "mean_bias",
        "trustworthy",
        "disagreements",
    }
    assert d["n"] == 1
    assert d["trustworthy"] is False
    assert d["disagreements"][0]["id"] == "a"


def test_format_calibration_report_contains_verdict_and_metric_names():
    m = CalibrationMetrics(
        pass_threshold=4.0,
        kappa_gate=0.6,
        per_label=[JudgeOnLabel("a", 5, 5, True, True, "r")],
    )
    text = format_calibration_report(m)
    assert "Cohen" in text
    assert "可信" in text

"""辩论收敛校准自测（§三 · per-PR 零 LLM 硬门禁）。

用**脚本化假 provider**零成本验证：① 合成场景集结构合法且两侧均衡；② lint 挡住各类带病场景；
③ 度量计算正确（过保守率 / 过早收敛率 / kappa / 分歧排序）——含对真实 :data:`SCENARIOS` 走一遍
生产 `_judge` 路径（oracle 假 provider）确保不崩、金标自洽。真模型出数留给手动 / nightly。
"""

import asyncio
import json

import pytest

from agentcore.evals.debate_converge import (
    SCENARIOS,
    ConvergeScenario,
    debate_converge_to_dict,
    format_debate_converge_report,
    lint_scenarios,
    run_debate_converge,
)
from agentcore.evals.types import EvalConfigError
from agentcore.llm.provider.protocol import LLMResponse
from agentcore.runtime.debate.types import (
    STOP_FOCUS_CLARIFIED,
    DebateForm,
    DebateSide,
    SideTurn,
)

# --- 脚本化假 provider ------------------------------------------------------


class _FixedJudge:
    """每次裁判调用都返回同一个 converged（测退化混淆矩阵：全收敛 / 全继续）。"""

    def __init__(self, converged: bool) -> None:
        self._converged = converged
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        self.calls += 1
        payload = {
            "real_clash": True,
            "new_arguments": not self._converged,
            "converged": self._converged,
            "stop_reason": "converged" if self._converged else "",
            "rationale": "fixed",
        }
        return LLMResponse(content=json.dumps(payload))


class _ByIndexJudge:
    """按调用序返回脚本化 converged（runner 每场景恰调一次 `_judge`）——测精确混淆矩阵。"""

    def __init__(self, flags: list[bool]) -> None:
        self._flags = flags
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        conv = self._flags[self.calls]
        self.calls += 1
        payload = {
            "real_clash": True,
            "new_arguments": not conv,
            "converged": conv,
            "stop_reason": "converged" if conv else "",
            "rationale": f"scripted#{self.calls - 1}",
        }
        return LLMResponse(content=json.dumps(payload))


def _mk(
    cid: str,
    *,
    expect_converge: bool,
    form: DebateForm = DebateForm.DEBATE,
    round_no: int = 1,
    max_rounds: int = 5,
    sides: tuple[DebateSide, ...] | None = None,
    turns: tuple[SideTurn, ...] | None = None,
    expect_stop: str = "",
) -> ConvergeScenario:
    sides = sides or (
        DebateSide(key="pro", name="正方", stance="p"),
        DebateSide(key="con", name="反方", stance="c"),
    )
    turns = turns or (
        SideTurn("pro", "正方", "pro_t", "正方发言"),
        SideTurn("con", "反方", "con_t", "反方发言"),
    )
    return ConvergeScenario(
        id=cid,
        form=form,
        motion="m",
        sides=sides,
        focus="f",
        round_no=round_no,
        max_rounds=max_rounds,
        thorough=True,
        turns=turns,
        expect_converge=expect_converge,
        why="金标理由",
        expect_stop=expect_stop,
    )


def _balanced() -> tuple[ConvergeScenario, ...]:
    return (
        _mk("c1", expect_converge=True),
        _mk("c2", expect_converge=True),
        _mk("t1", expect_converge=False),
        _mk("t2", expect_converge=False),
    )


# --- 场景集结构 / lint ------------------------------------------------------


def test_real_scenarios_lint_ok_and_balanced():
    """内置场景集结构合法、两侧均衡（各 >= 2）、id 唯一。"""
    lint_scenarios(SCENARIOS)  # 不 raise
    ids = [s.id for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert sum(1 for s in SCENARIOS if s.expect_converge) >= 2
    assert sum(1 for s in SCENARIOS if not s.expect_converge) >= 2


def test_lint_rejects_duplicate_id():
    dup = (*_balanced(), _mk("c1", expect_converge=False))
    with pytest.raises(EvalConfigError, match="id 重复"):
        lint_scenarios(dup)


def test_lint_rejects_round_no_out_of_range():
    bad = (_mk("x", expect_converge=True, round_no=4, max_rounds=2), *_balanced())
    with pytest.raises(EvalConfigError, match="round_no"):
        lint_scenarios(bad)


def test_lint_rejects_redteam_without_subject():
    # 红队形态却无 is_subject 方（两方都不是被审方案方）。
    sides = (
        DebateSide(key="a", name="红队1", stance="attack"),
        DebateSide(key="b", name="红队2", stance="attack"),
    )
    turns = (SideTurn("a", "红队1", "a_t", "攻"), SideTurn("b", "红队2", "b_t", "攻"))
    bad = (
        _mk("rt", expect_converge=True, form=DebateForm.RED_TEAM, sides=sides, turns=turns),
        *_balanced(),
    )
    with pytest.raises(EvalConfigError, match="is_subject"):
        lint_scenarios(bad)


def test_lint_rejects_subject_on_nonredteam():
    sides = (
        DebateSide(key="pro", name="正方", stance="p", is_subject=True),
        DebateSide(key="con", name="反方", stance="c"),
    )
    bad = (_mk("s", expect_converge=True, sides=sides), *_balanced())
    with pytest.raises(EvalConfigError, match="is_subject"):
        lint_scenarios(bad)


def test_lint_rejects_expect_stop_on_continue():
    bad = (_mk("es", expect_converge=False, expect_stop=STOP_FOCUS_CLARIFIED), *_balanced())
    with pytest.raises(EvalConfigError, match="expect_stop"):
        lint_scenarios(bad)


def test_lint_rejects_bad_expect_stop_value():
    bad = (_mk("es2", expect_converge=True, expect_stop="max_rounds"), *_balanced())
    with pytest.raises(EvalConfigError, match="expect_stop"):
        lint_scenarios(bad)


def test_lint_rejects_imbalanced():
    imbalanced = (
        _mk("c1", expect_converge=True),
        _mk("c2", expect_converge=True),
        _mk("t1", expect_converge=False),
    )
    with pytest.raises(EvalConfigError, match="均衡"):
        lint_scenarios(imbalanced)


def test_lint_rejects_turn_side_key_not_declared():
    turns = (SideTurn("ghost", "幽灵", "g_t", "非声明方发言"),)
    bad = (_mk("g", expect_converge=True, turns=turns), *_balanced())
    with pytest.raises(EvalConfigError, match="side_key"):
        lint_scenarios(bad)


# --- 度量计算（脚本化裁判）--------------------------------------------------


def test_all_converge_is_pure_premature_on_real_scenarios():
    """裁判恒判收敛：该收敛的全对（过保守率 0）、该继续的全错（过早收敛率 1）。"""
    judge = _FixedJudge(converged=True)
    m = asyncio.run(run_debate_converge(judge, "m", SCENARIOS))
    assert judge.calls == len(SCENARIOS)
    assert m.over_conservatism_rate == 0.0
    assert m.premature_rate == 1.0
    assert len(m.premature) == m.n_should_continue
    assert m.accuracy == pytest.approx(m.n_should_converge / m.n)


def test_all_continue_is_pure_over_conservatism_on_real_scenarios():
    """裁判恒判继续：该收敛的全错（过保守率 1，本盘点最坏情形）、该继续的全对。"""
    judge = _FixedJudge(converged=False)
    m = asyncio.run(run_debate_converge(judge, "m", SCENARIOS))
    assert m.over_conservatism_rate == 1.0
    assert m.premature_rate == 0.0
    assert len(m.over_conservative) == m.n_should_converge
    assert m.accuracy == pytest.approx(m.n_should_continue / m.n)


def test_oracle_judge_matches_gold_perfectly():
    """oracle 假 provider（逐场景吐金标）→ 准确率 1、kappa 1、无分歧（金标自洽 + 路径不崩）。"""
    flags = [s.expect_converge for s in SCENARIOS]
    m = asyncio.run(run_debate_converge(_ByIndexJudge(flags), "m", SCENARIOS))
    assert m.accuracy == 1.0
    assert m.cohens_kappa == pytest.approx(1.0)
    assert m.disagreements == []
    assert m.n == len(SCENARIOS)


def test_mixed_confusion_matrix_and_disagreement_order():
    """混合脚本：一条过保守 + 一条过早收敛 → 精确混淆矩阵、分歧排序（过保守优先）、kappa。"""
    scenarios = _balanced()  # c1/c2 该收敛，t1/t2 该继续
    # c1 判收敛(对) / c2 判继续(过保守) / t1 判继续(对) / t2 判收敛(过早)
    flags = [True, False, False, True]
    m = asyncio.run(run_debate_converge(_ByIndexJudge(flags), "m", scenarios))

    assert m.n == 4
    assert m.accuracy == pytest.approx(0.5)
    assert m.over_conservatism_rate == pytest.approx(0.5)  # c2 / (c1,c2)
    assert m.premature_rate == pytest.approx(0.5)  # t2 / (t1,t2)
    assert [x.id for x in m.over_conservative] == ["c2"]
    assert [x.id for x in m.premature] == ["t2"]
    # 分歧排序：过保守（c2）排在过早收敛（t2）前。
    assert [x.id for x in m.disagreements] == ["c2", "t2"]
    assert m.cohens_kappa == pytest.approx(0.0)


def test_report_and_dict_shape():
    """报告文本含主信号行；to_dict 携逐场景 + 三个率，JSON 可序列化。"""
    flags = [s.expect_converge for s in SCENARIOS]
    m = asyncio.run(run_debate_converge(_ByIndexJudge(flags), "m", SCENARIOS))

    text = format_debate_converge_report(m)
    assert "辩论收敛校准" in text
    assert "过保守率" in text and "本盘点主信号" in text

    d = debate_converge_to_dict(m)
    assert d["n"] == len(SCENARIOS)
    assert set(d) >= {
        "accuracy",
        "over_conservatism_rate",
        "premature_rate",
        "cohens_kappa",
        "per_scenario",
    }
    assert len(d["per_scenario"]) == len(SCENARIOS)
    json.dumps(d, ensure_ascii=False)  # 可序列化，不 raise

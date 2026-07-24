"""TurnOutcome.artifacts 口径 + judged_text + EnsemblePairwiseJudge（假裁判，零 LLM）。"""

from __future__ import annotations

import asyncio
import json

from agentcore.evals.comparison import run_comparison_case
from agentcore.evals.harness import single_outcome, team_outcome
from agentcore.evals.judge import EnsemblePairwiseJudge
from agentcore.evals.recording_sink import RecordingSink
from agentcore.evals.types import (
    ComparisonCase,
    PairwiseVerdict,
    TurnOutcome,
    artifacts_from_tool_calls,
    judged_text,
)
from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import TokenUsage


def _fw(path: str, content: str) -> tuple[str, str]:
    return ("file_write", json.dumps({"path": path, "content": content}, ensure_ascii=False))


# --- artifacts 还原 -----------------------------------------------------------


def test_artifacts_from_tool_calls_last_write_wins_per_path():
    calls = [
        _fw("a.md", "draft-a"),
        ("web_search", '{"query": "x"}'),
        _fw("b.md", "only-b"),
        _fw("a.md", "final-a"),  # 同 path 末次覆盖
        ("file_write", "{not json}"),  # 坏 JSON 跳过
        ("file_write", json.dumps({"path": "c.md"})),  # 无 content 跳过
    ]
    assert artifacts_from_tool_calls(calls) == {"a.md": "final-a", "b.md": "only-b"}


def test_artifacts_empty_when_no_file_write():
    assert artifacts_from_tool_calls([("web_search", "{}")]) == {}
    assert artifacts_from_tool_calls([]) == {}


def test_judged_text_without_artifacts_is_content():
    oc = TurnOutcome(content="只有聊天", finish_reason="end_turn", rounds=1)
    assert judged_text(oc) == "只有聊天"


def test_judged_text_appends_sorted_artifacts():
    oc = TurnOutcome(
        content="摘要",
        finish_reason="end_turn",
        rounds=1,
        artifacts={"z.md": "Z正文", "a.md": "A正文"},
    )
    text = judged_text(oc)
    assert text.startswith("摘要")
    assert "### a.md\nA正文" in text
    assert "### z.md\nZ正文" in text
    # path 排序：a 在 z 前
    assert text.index("### a.md") < text.index("### z.md")


def test_judged_text_artifacts_only_when_content_empty():
    oc = TurnOutcome(
        content="",
        finish_reason="end_turn",
        rounds=1,
        artifacts={"out.md": "成品全文"},
    )
    assert judged_text(oc) == "### out.md\n成品全文"


# --- harness 填充 -------------------------------------------------------------


def test_single_outcome_fills_artifacts_from_sink():
    sink = RecordingSink()
    sink.tool_calls = [_fw("r.md", "v1"), _fw("r.md", "v2")]
    oc = single_outcome(
        "聊天",
        TokenUsage(),
        1,
        profile=ProfileParams(temperature=0.7, max_rounds=10),
        model="deepseek-v4-flash",
        sink=sink,
        citations=[],
        latency_ms=1,
    )
    assert oc.content == "聊天"  # 不改写
    assert oc.artifacts == {"r.md": "v2"}


def test_team_outcome_fills_artifacts_from_sink():
    sink = RecordingSink()
    sink.tool_calls = [_fw("team.md", "团队成品")]
    oc = team_outcome(
        {"content": "聊一句", "finish_reason": "end_turn", "rounds": 2},
        sink,
        latency_ms=1,
    )
    assert oc.content == "聊一句"
    assert oc.artifacts == {"team.md": "团队成品"}


# --- comparison 裁判吃到成品文本 ---------------------------------------------


class _CaptureJudge:
    """记下 compare 收到的 subject/baseline 内容。"""

    def __init__(self) -> None:
        self.subject_content = ""
        self.baseline_content = ""

    async def compare(self, *, subject_content, baseline_content, subject_arm, **_kw):  # noqa: ANN001
        self.subject_content = subject_content
        self.baseline_content = baseline_content
        return PairwiseVerdict(winner=subject_arm, rationale="ok", margin=1)


class _ArtifactHarness:
    async def run_case(self, case) -> TurnOutcome:  # noqa: ANN001
        if case.path == "team":
            return TurnOutcome(
                content="团队聊一句",
                finish_reason="end_turn",
                rounds=2,
                delegated=True,
                roster=["撰稿人"],
                artifacts={"report.md": "团队成品正文 FULL"},
                usage={"input": 10, "output": 5, "reasoning": 1},
                cost_usd=0.01,
                latency_ms=100,
            )
        return TurnOutcome(
            content="单体聊一句",
            finish_reason="end_turn",
            rounds=1,
            usage={"input": 5, "output": 2, "reasoning": 1},
            cost_usd=0.005,
            latency_ms=80,
        )


def test_comparison_judge_receives_artifact_text():
    cc = ComparisonCase(
        id="art_cmp",
        archetype="simple",
        user_message="写报告",
        arms=["single", "team"],
        baseline_arm="single",
        samples=1,
        rubric="哪个交付更完整",
    )
    judge = _CaptureJudge()
    asyncio.run(run_comparison_case(cc, _ArtifactHarness(), judge=judge, layer=2))
    assert "团队成品正文 FULL" in judge.subject_content
    assert "### report.md" in judge.subject_content
    assert "团队聊一句" in judge.subject_content
    assert judge.baseline_content == "单体聊一句"  # 无 artifacts → 纯 content


# --- Ensemble -----------------------------------------------------------------


class _FixedArmJudge:
    def __init__(self, winner: str, margin: int = 1) -> None:
        self.winner = winner
        self.margin = margin

    async def compare(self, **_kw) -> PairwiseVerdict:  # noqa: ANN003
        return PairwiseVerdict(winner=self.winner, rationale="fixed", margin=self.margin)


def test_ensemble_majority_wins_and_median_margin():
    ens = EnsemblePairwiseJudge(
        [
            _FixedArmJudge("team", 1),
            _FixedArmJudge("team", 3),
            _FixedArmJudge("single", 2),
        ],
        judge_ids=["a", "b", "c"],
    )
    v = asyncio.run(
        ens.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="T",
            baseline_arm="single",
            baseline_content="S",
        )
    )
    assert v.winner == "team"
    assert v.margin == 2  # median(1,3,2)
    assert len(v.votes) == 3
    assert [x.judge_id for x in v.votes] == ["a", "b", "c"]
    assert "多数=team" in v.rationale


def test_ensemble_no_majority_is_tie_with_vote_trace():
    ens = EnsemblePairwiseJudge(
        [
            _FixedArmJudge("team", 1),
            _FixedArmJudge("single", 1),
            _FixedArmJudge("tie", 0),
        ]
    )
    v = asyncio.run(
        ens.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="T",
            baseline_arm="single",
            baseline_content="S",
        )
    )
    assert v.winner == "tie"
    assert "分歧票型" in v.rationale
    assert len(v.votes) == 3


def test_ensemble_three_way_split_is_tie():
    ens = EnsemblePairwiseJudge(
        [_FixedArmJudge("team"), _FixedArmJudge("single"), _FixedArmJudge("other")]
    )
    v = asyncio.run(
        ens.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="T",
            baseline_arm="single",
            baseline_content="S",
        )
    )
    assert v.winner == "tie"


def test_absolute_judge_receives_artifact_text():
    """绝对分裁判走 judged_text，与成对裁判口径一致。"""
    from agentcore.evals.judge import LLMJudge
    from agentcore.evals.types import EvalCase
    from agentcore.llm.provider.protocol import LLMResponse

    class _Prov:
        def __init__(self) -> None:
            self.seen = ""

        async def complete(self, request):  # noqa: ANN001
            self.seen = request.messages[-1].content or ""
            return LLMResponse(content=json.dumps({"score": 4, "rationale": "ok"}))

    prov = _Prov()
    judge = LLMJudge(prov, "m", samples=1)
    case = EvalCase(id="j", category="qa", user_message="写文", rubric="完整")
    oc = TurnOutcome(
        content="聊",
        finish_reason="end_turn",
        rounds=1,
        artifacts={"doc.md": "成品 BODY"},
    )
    asyncio.run(judge.score(case, oc))
    assert "成品 BODY" in prov.seen
    assert "### doc.md" in prov.seen


def test_single_judge_verdict_votes_default_empty():
    """旧路径兼容：单裁判 PairwiseVerdict 无 votes / 空列表。"""
    v = PairwiseVerdict(winner="team", rationale="x", margin=1)
    assert v.votes == []

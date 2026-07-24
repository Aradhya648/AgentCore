"""辩手发言格式合规 eval 自测（per-PR 零 LLM 硬门禁）。"""

import asyncio

import pytest

from agentcore.evals.debate_speech_format import (
    NOTES_DRAFT_SAMPLES,
    SAMPLES,
    check_speech_format,
    debate_speech_format_to_dict,
    format_debate_speech_format_report,
    lint_notes_draft_samples,
    lint_samples,
    run_debate_speech_format,
)
from agentcore.evals.types import EvalConfigError
from agentcore.llm.provider.protocol import LLMResponse


class _FixedSpeech:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        self.calls += 1
        assert request.tools is None
        return LLMResponse(content=self.content)


def test_samples_lint_ok():
    lint_samples(SAMPLES)
    assert len(SAMPLES) >= 10
    assert {s.side_key for s in SAMPLES} == {"pro", "con"}
    assert {"opening", "continue"} <= {s.beat for s in SAMPLES}


def test_notes_draft_samples_lint_ok():
    """合成证据笔记→成稿样本（开发期合成，非真实数据）可组装。"""
    lint_notes_draft_samples(NOTES_DRAFT_SAMPLES)
    for s in NOTES_DRAFT_SAMPLES:
        _system, user = s.build_messages()
        assert s.evidence_notes.strip() in user
        assert "发言任务" in user


def test_lint_rejects_too_few():
    with pytest.raises(EvalConfigError, match="不足 10"):
        lint_samples(SAMPLES[:3])


def test_check_ok_skeleton():
    text = (
        "### 成本可控\n首年降本 18%【已核实·测算】。\n\n"
        "### 风险有兜底\n熔断策略已演练【待核实·推断】。"
    )
    r = check_speech_format(text)
    assert r.ok
    assert r.titles == ("成本可控", "风险有兜底")


def test_check_rejects_preamble():
    text = "好的，以下是我的立论。\n\n### 成本可控\n正文。"
    r = check_speech_format(text)
    assert not r.ok
    assert "preamble_or_not_h3_first" in r.failures


def test_check_rejects_overall_title():
    text = "### 正方立论\n铺垫。\n\n### 成本可控\n正文。"
    r = check_speech_format(text)
    assert not r.ok
    assert "overall_title" in r.failures


def test_check_rejects_bold_pseudo_header():
    text = "### 成本可控\n正文。\n\n**风险有兜底**\n更多正文。"
    r = check_speech_format(text)
    assert not r.ok
    assert "bold_pseudo_header" in r.failures


def test_check_rejects_long_title():
    long = "这是一个超过三十个字符用来触发度量门禁的超长论点标题必须足够长"
    assert len(long) > 30
    text = f"### {long}\n正文。"
    r = check_speech_format(text)
    assert not r.ok
    assert any(f.startswith("title_too_long") for f in r.failures)


def test_run_with_fixed_provider_all_ok():
    good = "### 成本可控\n降本。\n\n### 风险有兜底\n熔断。"
    provider = _FixedSpeech(good)
    metrics = asyncio.run(run_debate_speech_format(provider, "fake-model", SAMPLES[:2]))
    assert metrics.n == 2
    assert metrics.compliance_rate == 1.0
    assert provider.calls == 2
    report = format_debate_speech_format_report(metrics)
    assert "合规率" in report
    d = debate_speech_format_to_dict(metrics)
    assert d["n_ok"] == 2


def test_run_with_fixed_provider_captures_failure():
    bad = "好的我已掌握材料。\n\n下面是立论。"
    provider = _FixedSpeech(bad)
    metrics = asyncio.run(run_debate_speech_format(provider, "fake-model", SAMPLES[:1]))
    assert metrics.compliance_rate == 0.0
    assert metrics.failures[0].id == SAMPLES[0].id

"""对局台账（P0 对局记忆）自测：解析容错 / 累积 / 注入块。"""

from __future__ import annotations

import asyncio
import json

from agentcore.llm.provider.protocol import LLMResponse
from agentcore.runtime.debate import (
    DebateConfig,
    DebateForm,
    DebateSide,
    JudgeVerdict,
    LedgerEvent,
    LedgerEventKind,
    Moderator,
    RoundPolicy,
    RoundResult,
    SideTurn,
)
from agentcore.runtime.debate.match_ledger import (
    accumulate_match_ledger,
    as_ledger_events,
    format_match_ledger_block,
    format_own_argument_titles,
)
from agentcore.runtime.debate.prompt import closing_task, round_draft_brief, round_feedback


def test_as_ledger_events_parses_kinds_and_tolerates_missing_fields():
    raw = [
        {"kind": "withdrawal", "side": "pro", "content": "撤回 Interbrand 267 亿"},
        {"kind": "更正", "side": "pro", "content": "更正为 484 亿"},
        {"kind": "disputed_fact", "content": "门店数 2400 vs 2600"},  # side 可空
        {"kind": "concession", "side": "con", "content": "承认第64条不适用"},
        {"kind": "unknown", "side": "pro", "content": "应跳过"},
        {"kind": "withdrawal", "side": "ghost", "content": "幻觉方跳过"},
        {"kind": "withdrawal", "side": "pro"},  # 无 content
        "not-a-dict",
        {"kind": "withdrawal", "side": "pro", "content": "撤回 Interbrand 267 亿"},  # 去重
    ]
    out = as_ledger_events(raw, {"pro", "con"}, round_no=2)
    assert len(out) == 4
    assert out[0] == LedgerEvent(
        LedgerEventKind.WITHDRAWAL, "pro", "撤回 Interbrand 267 亿", 2
    )
    assert out[1].kind is LedgerEventKind.CORRECTION
    assert out[2].kind is LedgerEventKind.DISPUTED_FACT
    assert out[2].side == ""
    assert out[3].kind is LedgerEventKind.CONCESSION


def test_as_ledger_events_empty_on_bad_shape():
    assert as_ledger_events(None, {"pro"}) == []
    assert as_ledger_events({"kind": "withdrawal"}, {"pro"}) == []
    assert as_ledger_events([], {"pro"}) == []


def test_accumulate_and_format_digest():
    e1 = LedgerEvent(LedgerEventKind.WITHDRAWAL, "pro", "撤回 A", round_no=1)
    e2 = LedgerEvent(LedgerEventKind.CONCESSION, "con", "让步 B", round_no=2)
    r1 = RoundResult(
        1,
        "f1",
        [],
        JudgeVerdict(True, True, False, ledger_events=[e1]),
    )
    r2 = RoundResult(
        2,
        "f2",
        [],
        JudgeVerdict(True, True, False, ledger_events=[e2]),
    )
    ledger = accumulate_match_ledger([r1, r2])
    assert [e.content for e in ledger] == ["撤回 A", "让步 B"]
    block = format_match_ledger_block(
        ledger, side_names={"pro": "正方", "con": "反方"}
    )
    assert "【对局台账】" in block
    assert "已撤回" in block and "正方" in block
    assert "关键让步" in block and "反方" in block
    assert "禁止再引用" in block
    assert format_match_ledger_block([]) == ""


def test_own_argument_titles_and_brief_injection():
    pro = DebateSide("pro", "正方", "支持")
    con = DebateSide("con", "反方", "反对")
    config = DebateConfig(
        motion="是否 X",
        form=DebateForm.DEBATE,
        sides=[pro, con],
        policy=RoundPolicy(max_rounds=3),
    )
    turn = SideTurn(
        "pro",
        "正方",
        "r1_pro",
        "正文",
        arguments=[
            {"id": "arg-1", "title": "跨类须证混淆", "body": "……"},
            {"id": "arg-2", "title": "贡献率举证在权利人", "body": "……"},
        ],
    )
    history = [
        RoundResult(1, "焦点", [turn], JudgeVerdict(True, True, False)),
    ]
    titles = format_own_argument_titles(history, pro)
    assert "跨类须证混淆" in titles
    assert "贡献率举证在权利人" in titles

    ledger = [
        LedgerEvent(LedgerEventKind.WITHDRAWAL, "pro", "撤回旧数字", round_no=1),
    ]
    fb = round_feedback(
        config, con, 2, "更深", history[0], match_ledger=ledger, history=history
    )
    assert "【对局台账】" in fb
    assert "撤回旧数字" in fb
    # 检索 feedback 不注入己方标题一览
    assert "你历轮已立论点" not in fb

    brief = round_draft_brief(
        config, pro, 2, "更深", history[0], match_ledger=ledger, history=history
    )
    assert "【对局台账】" in brief
    assert "你历轮已立论点" in brief
    assert "跨类须证混淆" in brief

    # 无台账事件时 closing 仍可有论点材料；加事件后再查
    history[0].verdict.ledger_events.append(ledger[0])
    closing2 = closing_task(config, pro, history)
    assert "【对局台账】" in closing2
    assert "撤回旧数字" in closing2


def test_judge_parses_ledger_events_into_verdict():
    """裁判 JSON 带 ledger_events → verdict 结构化；缺字段容错。"""

    class _LLM:
        async def complete(self, request):  # noqa: ANN001
            payload = {
                "real_clash": True,
                "new_arguments": True,
                "converged": False,
                "next_focus": "下一焦点",
                "rationale": "推进",
                "summary": "小结",
                "clashes": [],
                "scores": {},
                "ledger_events": [
                    {
                        "kind": "withdrawal",
                        "side": "pro",
                        "content": "撤回北京日报引述",
                    },
                    {"kind": "bogus", "side": "pro", "content": "跳过"},
                ],
            }
            return LLMResponse(content=json.dumps(payload, ensure_ascii=False))

    mod = Moderator(provider=_LLM(), model="fake")
    turns = [
        SideTurn("pro", "正方", "r1", "我们撤回该引述。"),
        SideTurn("con", "反方", "r2", "对方撤回了。"),
    ]
    config = DebateConfig(
        motion="m",
        form=DebateForm.DEBATE,
        sides=[
            DebateSide("pro", "正方", "支持"),
            DebateSide("con", "反方", "反对"),
        ],
        policy=RoundPolicy(max_rounds=3),
    )
    verdict, summary = asyncio.run(
        mod._judge_and_summarize(config, "焦点", turns, [])
    )
    assert summary == "小结"
    assert len(verdict.ledger_events) == 1
    assert verdict.ledger_events[0].kind is LedgerEventKind.WITHDRAWAL
    assert verdict.ledger_events[0].content == "撤回北京日报引述"
    # 不上 wire
    rr = RoundResult(1, "焦点", turns, verdict, summary)
    assert "ledger" not in json.dumps(rr.to_event_payload(), ensure_ascii=False)

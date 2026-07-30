"""引用即出处 P1 §十第 3 步：#rN id 存在闸 + 分路径回炉 + pause 台账再水化。"""

from __future__ import annotations

from pathlib import Path

from agentcore.llm.provider.protocol import LLMChunk, LLMMessage
from agentcore.runtime.engine import react_loop
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import TurnPausedFact
from agentcore.runtime.pipeline.resume.rehydrate import rehydrate_from_turn_paused
from agentcore.runtime.suspension import AskUserSuspension, turn_evidence_ledger
from agentcore.runtime.turn_paused_capture import build_turn_paused_fact
from agentcore.runtime.verify import finish_guard
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.llm_helpers import make_profile_params


def _content_chunk(text: str) -> LLMChunk:
    return LLMChunk(delta_content=text)


class _ScriptedProvider:
    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0

    async def stream(self, request):  # noqa: ANN001
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk


def _context() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


async def _run_worker(
    provider: _ScriptedProvider,
    *,
    ledger: EvidenceLedgerCore,
    max_rounds: int = 10,
):
    messages: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    sink = EventSink()
    resets: list[str] = []
    result = await react_loop(
        messages=messages,
        llm=provider,
        tools=ToolRegistry(),
        sink=sink,
        tool_context=_context(),
        profile=make_profile_params(max_rounds=max_rounds),
        turn_model="m",
        citation_sink=[],
        annotate_citations=False,
        turn_evidence_ledger=ledger,
        on_reset=resets.append,
    )
    return result, messages, sink, resets


def _seed_ledger(
    *urls: str, weak_url: str | None = None, deep_read: bool = True
) -> EvidenceLedgerCore:
    """默认 deep_read=True，使成稿闸可引；search-only 测例显式传 deep_read=False。"""
    led = EvidenceLedgerCore(id_prefix="#r")
    for url in urls:
        led.register_sync(
            url=url, title=url, registrant="worker:w1", deep_read=deep_read
        )
    if weak_url:
        led.register_sync(
            url=weak_url,
            title="weak",
            registrant="worker:w1",
            tier="weak",
            deep_read=deep_read,
        )
    return led


def test_finish_guard_search_only_blocked():
    """search-only（无 deep_read / selected）不得进成稿闸。"""
    reworks = finish_guard(
        "见 #r1。",
        citation_count=0,
        check_citations=False,
        citable_ids=frozenset(),  # draft 空 = search-only 被排除后
    )
    assert reworks and "#r1" in reworks[0]


async def test_worker_search_only_rn_reworks():
    led = _seed_ledger("https://example.com/a", deep_read=False)
    assert led.draft_citable_ids() == frozenset()
    assert led.citable_ids() == frozenset({"#r1"})
    provider = _ScriptedProvider(
        [
            [_content_chunk("结论见 #r1。")],
            [_content_chunk("无引用的干净结论。")],
        ]
    )
    (content, _r, _u, rounds), _messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert content == "无引用的干净结论。"
    assert rounds == 2
    assert resets == ["finish_guard"]


# --- finish_guard 纯函数 -------------------------------------------------------


def test_finish_guard_valid_ledger_ref_passes():
    assert (
        finish_guard(
            "结论见 #r1。",
            citation_count=0,
            check_citations=False,
            citable_ids=frozenset({"#r1"}),
        )
        == []
    )


def test_finish_guard_forged_ledger_ref_flagged():
    reworks = finish_guard(
        "伪造 #r9。",
        citation_count=0,
        check_citations=False,
        citable_ids=frozenset({"#r1"}),
    )
    assert len(reworks) == 1
    assert "#r9" in reworks[0]


def test_finish_guard_uncitable_flagged():
    # 未登记 / 不在 citable 集的 id → 不可引用（P2：weak 本身可引用）
    reworks = finish_guard(
        "幽灵 #r2。",
        citation_count=0,
        check_citations=False,
        citable_ids=frozenset({"#r1"}),  # #r2 不在可引用集
    )
    assert reworks and "#r2" in reworks[0]


def test_finish_guard_weak_citable_passes():
    assert (
        finish_guard(
            "弱源亦可引 #r2。",
            citation_count=0,
            check_citations=False,
            citable_ids=frozenset({"#r1", "#r2"}),
        )
        == []
    )


def test_finish_guard_q5_no_marker_skips_ledger_gate():
    # 无 #rN → 不回炉（即便台账为空）
    assert (
        finish_guard(
            "普通调研结论，无约定引用标记。",
            citation_count=0,
            check_citations=False,
            citable_ids=frozenset(),
        )
        == []
    )


def test_finish_guard_legacy_bracket_track_unchanged():
    reworks = finish_guard("见 [9]。", citation_count=1, check_citations=True)
    assert reworks and "[9]" in reworks[0]


# --- react_loop 集成：worker 分路径 --------------------------------------------


async def test_worker_valid_rn_finishes_without_rework():
    led = _seed_ledger("https://example.com/a")
    provider = _ScriptedProvider([[_content_chunk("结论见 #r1。")]])
    (content, _r, _u, rounds), _messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert content == "结论见 #r1。"
    assert rounds == 1
    assert resets == []


async def test_worker_forged_rn_reworks_once_then_clean():
    led = _seed_ledger("https://example.com/a")
    provider = _ScriptedProvider(
        [
            [_content_chunk("伪造 #r9。")],
            [_content_chunk("修正：结论见 #r1。")],
        ]
    )
    (content, _r, _u, rounds), messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert content == "修正：结论见 #r1。"
    assert rounds == 2
    assert resets == ["finish_guard"]
    steers = [m for m in messages if m.role == "user" and m.content and "核验未通过" in m.content]
    assert len(steers) == 1
    assert "#r9" in steers[0].content


async def test_worker_second_violation_strips_with_observation(monkeypatch):
    import agentcore.runtime.engine.round as round_mod
    from tests.conftest import LogSpy

    spy = LogSpy()
    monkeypatch.setattr(round_mod, "logger", spy)

    led = _seed_ledger("https://example.com/a")
    bad = [_content_chunk("仍伪造 #r9。")]
    provider = _ScriptedProvider([bad, bad])
    (content, _r, _u, rounds), _messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert rounds == 2  # 回炉 1 次后放行
    assert "#r9" not in content
    assert "仍伪造" in content
    assert resets.count("finish_guard") >= 1  # 回炉 + 出口剥离至少一次
    obs = spy.get("citations.invalid_ledger_ref")
    assert obs["markers"] == ["#r9"]


async def test_worker_no_marker_does_not_rework():
    led = _seed_ledger("https://example.com/a")
    provider = _ScriptedProvider([[_content_chunk("worker 产出无引用。")]])
    (content, _r, _u, rounds), _messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert content == "worker 产出无引用。"
    assert rounds == 1
    assert resets == []


async def test_worker_legacy_bracket_still_skipped():
    # annotate_citations=False：[n] 旧轨仍不回炉（Q5 / 不回归）
    led = _seed_ledger("https://example.com/a")
    provider = _ScriptedProvider([[_content_chunk("worker 产出 [1]。")]])
    (content, _r, _u, rounds), _messages, _sink, resets = await _run_worker(
        provider, ledger=led
    )
    assert content == "worker 产出 [1]。"
    assert rounds == 1
    assert resets == []


async def test_ceo_ledger_ref_uses_config_max_reworks():
    # CEO annotate=True：非法 #rN 跟配置默认 2 次回炉
    led = _seed_ledger("https://example.com/a")
    bad = [_content_chunk("见 #r9。")]
    provider = _ScriptedProvider([bad, bad, bad])
    messages: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    sink = EventSink()
    content, _r, _u, rounds = await react_loop(
        messages=messages,
        llm=provider,
        tools=ToolRegistry(),
        sink=sink,
        tool_context=_context(),
        profile=make_profile_params(max_rounds=10),
        turn_model="m",
        citation_sink=[],
        annotate_citations=True,
        turn_evidence_ledger=led,
    )
    assert rounds == 3  # 回炉 2 次后放行
    assert "#r9" not in content  # 出口剥离
    resets = [e for e in sink._history if e.type == EventType.CONTENT_RESET]
    assert len(resets) >= 2


# --- pause / resume 台账快照 ---------------------------------------------------


def test_turn_paused_captures_and_rehydrates_ledger():
    led = EvidenceLedgerCore(id_prefix="#r")
    led.register_sync(
        url="https://example.com/a", title="A", registrant="ceo", deep_read=True
    )
    led.register_sync(url="https://example.com/b", title="B", registrant="worker:w1")
    token = turn_evidence_ledger.set(led)
    try:
        fact = build_turn_paused_fact(
            checkpoint_id="ck1",
            suspension_kind="ask_user",
            required_event=type("E", (), {"type": "ask_user_required", "payload": {}})(),
            journal_entries_before_trailing=[],
            sink=None,
        )
    finally:
        turn_evidence_ledger.reset(token)

    assert len(fact.evidence_ledger or []) == 2
    assert fact.evidence_ledger[0]["id"] == "#r1"
    assert fact.evidence_ledger[1]["id"] == "#r2"

    # rehydrate → load_entries → id 连续；成稿闸仅 deep_read∪selected
    restored = EvidenceLedgerCore(id_prefix="#r")
    restored.load_entries(fact.evidence_ledger or [])
    assert restored.citable_ids() == frozenset({"#r1", "#r2"})
    assert restored.draft_citable_ids() == frozenset({"#r1"})
    assert (
        finish_guard(
            "挂起前已引用 #r1。",
            citation_count=0,
            check_citations=False,
            citable_ids=restored.draft_citable_ids(),
        )
        == []
    )
    nxt = restored.register_sync(
        url="https://example.com/c", title="C", registrant="ceo"
    )
    assert nxt == "#r3"  # 不重号


def test_rehydrate_state_exposes_evidence_ledger():
    sink = EventSink()
    entry = (
        TurnPausedFact(
            checkpoint_id="ck1",
            suspension_kind="ask_user",
            content="见 #r1",
            evidence_ledger=[
                {
                    "id": "#r1",
                    "url": "https://example.com/a",
                    "title": "A",
                    "tier": "unknown",
                    "citable": True,
                    "registrant": "ceo",
                }
            ],
        )
        .to_fact()
        .entry()
    )
    frame = AskUserSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap1",
        checkpoint_id="ck1",
        tool_call_id="call1",
        base_system_prompt="sys",
        user_message="go",
        journal_entries=[entry],
        question="q",
        questions=[],
    )
    hydrated = rehydrate_from_turn_paused(sink=sink, suspension=frame)
    assert hydrated.from_turn_paused is True
    assert len(hydrated.evidence_ledger) == 1
    assert hydrated.evidence_ledger[0]["id"] == "#r1"

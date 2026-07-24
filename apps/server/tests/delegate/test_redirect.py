"""Drive-level run-redirect (热优先 · 冷诚实回落): user redirect cancels ONE worker;
salvageable transcript → continue_run revision; empty → cold ``_redir`` + replaces_run_id.
Parallel teammates keep running.
"""

import asyncio

from agentcore.llm.provider.protocol import LLMChunk
from agentcore.runtime.events import EventSink
from agentcore.runtime.events.types import EventType
from agentcore.runtime.runs.redirect_queue import enqueue_redirect, take_redirects
from tests.delegate.conftest import Provider, ctx, tool

_STEER = "改成B方向重做"


class _RedirectProvider:
    """ORIGINAL workers sleep (so redirect can cancel mid-flight). COLD re-run sees
    ``steer`` in the user prompt; HOT continue_run sees the revision instruction."""

    def __init__(self) -> None:
        self.steered_calls = 0
        self.hot_calls = 0

    async def stream(self, request):  # noqa: ANN001
        user = " ".join(m.content or "" for m in request.messages if m.role == "user")
        if (
            "续干指令" in user
            or "修改要求" in user
            or "立即改此人" in user
            or "改方向" in user
        ):
            self.hot_calls += 1
            yield LLMChunk(delta_content="HOT_DONE")
            return
        if _STEER in user:
            self.steered_calls += 1
            yield LLMChunk(delta_content="STEERED_DONE")
            return
        await asyncio.sleep(0.5)
        yield LLMChunk(delta_content="ORIG_DONE")


class _RedirectOnStartSink(EventSink):
    """Enqueue ONE redirect when the first worker starts."""

    def __init__(self, feedback: str) -> None:
        super().__init__()
        self._feedback = feedback
        self._sent = False
        self.redirected_run_id = ""

    def emit(self, event) -> None:  # noqa: ANN001
        if not self._sent and event.type is EventType.RUN_STARTED:
            run_id = str(event.payload.get("run_id") or "")
            # Skip revision / redir children — only redirect the original worker.
            if run_id and "_rev" not in run_id and not run_id.endswith("_redir"):
                self.redirected_run_id = run_id
                enqueue_redirect(
                    execution_id="e",
                    run_id=run_id,
                    feedback=self._feedback,
                    conversation_id="c",
                )
                self._sent = True
        super().emit(event)


class _HotRedirectProvider:
    """First call for a worker yields a draft then sleeps (so cancel can salvage);
    subsequent continue_run sees the revision instruction."""

    def __init__(self) -> None:
        self.calls = 0
        self.hot_calls = 0

    async def stream(self, request):  # noqa: ANN001
        self.calls += 1
        user = " ".join(m.content or "" for m in request.messages if m.role == "user")
        if "续干指令" in user or "修改要求" in user:
            self.hot_calls += 1
            yield LLMChunk(delta_content="HOT_DONE")
            return
        # Emit a draft assistant turn worth of content, then hang so redirect cancels.
        yield LLMChunk(delta_content="半成品草稿")
        await asyncio.sleep(0.5)
        yield LLMChunk(delta_content="…续")


class _HotRedirectSink(EventSink):
    """Redirect after the first run_output_delta (partial draft is on the wire)."""

    def __init__(self, feedback: str) -> None:
        super().__init__()
        self._feedback = feedback
        self._sent = False
        self.redirected_run_id = ""
        self.cancelled_reasons: list[str] = []
        self.continues_roots: list[str] = []
        self.replaces: list[str] = []

    def emit(self, event) -> None:  # noqa: ANN001
        if event.type is EventType.RUN_CANCELLED:
            self.cancelled_reasons.append(str(event.payload.get("reason") or ""))
        if event.type is EventType.RUN_STARTED:
            continues = event.payload.get("continues_run_id")
            if continues:
                self.continues_roots.append(str(continues))
            replaces = event.payload.get("replaces_run_id")
            if replaces:
                self.replaces.append(str(replaces))
        if (
            not self._sent
            and event.type is EventType.RUN_OUTPUT_DELTA
            and event.payload.get("delta")
        ):
            run_id = str(event.payload.get("run_id") or "")
            if run_id:
                self.redirected_run_id = run_id
                enqueue_redirect(
                    execution_id="e",
                    run_id=run_id,
                    feedback=self._feedback,
                    conversation_id="c",
                )
                self._sent = True
        super().emit(event)


async def test_redirect_cancels_running_worker_and_cold_reruns_with_steer():
    """Empty mid-flight (no assistant turn yet) → cold ``_redir`` + steer + replaces_run_id."""
    provider = _RedirectProvider()
    sink = _RedirectOnStartSink(_STEER)
    t = tool(provider, sink)

    result = await t.execute(
        {"tasks": [{"id": "a", "role": "研究员", "task": "原方向调研"}]}, ctx()
    )

    assert result.success is True
    assert provider.steered_calls == 1
    assert "STEERED_DONE" in result.output
    assert "ORIG_DONE" not in result.output
    # Cold handoff must declare replaces_run_id (接手, not parallel phantom).
    history = sink._history
    replaces = [
        e.payload.get("replaces_run_id")
        for e in history
        if e.type is EventType.RUN_STARTED and e.payload.get("replaces_run_id")
    ]
    assert replaces == [sink.redirected_run_id]
    cancelled = [
        e.payload.get("reason")
        for e in history
        if e.type is EventType.RUN_CANCELLED
    ]
    assert "redirect" in cancelled


async def test_redirect_one_worker_leaves_sibling_running():
    """并行 ≥2 worker，redirect 其一 → 另一照常 completed，整轮不 cancelled."""
    provider = _RedirectProvider()
    sink = _RedirectOnStartSink(_STEER)
    t = tool(provider, sink)

    result = await t.execute(
        {
            "tasks": [
                {"id": "a", "role": "研究员", "task": "并行调研甲"},
                {"id": "b", "role": "编辑", "task": "并行撰写乙"},
            ],
            "coordinate": False,
        },
        ctx(),
    )

    assert result.success is True
    assert provider.steered_calls == 1
    assert "STEERED_DONE" in result.output
    assert "ORIG_DONE" in result.output


async def test_redirect_hot_continue_when_partial_draft_exists():
    """有一半产出 → salvage → continue_run 修订链；无 ``_redir`` 节点."""
    provider = _HotRedirectProvider()
    sink = _HotRedirectSink(_STEER)
    t = tool(provider, sink)

    result = await t.execute(
        {"tasks": [{"id": "a", "role": "研究员", "task": "原方向调研"}]}, ctx()
    )

    assert result.success is True
    assert provider.hot_calls >= 1
    assert "HOT_DONE" in result.output
    assert "redirect" in sink.cancelled_reasons
    assert sink.redirected_run_id in sink.continues_roots
    # No cold handoff node.
    assert sink.replaces == []
    redir_starts = [
        e
        for e in sink._history
        if e.type is EventType.RUN_STARTED
        and str(e.payload.get("run_id") or "").endswith("_redir")
    ]
    assert redir_starts == []


class _DoubleHotProvider:
    """First non-hot call hangs with a salvageable draft (the redirected worker);
    other non-hot calls are the slow sibling that keeps the wave alive; hot
    continues answer revision keywords. Claim is locked so parallel starts don't
    both hang (sibling task text also appears in the peer's sibling_summary)."""

    def __init__(self) -> None:
        self.hot_calls = 0
        self._orig_claimed = False
        self._claim_lock = asyncio.Lock()

    async def stream(self, request):  # noqa: ANN001
        user = " ".join(m.content or "" for m in request.messages if m.role == "user")
        # continue_run appends prior assistant turns + revision instruction.
        if (
            any(m.role == "assistant" for m in request.messages)
            or "续干指令" in user
            or "修改要求" in user
            or "立即改此人" in user
            or "改方向" in user
        ):
            self.hot_calls += 1
            yield LLMChunk(delta_content=f"HOT{self.hot_calls}")
            return
        async with self._claim_lock:
            claim_orig = not self._orig_claimed
            if claim_orig:
                self._orig_claimed = True
        if claim_orig:
            yield LLMChunk(delta_content="半成品草稿")
            await asyncio.sleep(0.5)
            yield LLMChunk(delta_content="…续")
            return
        await asyncio.sleep(0.35)
        yield LLMChunk(delta_content="SIBLING_DONE")


class _DoubleHotSink(EventSink):
    """First redirect after original draft; second after first hot revision starts."""

    def __init__(self) -> None:
        super().__init__()
        self.redirected_run_id = ""
        self.redirect_count = 0
        self.revision_starts: list[tuple[str, str | None, str | None]] = []

    def emit(self, event) -> None:  # noqa: ANN001
        if event.type is EventType.RUN_STARTED:
            rid = str(event.payload.get("run_id") or "")
            parent = event.payload.get("parent_run_id")
            continues = event.payload.get("continues_run_id")
            if continues:
                self.revision_starts.append(
                    (
                        rid,
                        str(parent) if parent else None,
                        str(continues) if continues else None,
                    )
                )
                # Second redirect on the same author once the first hot revision is live.
                if self.redirect_count == 1 and self.redirected_run_id:
                    enqueue_redirect(
                        execution_id="e",
                        run_id=self.redirected_run_id,
                        feedback="再改一版：补风险",
                        conversation_id="c",
                    )
                    self.redirect_count = 2
        if (
            self.redirect_count == 0
            and event.type is EventType.RUN_OUTPUT_DELTA
            and event.payload.get("delta")
        ):
            run_id = str(event.payload.get("run_id") or "")
            if run_id and "_rev" not in run_id and not run_id.endswith("_redir"):
                self.redirected_run_id = run_id
                enqueue_redirect(
                    execution_id="e",
                    run_id=run_id,
                    feedback=_STEER,
                    conversation_id="c",
                )
                self.redirect_count = 1
        super().emit(event)


async def test_redirect_hot_twice_increments_revision_ids():
    """同人连续两次热 redirect（均有可 salvage 草稿）→ ``_rev1`` then ``_rev2``，图链正确."""
    provider = _DoubleHotProvider()
    sink = _DoubleHotSink()
    t = tool(provider, sink)

    result = await t.execute(
        {
            "tasks": [
                {"id": "a", "role": "研究员", "task": "原方向调研"},
                {"id": "b", "role": "编辑", "task": "并行撰写乙"},
            ],
            "coordinate": False,
        },
        ctx(),
    )

    assert result.success is True
    assert provider.hot_calls >= 2
    assert sink.redirect_count == 2
    orig = sink.redirected_run_id
    rev_ids = [rid for rid, _parent, continues in sink.revision_starts if continues == orig]
    assert rev_ids == [f"{orig}_rev1", f"{orig}_rev2"]
    # No cold handoff for this author.
    assert not any(
        str(e.payload.get("run_id") or "").endswith("_redir")
        for e in sink._history
        if e.type is EventType.RUN_STARTED
    )


async def test_redirect_that_cannot_apply_is_recorded_ignored(monkeypatch):
    """忽略路径：目标从未 in-flight → audit ignored，无 wire 幻影."""
    take_redirects("e")
    recorded: list[dict] = []

    def _capture(*, run_id, feedback=None, execution_id=None):
        recorded.append({"run_id": run_id, "feedback": feedback, "execution_id": execution_id})

    monkeypatch.setattr("agentcore.runtime.audit.hooks.on_run_redirect_ignored", _capture)

    enqueue_redirect(execution_id="e", run_id="ghost", feedback="太晚了改不动", conversation_id="c")

    t = tool(Provider(["调研完成"]))
    result = await t.execute({"tasks": [{"id": "a", "role": "研究员", "task": "调研"}]}, ctx())

    assert result.success is True
    assert [r["run_id"] for r in recorded] == ["ghost"]
    assert recorded[0]["feedback"] == "太晚了改不动"
    assert recorded[0]["execution_id"] == "e"


class _ColdThenHotProvider:
    """Original hangs empty (cold); ``_redir`` emits salvageable draft then hangs;
    continue_run answers revision keywords."""

    def __init__(self) -> None:
        self.hot_calls = 0
        self.cold_steered_calls = 0

    async def stream(self, request):  # noqa: ANN001
        user = " ".join(m.content or "" for m in request.messages if m.role == "user")
        if (
            any(m.role == "assistant" for m in request.messages)
            or "续干指令" in user
            or "修改要求" in user
            or "立即改此人" in user
            or "改方向" in user
        ):
            self.hot_calls += 1
            yield LLMChunk(delta_content="HOT_AFTER_REDIR")
            return
        if _STEER in user:
            # Cold handoff: produce a draft the second redirect can salvage.
            self.cold_steered_calls += 1
            yield LLMChunk(delta_content="接手半成品")
            await asyncio.sleep(0.5)
            yield LLMChunk(delta_content="…续")
            return
        await asyncio.sleep(0.5)
        yield LLMChunk(delta_content="ORIG_DONE")


class _ColdThenHotSink(EventSink):
    """First redirect on original RUN_STARTED (empty → cold ``_redir``);
    second on the handoff's first output delta (salvage → hot ``{redir}_rev1``)."""

    def __init__(self) -> None:
        super().__init__()
        self.original_run_id = ""
        self.redir_run_id = ""
        self.redirect_count = 0
        self.replaces: list[str] = []
        self.revision_starts: list[tuple[str, str | None, str | None]] = []

    def emit(self, event) -> None:  # noqa: ANN001
        if event.type is EventType.RUN_STARTED:
            rid = str(event.payload.get("run_id") or "")
            replaces = event.payload.get("replaces_run_id")
            if replaces:
                self.replaces.append(str(replaces))
            parent = event.payload.get("parent_run_id")
            continues = event.payload.get("continues_run_id")
            if continues:
                self.revision_starts.append(
                    (
                        rid,
                        str(parent) if parent else None,
                        str(continues),
                    )
                )
            if (
                self.redirect_count == 0
                and rid
                and "_rev" not in rid
                and not rid.endswith("_redir")
            ):
                self.original_run_id = rid
                enqueue_redirect(
                    execution_id="e",
                    run_id=rid,
                    feedback=_STEER,
                    conversation_id="c",
                )
                self.redirect_count = 1
        if (
            self.redirect_count == 1
            and event.type is EventType.RUN_OUTPUT_DELTA
            and event.payload.get("delta")
        ):
            run_id = str(event.payload.get("run_id") or "")
            if run_id.endswith("_redir"):
                self.redir_run_id = run_id
                enqueue_redirect(
                    execution_id="e",
                    run_id=run_id,
                    feedback="再改一版：补风险",
                    conversation_id="c",
                )
                self.redirect_count = 2
        super().emit(event)


async def test_redirect_cold_redir_then_hot_continue_on_handoff():
    """冷 ``_redir`` 后再热续接手节点 → 一条 ``_redir`` + ``{redir}_rev1``，无双 ``_redir`` 幻影."""
    provider = _ColdThenHotProvider()
    sink = _ColdThenHotSink()
    t = tool(provider, sink)

    result = await t.execute(
        {"tasks": [{"id": "a", "role": "研究员", "task": "原方向调研"}]}, ctx()
    )

    assert result.success is True
    assert sink.redirect_count == 2
    assert provider.cold_steered_calls >= 1
    assert provider.hot_calls >= 1
    assert "HOT_AFTER_REDIR" in result.output

    orig = sink.original_run_id
    redir = sink.redir_run_id
    assert orig
    assert redir == f"{orig}_redir"
    assert sink.replaces == [orig]

    redir_starts = [
        str(e.payload.get("run_id") or "")
        for e in sink._history
        if e.type is EventType.RUN_STARTED
        and str(e.payload.get("run_id") or "").endswith("_redir")
    ]
    assert redir_starts == [redir]

    rev_ids = [rid for rid, _parent, continues in sink.revision_starts if continues == redir]
    assert rev_ids == [f"{redir}_rev1"]
    # No continuation hanging off the cancelled original (cold, not hot).
    assert not any(continues == orig for _, _, continues in sink.revision_starts)

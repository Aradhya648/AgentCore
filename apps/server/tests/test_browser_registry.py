"""BrowserSessionRegistry M0 lifecycle: multi session_id, TTL, concurrency, reap."""

from __future__ import annotations

import time

import pytest

from agentcore.runtime.browser.registry import BrowserSessionRegistry
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommand,
    BrowserCommandResult,
    BrowserSessionRequest,
    BrowserSessionsBusyError,
)


class FakeBrowserSession:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.created_at = time.time()
        self.last_used = time.time()
        self._alive = True
        self.closed = False

    @property
    def alive(self) -> bool:
        return self._alive

    async def send(self, command: BrowserCommand) -> BrowserCommandResult:
        self.last_used = time.time()
        return BrowserCommandResult(ok=True, data={"final_url": "https://x/"})

    async def close(self) -> None:
        self.closed = True
        self._alive = False


def _make_registry(**kw):
    created: list[FakeBrowserSession] = []

    async def factory(request: BrowserSessionRequest) -> FakeBrowserSession:
        s = FakeBrowserSession(request.conversation_id)
        created.append(s)
        return s

    reg = BrowserSessionRegistry(factory=factory, **kw)
    return reg, created


def _req(cid: str, **kw) -> BrowserSessionRequest:
    return BrowserSessionRequest(conversation_id=cid, **kw)


@pytest.mark.asyncio
async def test_lazy_create_and_reuse():
    reg, created = _make_registry(max_sessions=4)
    s1, kf1 = await reg.acquire(_req("c1"))
    s2, kf2 = await reg.acquire(_req("c1"))
    assert s1 is s2 and kf1 is kf2  # same conversation reuses the live session
    assert len(created) == 1
    assert len(reg) == 1
    assert "c1" in reg


@pytest.mark.asyncio
async def test_conversation_can_hold_two_live_sessions():
    """Acceptance: one conversation may hold ≥2 live entries (multi session_id)."""
    reg, created = _make_registry(max_sessions=8)
    a, _, sid_a = await reg.create(_req("c1"), activate=True)
    b, _, sid_b = await reg.create(_req("c1"), activate=False)
    assert sid_a != sid_b
    assert a is not b
    assert len(created) == 2
    assert len(reg) == 2
    infos = reg.list_by_conversation("c1")
    assert {i.session_id for i in infos} == {sid_a, sid_b}
    assert all(i.host_kind == "sandbox" for i in infos)
    # Default peek resolves to the active tab (sid_a).
    assert reg.peek("c1") is a
    assert reg.peek("c1", session_id=sid_b) is b


@pytest.mark.asyncio
async def test_run_id_binds_separate_sessions():
    reg, created = _make_registry(max_sessions=8)
    s1, _ = await reg.acquire(_req("c1", run_id="run-a"))
    s2, _ = await reg.acquire(_req("c1", run_id="run-b"))
    assert s1 is not s2
    assert len(created) == 2
    assert reg.peek("c1", run_id="run-a") is s1
    assert reg.peek("c1", run_id="run-b") is s2
    # Same run reuses its bound session.
    s1b, _ = await reg.acquire(_req("c1", run_id="run-a"))
    assert s1b is s1
    assert len(created) == 2


@pytest.mark.asyncio
async def test_concurrent_acquire_different_runs_split_unbound_tab():
    """Two runs racing on one unbound tab must not share the same session_id."""
    import asyncio

    reg, created = _make_registry(max_sessions=8)
    await reg.create(_req("c1"), activate=True)
    assert len(created) == 1

    (s_a, _), (s_b, _) = await asyncio.gather(
        reg.acquire(_req("c1", run_id="run-a")),
        reg.acquire(_req("c1", run_id="run-b")),
    )
    assert s_a is not s_b
    peek_a = reg.peek("c1", run_id="run-a")
    peek_b = reg.peek("c1", run_id="run-b")
    assert peek_a is s_a and peek_b is s_b
    assert peek_a is not peek_b
    # One reuses the unbound tab; the other creates.
    assert len(created) == 2
    infos = {i.run_id: i.session_id for i in reg.list_by_conversation("c1")}
    assert infos["run-a"] != infos["run-b"]


@pytest.mark.asyncio
async def test_concurrency_gate_refuses_when_full():
    reg, _ = _make_registry(max_sessions=2, idle_ttl_seconds=1000, max_lifetime_seconds=1000)
    await reg.acquire(_req("c1"))
    await reg.acquire(_req("c2"))
    with pytest.raises(BrowserSessionsBusyError):
        await reg.acquire(_req("c3"))
    assert len(reg) == 2


@pytest.mark.asyncio
async def test_idle_session_reclaimed_frees_a_slot():
    reg, created = _make_registry(max_sessions=1, idle_ttl_seconds=100, max_lifetime_seconds=10000)
    s1, _ = await reg.acquire(_req("c1"))
    # Make c1 idle past the TTL; acquiring c2 must reap it and free the only slot.
    s1.last_used = time.time() - 200
    s2, _ = await reg.acquire(_req("c2"))
    assert s1.closed is True
    assert s2 is not s1
    assert "c1" not in reg and "c2" in reg


@pytest.mark.asyncio
async def test_max_lifetime_forces_recycle():
    reg, created = _make_registry(max_sessions=4, idle_ttl_seconds=10000, max_lifetime_seconds=100)
    s1, _ = await reg.acquire(_req("c1"))
    s1.created_at = time.time() - 200  # aged past max lifetime, even if active
    s2, _ = await reg.acquire(_req("c1"))
    assert s1.closed is True and s2 is not s1
    assert len(created) == 2


@pytest.mark.asyncio
async def test_crashed_session_rebuilt_on_next_acquire():
    reg, created = _make_registry(max_sessions=4)
    s1, _ = await reg.acquire(_req("c1"))
    s1._alive = False  # driver crashed
    s2, _ = await reg.acquire(_req("c1"))
    assert s2 is not s1 and s2.alive
    assert len(created) == 2


@pytest.mark.asyncio
async def test_close_cascades_teardown():
    reg, _ = _make_registry(max_sessions=4)
    s1, _ = await reg.acquire(_req("c1"))
    await reg.create(_req("c1"))  # second tab
    assert len(reg.list_by_conversation("c1")) == 2
    await reg.close("c1")
    assert s1.closed is True
    assert "c1" not in reg
    assert len(reg.list_by_conversation("c1")) == 0


@pytest.mark.asyncio
async def test_close_session_tears_down_one_tab():
    reg, _ = _make_registry(max_sessions=4)
    _, _, sid_a = await reg.create(_req("c1"))
    s_b, _, sid_b = await reg.create(_req("c1"))
    await reg.close_session(sid_a)
    assert len(reg.list_by_conversation("c1")) == 1
    assert reg.peek("c1", session_id=sid_b) is s_b


@pytest.mark.asyncio
async def test_reap_closes_idle_and_dead_returns_count():
    reg, _ = _make_registry(max_sessions=8, idle_ttl_seconds=100, max_lifetime_seconds=10000)
    a, _ = await reg.acquire(_req("a"))
    b, _ = await reg.acquire(_req("b"))
    c, _ = await reg.acquire(_req("c"))
    a.last_used = time.time() - 200  # idle
    b._alive = False  # dead
    # c stays live/fresh
    closed = await reg.reap()
    assert closed == 2
    assert a.closed is True and b.closed is True
    assert "c" in reg and len(reg) == 1


@pytest.mark.asyncio
async def test_close_all_tears_down_every_session():
    reg, _ = _make_registry(max_sessions=8)
    sessions = [(await reg.acquire(_req(f"c{i}")))[0] for i in range(3)]
    await reg.close_all()
    assert all(s.closed for s in sessions)
    assert len(reg) == 0


# -- M1 (D13): live-hub observer seam + peek + watch-based TTL sparing -------------------


class _FakeObserver:
    def __init__(self, watched: set[str] | None = None) -> None:
        self.ready: list[tuple[str, str]] = []
        self.gone: list[tuple[str, str]] = []
        self.watched = watched or set()

    def on_session_ready(self, conversation_id: str, session_id: str = "") -> None:
        self.ready.append((conversation_id, session_id))

    def on_session_gone(self, conversation_id: str, session_id: str = "") -> None:
        self.gone.append((conversation_id, session_id))

    def is_watched(self, conversation_id: str, session_id: str | None = None) -> bool:
        return conversation_id in self.watched


@pytest.mark.asyncio
async def test_peek_returns_live_session_or_none_without_creating():
    reg, created = _make_registry(max_sessions=4)
    assert reg.peek("c1") is None  # peek never creates
    assert created == []
    s1, _ = await reg.acquire(_req("c1"))
    assert reg.peek("c1") is s1
    s1._alive = False  # dead → peek reports None (live view: session_closed, no auto-rebuild)
    assert reg.peek("c1") is None


@pytest.mark.asyncio
async def test_observer_notified_on_create_and_drop():
    reg, _ = _make_registry(max_sessions=4)
    obs = _FakeObserver()
    reg.set_observer(obs)
    await reg.acquire(_req("c1"))
    assert len(obs.ready) == 1 and obs.ready[0][0] == "c1" and obs.ready[0][1]
    sid = obs.ready[0][1]
    await reg.close("c1")
    assert obs.gone == [("c1", sid)]


@pytest.mark.asyncio
async def test_watched_session_is_spared_idle_reaping():
    reg, _ = _make_registry(max_sessions=4, idle_ttl_seconds=100, max_lifetime_seconds=100000)
    obs = _FakeObserver(watched={"c1"})
    reg.set_observer(obs)
    s1, _ = await reg.acquire(_req("c1"))
    s1.last_used = time.time() - 500  # idle well past the TTL
    assert await reg.reap() == 0  # a viewer is watching → not reaped
    assert "c1" in reg
    obs.watched.clear()  # last viewer left
    assert await reg.reap() == 1  # now idle-reaped
    assert "c1" not in reg


@pytest.mark.asyncio
async def test_watched_session_still_recycled_at_max_lifetime():
    reg, _ = _make_registry(max_sessions=4, idle_ttl_seconds=100000, max_lifetime_seconds=100)
    obs = _FakeObserver(watched={"c1"})
    reg.set_observer(obs)
    s1, _ = await reg.acquire(_req("c1"))
    s1.created_at = time.time() - 500  # aged past max lifetime even while watched
    assert await reg.reap() == 1  # max lifetime wins over the watch spare
    assert "c1" not in reg


# -- M2: host_kind 互斥 + session_not_found / session_bound_elsewhere --------------------


@pytest.mark.asyncio
async def test_acquire_host_kind_mismatch_raises_session_bound_elsewhere():
    from agentcore.tools.sandbox.browser.protocol import BrowserSessionAcquireError

    reg, _ = _make_registry(max_sessions=4)
    await reg.create(_req("c1"), host_kind="local", activate=True)
    with pytest.raises(BrowserSessionAcquireError) as ei:
        await reg.acquire(_req("c1", host_kind="sandbox"))
    assert ei.value.code == "session_bound_elsewhere"


@pytest.mark.asyncio
async def test_acquire_explicit_sid_missing_raises_session_not_found():
    from agentcore.tools.sandbox.browser.protocol import BrowserSessionAcquireError

    reg, _ = _make_registry(max_sessions=4)
    with pytest.raises(BrowserSessionAcquireError) as ei:
        await reg.acquire(_req("c1", session_id="no-such-sid"))
    assert ei.value.code == "session_not_found"
    assert len(reg) == 0  # does not recreate under the missing id


@pytest.mark.asyncio
async def test_acquire_explicit_sid_bound_other_run_raises_session_bound_elsewhere():
    from agentcore.tools.sandbox.browser.protocol import BrowserSessionAcquireError

    reg, _ = _make_registry(max_sessions=4)
    _, _, sid = await reg.create(_req("c1"), run_id="run-a", activate=True)
    with pytest.raises(BrowserSessionAcquireError) as ei:
        await reg.acquire(_req("c1", session_id=sid, run_id="run-b"))
    assert ei.value.code == "session_bound_elsewhere"

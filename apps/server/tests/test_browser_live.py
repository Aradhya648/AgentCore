"""BrowserLiveHub (M1 · D13): viewer-driven screencast lifecycle + frame fan-out.

Drives the hub with a fake session + a dict-based ``session_lookup`` (no gVisor), asserting
the pinned viewer semantics: first attach starts / last detach stops (after grace), no_session
when absent, started when present, session_closed on recycle, frame broadcast to all viewers,
bounded drop-oldest per-viewer queue, and the ``is_watched`` TTL-sparing signal.
"""

from __future__ import annotations

import asyncio

import pytest

from agentcore.runtime.browser.live import BrowserLiveHub, BrowserLiveViewer
from agentcore.runtime.events.types import EventType


class FakeSession:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self._alive = True
        self.listener = None
        self.started = 0
        self.stopped = 0

    @property
    def alive(self) -> bool:
        return self._alive

    def set_frame_listener(self, listener) -> None:
        self.listener = listener

    async def start_screencast(self) -> None:
        self.started += 1

    async def stop_screencast(self) -> None:
        self.stopped += 1

    def push_frame(self, b64: str = "AAAA", w: int = 1280, h: int = 800) -> None:
        if self.listener is not None:
            self.listener({"frame_b64": b64, "width": w, "height": h})


def _hub(sessions: dict[str, FakeSession], *, grace: float = 0.02, max_q: int = 8) -> BrowserLiveHub:
    return BrowserLiveHub(
        session_lookup=lambda cid: sessions.get(cid),
        grace_seconds=grace,
        max_queued_frames=max_q,
    )


async def _next(viewer: BrowserLiveViewer, timeout: float = 1.0):
    return await asyncio.wait_for(viewer.get(), timeout)


# -- viewer queue: bounded, drop-oldest -------------------------------------------------


def test_viewer_queue_drops_oldest_when_full():
    from agentcore.runtime.events import browser_live_status

    viewer = BrowserLiveViewer(max_queue=2)
    viewer.emit(browser_live_status("no_session"))  # oldest → will be dropped
    viewer.emit(browser_live_status("started"))
    viewer.emit(browser_live_status("session_closed"))  # overflow → drops the no_session
    assert viewer._queue.qsize() == 2


@pytest.mark.asyncio
async def test_viewer_close_wakes_consumer_with_sentinel():
    viewer = BrowserLiveViewer(max_queue=4)
    viewer.close()
    assert await _next(viewer) is None


# -- attach: no_session vs started ------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_without_session_emits_no_session():
    hub = _hub({})
    viewer = await hub.attach("c1")
    ev = await _next(viewer)
    assert ev.type is EventType.BROWSER_LIVE_STATUS and ev.payload["state"] == "no_session"


@pytest.mark.asyncio
async def test_first_attach_starts_screencast_and_emits_started():
    s = FakeSession("c1")
    hub = _hub({"c1": s})
    viewer = await hub.attach("c1")
    assert s.started == 1 and s.listener is not None
    ev = await _next(viewer)
    assert ev.payload["state"] == "started"


@pytest.mark.asyncio
async def test_second_viewer_reuses_running_screencast():
    s = FakeSession("c1")
    hub = _hub({"c1": s})
    await hub.attach("c1")
    await hub.attach("c1")
    assert s.started == 1  # screencast started once for the channel


# -- frame fan-out ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frame_broadcast_to_all_viewers():
    s = FakeSession("c1")
    hub = _hub({"c1": s})
    v1 = await hub.attach("c1")
    v2 = await hub.attach("c1")
    assert (await _next(v1)).payload["state"] == "started"
    assert (await _next(v2)).payload["state"] == "started"
    s.push_frame(b64="ZmZm", w=1200, h=700)
    for v in (v1, v2):
        ev = await _next(v)
        assert ev.type is EventType.BROWSER_LIVE_FRAME
        assert ev.payload == {"frame_b64": "ZmZm", "width": 1200, "height": 700}


# -- last detach stops after grace; reattach cancels the stop ---------------------------


@pytest.mark.asyncio
async def test_last_detach_stops_screencast_after_grace():
    s = FakeSession("c1")
    hub = _hub({"c1": s}, grace=0.02)
    v = await hub.attach("c1")
    await hub.detach("c1", v)
    await asyncio.sleep(0.06)
    assert s.stopped == 1 and s.listener is None


@pytest.mark.asyncio
async def test_reattach_within_grace_keeps_screencast_running():
    s = FakeSession("c1")
    hub = _hub({"c1": s}, grace=0.05)
    v1 = await hub.attach("c1")
    await hub.detach("c1", v1)  # arms the grace-period stop
    await hub.attach("c1")      # re-attach cancels it
    await asyncio.sleep(0.08)
    assert s.stopped == 0 and s.started == 1


# -- session appearing / disappearing while watched ------------------------------------


@pytest.mark.asyncio
async def test_session_ready_while_watching_starts_and_emits_started():
    sessions: dict[str, FakeSession] = {}
    hub = _hub(sessions, grace=1.0)
    viewer = await hub.attach("c1")
    assert (await _next(viewer)).payload["state"] == "no_session"

    s = FakeSession("c1")
    sessions["c1"] = s
    hub.on_session_ready("c1")
    await asyncio.sleep(0.02)
    assert s.started == 1
    assert (await _next(viewer)).payload["state"] == "started"


@pytest.mark.asyncio
async def test_session_gone_emits_session_closed_to_viewers():
    s = FakeSession("c1")
    hub = _hub({"c1": s})
    viewer = await hub.attach("c1")
    assert (await _next(viewer)).payload["state"] == "started"

    hub.on_session_gone("c1")
    await asyncio.sleep(0.02)
    assert (await _next(viewer)).payload["state"] == "session_closed"


# -- is_watched (TTL sparing signal) ----------------------------------------------------


@pytest.mark.asyncio
async def test_is_watched_tracks_viewer_presence():
    s = FakeSession("c1")
    hub = _hub({"c1": s}, grace=1.0)
    assert hub.is_watched("c1") is False
    v = await hub.attach("c1")
    assert hub.is_watched("c1") is True
    await hub.detach("c1", v)
    assert hub.is_watched("c1") is False


@pytest.mark.asyncio
async def test_detach_soon_schedules_removal():
    s = FakeSession("c1")
    hub = _hub({"c1": s}, grace=0.02)
    v = await hub.attach("c1")
    hub.detach_soon("c1", v)  # fire-and-forget (SSE-finally path)
    await asyncio.sleep(0.06)
    assert hub.is_watched("c1") is False
    assert s.stopped == 1


# -- multi session_id: independent channels (no cross-tab frame bleed) ------------------


@pytest.mark.asyncio
async def test_attach_different_session_ids_do_not_cross_frames():
    """Two tabs on the same conversation get isolated frame sinks."""
    s_a = FakeSession("c1")
    s_b = FakeSession("c1")
    by_sid = {"sid-a": s_a, "sid-b": s_b}

    hub = BrowserLiveHub(
        session_lookup=lambda cid, sid=None: by_sid.get(sid) if cid == "c1" else None,
        grace_seconds=1.0,
        max_queued_frames=8,
    )
    v_a = await hub.attach("c1", session_id="sid-a")
    v_b = await hub.attach("c1", session_id="sid-b")
    assert s_a.started == 1 and s_b.started == 1
    assert (await _next(v_a)).payload["state"] == "started"
    assert (await _next(v_b)).payload["state"] == "started"

    s_a.push_frame(b64="QUFB", w=100, h=50)
    s_b.push_frame(b64="QkJC", w=200, h=100)

    ev_a = await _next(v_a)
    ev_b = await _next(v_b)
    assert ev_a.type is EventType.BROWSER_LIVE_FRAME
    assert ev_b.type is EventType.BROWSER_LIVE_FRAME
    assert ev_a.payload == {"frame_b64": "QUFB", "width": 100, "height": 50}
    assert ev_b.payload == {"frame_b64": "QkJC", "width": 200, "height": 100}
    # Queues stay isolated — neither viewer got the other's frame.
    assert v_a._queue.empty()
    assert v_b._queue.empty()


@pytest.mark.asyncio
async def test_is_watched_is_scoped_to_session_pin():
    s_a = FakeSession("c1")
    s_b = FakeSession("c1")
    by_sid = {"sid-a": s_a, "sid-b": s_b}
    hub = BrowserLiveHub(
        session_lookup=lambda cid, sid=None: by_sid.get(sid) if cid == "c1" else None,
        grace_seconds=1.0,
        max_queued_frames=8,
    )
    v = await hub.attach("c1", session_id="sid-a")
    assert hub.is_watched("c1", "sid-a") is True
    assert hub.is_watched("c1", "sid-b") is False
    assert hub.is_watched("c1") is True
    await hub.detach("c1", v, session_id="sid-a")
    assert hub.is_watched("c1", "sid-a") is False

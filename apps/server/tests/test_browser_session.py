"""GVisorBrowserSession.close() teardown: natural-exit ordering, SIGKILL fallback, bounded runsc.

These pin the D9/D10 teardown contract validated end-to-end by the gVisor smoke
(scripts/smoke_browser_gvisor): after the `close` RPC the `runsc run` supervisor is given a
bounded window to exit on its own (a clean exit lets `runsc delete` finish fast instead of the
~120s orphan force-delete path); only a wedged supervisor is SIGKILLed. All runsc waits are
bounded so teardown can never block its callers forever. Everything is driven with fakes /
monkeypatched subprocess, so it runs off-Linux without runsc.
"""

from __future__ import annotations

import asyncio

import pytest

from agentcore.tools.sandbox.browser import gvisor_session as gs
from agentcore.tools.sandbox.browser.gvisor_session import GVisorBrowserSession

_CID = "agentcore-browser-test"


class _FakeChannel:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.closed = False

    async def request(self, action: str, args: dict, *, timeout: float) -> dict:
        self.requests.append(action)
        return {"id": 1, "ok": True, "closed": True}

    async def aclose(self) -> None:
        self.closed = True


class _FakeProcess:
    """Stand-in for the `runsc run` supervisor.

    ``natural_exit=True`` → ``wait()`` returns promptly (the supervisor followed the driver out).
    ``natural_exit=False`` → wedged: ``wait()`` blocks until ``kill()`` (the SIGKILL fallback).
    """

    def __init__(self, *, natural_exit: bool) -> None:
        self._natural_exit = natural_exit
        self.returncode: int | None = None
        self.killed = False
        self.waited = False
        self._exited = asyncio.Event()

    async def wait(self) -> int:
        self.waited = True
        if self._natural_exit:
            self.returncode = 0
            return 0
        await self._exited.wait()
        return self.returncode if self.returncode is not None else -9

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._exited.set()


class _FakeNetns:
    def __init__(self) -> None:
        self.torn = False

    async def teardown(self) -> None:
        self.torn = True


def _make_session(process: _FakeProcess, channel: _FakeChannel, netns: _FakeNetns):
    return GVisorBrowserSession(
        conversation_id="c1",
        slot=0,
        netns=netns,
        bundle_dir="/nonexistent/agentcore_browser_test_bundle",
        container_id=_CID,
        runsc_path="runsc",
        runtime_root="/tmp/agentcore-test-root",
        process=process,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
    )


def _record_runsc(session) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def _rec(*args: str) -> None:
        calls.append(args)

    session._runsc_cmd = _rec
    return calls


@pytest.mark.asyncio
async def test_close_awaits_natural_supervisor_exit_before_kill():
    proc = _FakeProcess(natural_exit=True)
    ch = _FakeChannel()
    netns = _FakeNetns()
    session = _make_session(proc, ch, netns)
    runsc_calls = _record_runsc(session)

    await session.close()

    assert ch.requests == ["close"]  # close RPC sent first
    assert ch.closed is True
    assert proc.waited is True  # waited for the supervisor to exit on its own
    assert proc.killed is False  # clean exit → never SIGKILLed (avoids orphan slow-delete)
    assert runsc_calls == [
        ("kill", _CID, "SIGKILL"),
        ("delete", "--force", _CID),
    ]
    assert netns.torn is True
    assert session.alive is False


@pytest.mark.asyncio
async def test_close_sigkills_wedged_supervisor_after_bounded_wait(monkeypatch):
    monkeypatch.setattr(gs, "_SUPERVISOR_EXIT_TIMEOUT", 0.05)
    proc = _FakeProcess(natural_exit=False)  # supervisor never exits on its own
    ch = _FakeChannel()
    netns = _FakeNetns()
    session = _make_session(proc, ch, netns)
    runsc_calls = _record_runsc(session)

    await asyncio.wait_for(session.close(), timeout=5)

    assert proc.killed is True  # bounded wait elapsed → SIGKILL fallback fired
    assert runsc_calls == [
        ("kill", _CID, "SIGKILL"),
        ("delete", "--force", _CID),
    ]
    assert netns.torn is True


@pytest.mark.asyncio
async def test_close_is_idempotent():
    proc = _FakeProcess(natural_exit=True)
    ch = _FakeChannel()
    session = _make_session(proc, ch, _FakeNetns())
    runsc_calls = _record_runsc(session)

    await session.close()
    assert len(runsc_calls) == 2
    await session.close()  # second call is a no-op (already torn down)
    assert len(runsc_calls) == 2
    assert ch.requests == ["close"]


@pytest.mark.asyncio
async def test_close_after_driver_crash_still_reclaims_resources():
    """A crashed session (``_alive=False``, teardown never ran) must still tear down fully.

    Idempotency is keyed on ``_closed``, not ``_alive`` — otherwise the netns/veth, the
    concurrency slot, the runsc container and the bundle dir of a crashed driver leak until
    process exit (they are host-side resources; the crash only killed the RPC channel).
    """
    proc = _FakeProcess(natural_exit=True)
    ch = _FakeChannel()
    netns = _FakeNetns()
    session = _make_session(proc, ch, netns)
    runsc_calls = _record_runsc(session)

    session._alive = False  # driver crash marked the session dead before any teardown

    await session.close()

    assert ch.requests == []  # dead channel: no close RPC attempted
    assert ch.closed is True
    assert runsc_calls == [
        ("kill", _CID, "SIGKILL"),
        ("delete", "--force", _CID),
    ]
    assert netns.torn is True

    await session.close()  # still idempotent afterwards
    assert len(runsc_calls) == 2


@pytest.mark.asyncio
async def test_run_runsc_bounded_abandons_wedged_runsc(monkeypatch):
    """A wedged `runsc` is abandoned after the bound (child killed), never blocking the caller."""
    monkeypatch.setattr(gs, "_RUNSC_CMD_TIMEOUT", 0.05)
    killed = {"value": False}

    class _WedgedProc:
        returncode = None

        def __init__(self) -> None:
            self._exited = asyncio.Event()

        async def wait(self) -> int:
            await self._exited.wait()
            return -9

        def kill(self) -> None:
            killed["value"] = True
            self._exited.set()

    async def _fake_exec(*_args, **_kwargs):
        return _WedgedProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    await asyncio.wait_for(
        gs._run_runsc_bounded("runsc", "/tmp/root", "delete", "--force", _CID), timeout=5
    )
    assert killed["value"] is True  # bounded wait elapsed → wedged runsc child killed


@pytest.mark.asyncio
async def test_run_runsc_bounded_swallows_spawn_failure(monkeypatch):
    """A missing/unspawnable runsc must not raise out of best-effort teardown."""

    async def _boom(*_args, **_kwargs):
        raise FileNotFoundError("runsc not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    await gs._run_runsc_bounded("runsc", "/tmp/root", "delete", "--force", _CID)

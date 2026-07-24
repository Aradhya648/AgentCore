"""SessionRosterWriter — fire-and-forget roster write-through + turn-end flush."""

from __future__ import annotations

import asyncio

import pytest

from agentcore.runtime.runs import RunSession, RunSpec
from agentcore.runtime.session_persistence import SessionRosterWriter


def _session(run_id: str, content: str = "v1") -> RunSession:
    return RunSession(
        run_id=run_id,
        spec=RunSpec(run_id=run_id, task="t", role="研究员"),
        transcript=[],
        content=content,
    )


@pytest.mark.asyncio
async def test_save_returns_before_underlying_completes():
    started = asyncio.Event()
    release = asyncio.Event()
    saved: list[str] = []

    async def slow_save(session: RunSession) -> None:
        started.set()
        await release.wait()
        saved.append(session.content)

    writer = SessionRosterWriter(slow_save)
    await writer.save(_session("r1", "done"))
    await asyncio.sleep(0)  # let the scheduled task reach the gate
    assert started.is_set()
    assert saved == []

    release.set()
    await writer.flush()
    assert saved == ["done"]


@pytest.mark.asyncio
async def test_same_run_id_coalesce_keeps_latest():
    """A later schedule for the same run_id supersedes an in-flight write."""
    gate = asyncio.Event()
    order: list[str] = []

    async def gated_save(session: RunSession) -> None:
        await gate.wait()
        order.append(session.content)

    writer = SessionRosterWriter(gated_save)
    await writer.save(_session("r1", "stale"))
    await writer.save(_session("r1", "fresh"))
    gate.set()
    await writer.flush()
    assert order == ["fresh"]


@pytest.mark.asyncio
async def test_wrap_none_is_none():
    assert SessionRosterWriter.wrap(None) is None

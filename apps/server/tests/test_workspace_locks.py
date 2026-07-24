"""Tests for the folder-level workspace lock (决策④).

Verifies that the same workspace key serializes (one task at a time, others
queue) while different keys run concurrently (a folder's work never blocks an
unrelated workspace). Deterministic via small sleeps + an ordered event log.
"""

import asyncio

from agentcore.workspace.locks import workspace_lock


async def test_same_key_serializes():
    events: list[str] = []

    async def worker(name: str) -> None:
        async with workspace_lock("ws/u1/f1"):
            events.append(f"{name}-enter")
            await asyncio.sleep(0.02)
            events.append(f"{name}-exit")

    await asyncio.gather(worker("A"), worker("B"))

    # Each enter is immediately followed by its own exit — no interleaving.
    assert events in (
        ["A-enter", "A-exit", "B-enter", "B-exit"],
        ["B-enter", "B-exit", "A-enter", "A-exit"],
    )


async def test_different_keys_run_concurrently():
    events: list[str] = []

    async def worker(key: str, name: str) -> None:
        async with workspace_lock(key):
            events.append(f"{name}-enter")
            await asyncio.sleep(0.02)
            events.append(f"{name}-exit")

    await asyncio.gather(worker("ws/u1/f1", "A"), worker("ws/u1/f2", "B"))

    # Both enter before either exits → they overlapped (no mutual exclusion).
    assert set(events[:2]) == {"A-enter", "B-enter"}


async def test_lock_released_after_block():
    key = "ws/u1/f1"
    async with workspace_lock(key):
        pass
    # Re-acquiring immediately must not block (the previous block released it).
    await asyncio.wait_for(_acquire_once(key), timeout=1.0)


async def _acquire_once(key: str) -> None:
    async with workspace_lock(key):
        return

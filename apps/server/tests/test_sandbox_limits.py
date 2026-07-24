"""灰度护栏：全局执行位限流（有界等待 → 快速失败）与 gVisor busy 结果语义。"""

from __future__ import annotations

import pytest

from agentcore.config import settings
from agentcore.tools.sandbox.limits import (
    reset_execution_slots,
    try_acquire_execution_slot,
)


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reset_execution_slots()
    yield
    reset_execution_slots()


async def test_slot_grants_then_rejects_at_capacity(monkeypatch):
    monkeypatch.setattr(settings, "gvisor_max_concurrent_executions", 1)
    monkeypatch.setattr(settings, "gvisor_slot_wait_seconds", 0.05)

    release = await try_acquire_execution_slot()
    assert release is not None

    # Capacity exhausted → bounded wait times out → fast-fail (None).
    assert await try_acquire_execution_slot() is None

    release()
    again = await try_acquire_execution_slot()
    assert again is not None
    again()


async def test_slot_capacity_change_takes_effect_on_next_acquire(monkeypatch):
    monkeypatch.setattr(settings, "gvisor_max_concurrent_executions", 1)
    monkeypatch.setattr(settings, "gvisor_slot_wait_seconds", 0.05)
    first = await try_acquire_execution_slot()
    assert first is not None

    # Ops bumps the cap: a fresh semaphore with the new capacity takes over.
    monkeypatch.setattr(settings, "gvisor_max_concurrent_executions", 2)
    a = await try_acquire_execution_slot()
    b = await try_acquire_execution_slot()
    assert a is not None and b is not None
    assert await try_acquire_execution_slot() is None
    for rel in (first, a, b):
        rel()


async def test_gvisor_busy_result_is_explainable(monkeypatch, tmp_path):
    from agentcore.tools.sandbox.gvisor import GVisorSandbox

    monkeypatch.setattr(settings, "gvisor_max_concurrent_executions", 2)
    monkeypatch.setattr(settings, "gvisor_slot_wait_seconds", 15.0)
    sandbox = GVisorSandbox(runtime_root=str(tmp_path / "rt"))

    result = sandbox._slot_busy_result(start=0.0)  # noqa: SLF001

    assert result.success is False
    assert result.exit_code == -1
    assert "并发上限 2" in result.stderr
    assert "稍后重试" in result.stderr

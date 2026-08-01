"""Boot-time browser netns health probe → ``browser_execution_enabled_for`` gate."""

from __future__ import annotations

from typing import Any

import pytest

from agentcore.config import settings
from agentcore.tools.sandbox.browser.netns import (
    NetnsError,
    browser_netns_health,
    probe_browser_netns_at_startup,
    set_browser_netns_health_for_tests,
)


@pytest.mark.asyncio
async def test_probe_skipped_when_gvisor_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gvisor_enabled", False)
    called: list[Any] = []

    async def _boom(*_a: Any, **_k: Any) -> tuple[int, str]:
        called.append(True)
        raise AssertionError("ip must not run when gvisor is off")

    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns._ip", _boom)
    await probe_browser_netns_at_startup()
    assert browser_netns_health() is None
    assert called == []


@pytest.mark.asyncio
async def test_probe_skipped_on_non_linux(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns.sys.platform", "win32")
    called: list[Any] = []

    async def _boom(*_a: Any, **_k: Any) -> tuple[int, str]:
        called.append(True)
        raise AssertionError("ip must not run off Linux")

    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns._ip", _boom)
    await probe_browser_netns_at_startup()
    assert browser_netns_health() is None
    assert called == []


@pytest.mark.asyncio
async def test_probe_success_caches_healthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns.sys.platform", "linux")
    calls: list[tuple[str, ...]] = []

    async def _fake_ip(*args: str, check: bool = True) -> tuple[int, str]:
        calls.append(args)
        return 0, ""

    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns._ip", _fake_ip)
    await probe_browser_netns_at_startup()
    assert browser_netns_health() is True
    assert ("netns", "add", "acbrwprobe") in calls
    assert ("netns", "del", "acbrwprobe") in calls


@pytest.mark.asyncio
async def test_probe_failure_caches_unhealthy_without_raising(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns.sys.platform", "linux")

    async def _fail(*args: str, check: bool = True) -> tuple[int, str]:
        if args[:2] == ("netns", "add"):
            raise NetnsError("mkdir /run/netns failed: Permission denied")
        return 0, ""

    monkeypatch.setattr("agentcore.tools.sandbox.browser.netns._ip", _fail)
    await probe_browser_netns_at_startup()
    assert browser_netns_health() is False


def test_set_for_tests_roundtrip():
    set_browser_netns_health_for_tests(True)
    assert browser_netns_health() is True
    set_browser_netns_health_for_tests(False)
    assert browser_netns_health() is False
    set_browser_netns_health_for_tests(None)
    assert browser_netns_health() is None

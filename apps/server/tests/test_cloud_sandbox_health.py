"""Boot-time cloud sandbox health probe → ``code_execution_enabled_for`` gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentcore.config import settings
from agentcore.tools.builtin import code_execution_enabled_for
from agentcore.tools.sandbox.cloud_health import (
    cloud_sandbox_health,
    probe_cloud_sandbox_at_startup,
    set_cloud_sandbox_health_for_tests,
)
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import LocalBackend


class _FakeSandbox:
    def __init__(self, *, ok: bool = True, raise_exc: BaseException | None = None):
        self._ok = ok
        self._raise = raise_exc

    async def health_check(self) -> bool:
        if self._raise is not None:
            raise self._raise
        return self._ok


class _SandboxWithoutHealth:
    """Provider that omits ``health_check`` — must be treated as unhealthy."""


@pytest.mark.asyncio
async def test_probe_skipped_when_cloud_execution_config_off(monkeypatch: pytest.MonkeyPatch):
    called: list[Any] = []

    def _boom() -> Any:
        called.append(True)
        raise AssertionError("sandbox must not be built when config is off")

    monkeypatch.setattr(
        "agentcore.workspace.locate._default_server_sandbox",
        _boom,
    )
    await probe_cloud_sandbox_at_startup()
    assert cloud_sandbox_health() is None
    assert called == []


@pytest.mark.asyncio
async def test_probe_success_caches_healthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr(
        "agentcore.workspace.locate._default_server_sandbox",
        lambda: _FakeSandbox(ok=True),
    )
    await probe_cloud_sandbox_at_startup()
    assert cloud_sandbox_health() is True


@pytest.mark.asyncio
async def test_probe_failure_caches_unhealthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "code_execute_cloud_enabled", True)
    monkeypatch.setattr(settings, "code_execute_cloud_unsafe_ack", True)
    monkeypatch.setattr(
        "agentcore.workspace.locate._default_server_sandbox",
        lambda: _FakeSandbox(ok=False),
    )
    await probe_cloud_sandbox_at_startup()
    assert cloud_sandbox_health() is False


@pytest.mark.asyncio
async def test_probe_exception_caches_unhealthy_without_raising(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr(
        "agentcore.workspace.locate._default_server_sandbox",
        lambda: _FakeSandbox(raise_exc=RuntimeError("runsc gone")),
    )
    await probe_cloud_sandbox_at_startup()
    assert cloud_sandbox_health() is False


@pytest.mark.asyncio
async def test_probe_missing_health_check_caches_unhealthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    monkeypatch.setattr(
        "agentcore.workspace.locate._default_server_sandbox",
        lambda: _SandboxWithoutHealth(),
    )
    await probe_cloud_sandbox_at_startup()
    assert cloud_sandbox_health() is False


def test_local_backend_ignores_unhealthy_cloud_probe(tmp_path: Path):
    set_cloud_sandbox_health_for_tests(False)
    assert code_execution_enabled_for(LocalBackend()) is True
    # Server backend with config off stays false regardless of probe.
    assert code_execution_enabled_for(ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())) is False

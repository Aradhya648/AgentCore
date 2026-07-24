"""SubprocessSandbox execution under any event loop (incl. Windows SelectorEventLoop).

uvicorn ``--reload`` on Windows installs a ``SelectorEventLoop``, which cannot create
asyncio subprocess transports (``NotImplementedError``). SubprocessSandbox must therefore
use blocking ``subprocess`` in a worker thread — these tests pin that contract.
"""

from __future__ import annotations

import asyncio
import sys

from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.tools.sandbox.subprocess import SubprocessSandbox


def _make_selector_loop() -> asyncio.AbstractEventLoop:
    """Build a SelectorEventLoop the way Windows reload / policy would."""
    if sys.platform == "win32":
        # Match uvicorn --reload: WindowsSelectorEventLoopPolicy → SelectorEventLoop.
        return asyncio.SelectorEventLoop()
    return asyncio.SelectorEventLoop()


def test_execute_succeeds_under_selector_event_loop():
    """Real command must succeed on SelectorEventLoop (no NotImplementedError)."""

    async def _run() -> None:
        sandbox = SubprocessSandbox()
        result = await sandbox.execute(
            ExecutionRequest(
                code="print('selector-ok')",
                language="python",
                timeout_seconds=10,
            )
        )
        assert result.success is True
        assert "selector-ok" in result.stdout
        assert result.exit_code == 0

    loop = _make_selector_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def test_timeout_returns_graceful_result_under_selector_event_loop():
    """Timeout contract: success=False, exit_code=-1, stderr mentions Timeout."""

    async def _run() -> None:
        sandbox = SubprocessSandbox()
        result = await sandbox.execute(
            ExecutionRequest(
                code="import time; time.sleep(5)",
                language="python",
                timeout_seconds=1,
            )
        )
        assert result.success is False
        assert result.exit_code == -1
        assert "Timeout" in result.stderr

    loop = _make_selector_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def test_bash_missing_returns_actionable_stderr(monkeypatch):
    """Windows-common: no bash on PATH → fail fast, steer to python/javascript."""
    import shutil

    real_which = shutil.which

    def _which(cmd: str, *args, **kwargs):
        if cmd == "bash":
            return None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _which)

    async def _run() -> None:
        sandbox = SubprocessSandbox()
        result = await sandbox.execute(
            ExecutionRequest(code="echo hi", language="bash", timeout_seconds=5)
        )
        assert result.success is False
        assert result.exit_code == 127
        assert "bash" in result.stderr
        assert "python" in result.stderr.lower() or "javascript" in result.stderr.lower()

    asyncio.run(_run())

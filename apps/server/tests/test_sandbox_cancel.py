"""SubprocessSandbox cancel-safety (B1 取消安全).

A ``code_execute`` call aborted mid-flight — by the engine's tool-timeout backstop
or a user stop propagating ``CancelledError`` into the await — must not leave the
child process running as an orphan. Cancel path: assert the child PID is dead (not
a wall-clock race against ``sleep`` + sentinel write, which flaps on slow Win
``taskkill``). Timeout paths still use the sentinel proof.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.tools.sandbox.subprocess import SubprocessSandbox


def _pid_alive(pid: int) -> bool:
    """True if ``pid`` still refers to a live process."""
    if sys.platform == "win32":
        import ctypes

        # SYNCHRONIZE is enough to probe existence without needing PROCESS_QUERY_*.
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _wait_until(predicate, *, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def test_cancel_kills_subprocess_no_orphan(tmp_path: Path):
    pid_file = tmp_path / "pid.txt"
    sentinel = tmp_path / "ran.txt"
    # Long sleep so cancel always wins the race once the child has published its pid;
    # the assertion is "pid dead", not "wait past sleep then check sentinel".
    code = (
        "import os, time, pathlib\n"
        f"pathlib.Path(r'{pid_file.as_posix()}').write_text(str(os.getpid()))\n"
        "time.sleep(30.0)\n"
        f"pathlib.Path(r'{sentinel.as_posix()}').write_text('done')\n"
    )
    sandbox = SubprocessSandbox()
    request = ExecutionRequest(code=code, language="python", timeout_seconds=60)

    task = asyncio.create_task(sandbox.execute(request))
    assert await _wait_until(pid_file.exists, timeout=5.0), "child never published pid"
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert _pid_alive(pid)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert await _wait_until(lambda: not _pid_alive(pid), timeout=10.0), (
        f"child pid {pid} still alive after cancel"
    )
    assert not sentinel.exists()


async def test_timeout_kills_subprocess_no_orphan(tmp_path: Path):
    # The same guarantee on the tool's own timeout path: the sandbox's wait_for fires
    # at 1s, the child (sleeping 3s) is killed, and a graceful timeout result returns.
    sentinel = tmp_path / "ran.txt"
    code = (
        "import time, pathlib\n"
        "time.sleep(3.0)\n"
        f"pathlib.Path('{sentinel.as_posix()}').write_text('done')\n"
    )
    sandbox = SubprocessSandbox()
    request = ExecutionRequest(code=code, language="python", timeout_seconds=1)

    result = await sandbox.execute(request)
    assert result.success is False  # graceful SandboxTimeout result (exit_code -1)

    # Past the child's 3s write point (≈1s already elapsed in execute); a killed
    # process never writes the sentinel.
    await asyncio.sleep(2.5)
    assert not sentinel.exists()


async def test_timeout_kills_whole_tree_not_just_direct_child(tmp_path: Path):
    """A helper the executed code ITSELF spawns must die too, not just the direct child.

    Otherwise the grandchild orphans — keeping its inherited cwd (the workspace) locked
    in Windows "delete-pending" limbo — and writes its sentinel long after we believed
    the call was over. A direct-only ``process.kill()`` would let it survive; the
    process-tree reap (``killpg`` / ``taskkill /T``) takes it down with the parent.
    """
    sentinel = tmp_path / "grandchild.txt"
    grandchild = (
        f"import time, pathlib; time.sleep(2.0); "
        f"pathlib.Path(r'{sentinel.as_posix()}').write_text('done')"
    )
    code = (
        "import subprocess, sys\n"
        f"proc = subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "proc.wait()\n"  # parent stays alive holding the tree until timeout fires
    )
    sandbox = SubprocessSandbox()
    request = ExecutionRequest(code=code, language="python", timeout_seconds=1)

    result = await sandbox.execute(request)
    assert result.success is False  # timed out at 1s

    # Past the grandchild's 2s write point; a true tree-kill means it never lands.
    await asyncio.sleep(2.0)
    assert not sentinel.exists()

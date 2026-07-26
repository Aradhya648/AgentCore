"""SubprocessSandbox — run code in a child process (MVP; NOT an isolation boundary).

What it actually provides:
- Timeout enforcement (kill the whole process tree on timeout / cancel)
- A per-execution temp dir used as the default working directory
- stdout/stderr capture

What it does NOT provide — read before enabling on a shared/cloud host:
- NO real isolation: the child runs with the **full privileges of the API process**
  (filesystem read/write, free network egress, and access to in-process secrets such as
  JWT_SECRET_KEY / ENCRYPTION_KEY and every user's encrypted keys).
- NO namespace / seccomp / cgroup / rlimit / egress controls of any kind.

So it is safe ONLY where the caller already trusts the code: local/sidecar mode
(``location=local`` — the user's own machine). On a cloud/server worker it is gated off
by default and guarded at startup (see ``code_execute_cloud_enabled`` /
``code_execute_cloud_unsafe_ack`` and ``main._validate_production_security``); a true
sandbox (container/gVisor/nsjail/firecracker) is required before exposing it to
untrusted input (SEC-005).

Implementation note: child processes are spawned with the blocking ``subprocess``
stdlib inside a worker thread (``run_in_executor``). This avoids
``asyncio.create_subprocess_exec``, which raises ``NotImplementedError`` on Windows
when the running loop is a ``SelectorEventLoop`` (uvicorn ``--reload``).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from agentcore.core.errors import SandboxError, SandboxTimeoutError
from agentcore.tools.sandbox.protocol import (
    ExecutionRequest,
    ExecutionResult,
    SandboxCapabilities,
)

_IS_WINDOWS = sys.platform == "win32"

_LANGUAGE_COMMANDS: dict[str, list[str]] = {
    "python": ["python", "-u"],
    "javascript": ["node"],
    "bash": ["bash"],
}

_FILE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "bash": ".sh",
}

# NUL density at/above this → treat the chunk as UTF-16LE (ASCII-range text).
# WSL / some Win32 tools emit UTF-16LE; naive UTF-8 yields ``w\0s\0l\0…``.
_NUL_DENSITY_UTF16 = 0.3

_GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)

_BASH_UNAVAILABLE_HINT = (
    "本机没有可用的 bash（Windows 上 PATH 的 bash 常是不可用的 WSL 蹦床）。"
    "请改用 language=javascript 或 python 直接跑代码，不要用 bash 外壳包一层。"
)


def _decode_pipe_bytes(chunk: bytes) -> str:
    """Decode a subprocess pipe chunk; re-decode as UTF-16LE when NUL-dense."""
    if len(chunk) >= 4 and chunk.count(0) / len(chunk) >= _NUL_DENSITY_UTF16:
        try:
            return chunk.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    return chunk.decode("utf-8", errors="replace")


def _is_wsl_bash_trampoline(path: str) -> bool:
    """True when ``path`` is the Windows System32/SysWOW64 WSL bash trampoline."""
    norm = path.replace("/", "\\").lower()
    return norm.endswith("\\system32\\bash.exe") or norm.endswith(
        "\\syswow64\\bash.exe"
    )


def _which_all(cmd: str) -> list[str]:
    """All PATH hits for ``cmd`` (``shutil.which`` only returns the first)."""
    path_env = os.environ.get("PATH", "")
    if not path_env:
        return []
    names: list[str]
    if _IS_WINDOWS:
        exts = os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";")
        names = [cmd + ext for ext in exts] + [cmd]
    else:
        names = [cmd]
    found: list[str] = []
    seen: set[str] = set()
    for directory in path_env.split(os.pathsep):
        if not directory:
            continue
        for name in names:
            candidate = os.path.join(directory, name)
            key = candidate.lower() if _IS_WINDOWS else candidate
            if key in seen:
                continue
            # Windows has no meaningful X_OK; POSIX still requires execute bit.
            if os.path.isfile(candidate) and (
                _IS_WINDOWS or os.access(candidate, os.X_OK)
            ):
                seen.add(key)
                found.append(candidate)
    return found


def resolve_bash_launcher() -> str | None:
    """Resolve a usable bash binary.

    Windows: prefer Git Bash; skip System32 WSL trampoline; else ``None`` (honest
    reject — never hang on a broken trampoline). Non-Windows: first PATH bash.
    """
    if not _IS_WINDOWS:
        return shutil.which("bash")

    for candidate in _GIT_BASH_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        local_git = os.path.join(local, "Programs", "Git", "bin", "bash.exe")
        if os.path.isfile(local_git):
            return local_git
    for candidate in _which_all("bash"):
        if not _is_wsl_bash_trampoline(candidate):
            return candidate
    return None


def _resolve_language_cmd(language: str) -> list[str] | None:
    """Build argv for ``language``, or ``None`` when the launcher is unavailable.

    Bash is absolutized (skip WSL trampoline). python/node keep bare names so
    Windows PATHEXT / ``.cmd`` shims still resolve via ``CreateProcess``.
    """
    base = list(_LANGUAGE_COMMANDS[language])
    if language == "bash":
        bash = resolve_bash_launcher()
        if bash is None:
            return None
        return [bash]
    if shutil.which(base[0]) is None:
        return None
    return base


def probe_available_languages() -> tuple[str, ...]:
    """Which ``code_execute`` languages have a usable launcher on this host.

    Same truth as execute-time resolution — callers trim the tool schema so
    unavailable languages (e.g. Windows WSL bash trampoline) never appear.
    """
    return tuple(
        lang
        for lang in ("python", "javascript", "bash")
        if _resolve_language_cmd(lang) is not None
    )


def _launcher_missing_stderr(language: str, launcher: str) -> str:
    if language == "bash":
        return (
            f"代码执行环境启动失败：找不到可用的命令 {launcher!r}。 "
            f"{_BASH_UNAVAILABLE_HINT}"
        )
    if language == "python":
        hint = " 请确认 PATH 上有 python 可执行文件。"
    elif language == "javascript":
        hint = " 请确认 PATH 上有 node 可执行文件。"
    else:
        hint = ""
    return f"代码执行环境启动失败：找不到命令 {launcher!r}。{hint}"


class _CancelledError(Exception):
    """Internal: blocking run aborted because the asyncio caller was cancelled."""


def _new_group_kwargs() -> dict:
    """Spawn kwargs that make the child the head of its own killable group.

    Killing only the direct child (``process.kill()``) leaves any helper it spawned
    running as an orphan — and on Windows an orphan keeps its inherited cwd (the
    workspace / temp dir) locked in "delete-pending" limbo, so that directory can
    never be removed until the stray handle closes. POSIX: ``start_new_session`` makes
    the child a process-group leader so cleanup can ``killpg`` the whole group. Windows
    needs no flag — ``taskkill /T`` walks the live parent→child tree by pid.
    """
    return {} if _IS_WINDOWS else {"start_new_session": True}


def _reap_tree_sync(process: subprocess.Popen[bytes], pid: int) -> None:
    """Kill the child AND every descendant it spawned, then reap the child.

    Only fires while the child is still alive (``poll() is None``) — its own
    timeout, an external cancel, or a hang — so the pid is unambiguously ours and not
    yet recycled (no risk of signalling an unrelated process). A child that already
    exited cleanly is left alone. Best-effort throughout: never raises.
    """
    if process.poll() is not None:
        return
    if _IS_WINDOWS:
        # /T = whole descendant tree, /F = force; run while the parent pid is still
        # live so the tree is intact (it reparents nothing on Windows once dead).
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        # SIGKILL the child's whole process group (pgid == leader pid).
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        process.wait(timeout=5)


def _read_pipe(
    stream: object,
    stream_name: str,
    buffer: list[str],
    on_chunk: Callable[[str, str], None] | None,
) -> None:
    """Read from a subprocess pipe in chunks, optionally forwarding each chunk."""
    read = getattr(stream, "read", None)
    if read is None:
        return
    while True:
        chunk = read(2048)
        if not chunk:
            break
        text = _decode_pipe_bytes(chunk)
        buffer.append(text)
        if on_chunk:
            on_chunk(stream_name, text)


def _execute_blocking(
    *,
    cmd: list[str],
    cwd: str,
    env: dict[str, str] | None,
    stdin_bytes: bytes | None,
    timeout_seconds: float,
    cancel_flag: threading.Event,
    done_event: threading.Event,
    proc_holder: dict[str, subprocess.Popen[bytes]],
    on_output: Callable[[str, str], None] | None,
    loop: asyncio.AbstractEventLoop | None,
) -> tuple[str, str, int]:
    """Run the child with blocking stdlib subprocess.

    Raises ``SandboxTimeoutError`` on timeout and ``_CancelledError`` when ``cancel_flag``
    is set. Always sets ``done_event`` before returning/raising.
    """

    def emit(stream_name: str, text: str) -> None:
        if on_output is None:
            return
        if loop is None:
            on_output(stream_name, text)
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(on_output, stream_name, text)

    process: subprocess.Popen[bytes] | None = None
    readers: list[threading.Thread] = []
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if stdin_bytes is not None else None,
            cwd=cwd,
            env=env,
            **_new_group_kwargs(),
        )
        # Capture the pid up front: after a clean exit the OS can recycle it, so
        # cleanup keys off this snapshot.
        child_pid = process.pid
        proc_holder["proc"] = process

        if stdin_bytes is not None and process.stdin is not None:
            with contextlib.suppress(BrokenPipeError):
                process.stdin.write(stdin_bytes)
                process.stdin.close()

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_buf: list[str] = []
        stderr_buf: list[str] = []
        t_out = threading.Thread(
            target=_read_pipe,
            args=(process.stdout, "stdout", stdout_buf, emit),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_read_pipe,
            args=(process.stderr, "stderr", stderr_buf, emit),
            daemon=True,
        )
        readers = [t_out, t_err]
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if cancel_flag.is_set():
                _reap_tree_sync(process, child_pid)
                raise _CancelledError
            if time.monotonic() >= deadline:
                _reap_tree_sync(process, child_pid)
                raise SandboxTimeoutError(
                    f"Execution exceeded {timeout_seconds}s timeout"
                )
            # Short sleep so cancel / timeout are noticed promptly without spinning.
            time.sleep(0.05)

        for t in readers:
            t.join(timeout=5)

        return "".join(stdout_buf), "".join(stderr_buf), process.returncode or 0
    except (_CancelledError, SandboxTimeoutError):
        for t in readers:
            t.join(timeout=5)
        raise
    finally:
        if process is not None and process.poll() is None:
            _reap_tree_sync(process, process.pid)
        done_event.set()


async def _cleanup_tempdir(path: str) -> None:
    """Best-effort removal of an execution temp dir.

    On Windows the subprocess holds its cwd (the temp dir) and the OS releases
    that handle only shortly after the process exits, so an immediate rmtree can
    fail with a sharing violation (WinError 32). Retry a few times, then give up:
    a stray temp dir is harmless and eventually reaped by the OS.
    """
    for delay in (0.0, 0.05, 0.2, 0.5):
        if delay:
            await asyncio.sleep(delay)
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            continue
    shutil.rmtree(path, ignore_errors=True)


class SubprocessSandbox:
    """Restricted subprocess sandbox for MVP code execution."""

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            isolation="subprocess",
            supports_network=True,
            max_memory_mb=512,
            max_timeout_seconds=90,
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute code in a temporary directory with timeout."""
        if request.language not in _LANGUAGE_COMMANDS:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"Unsupported language: {request.language}",
                exit_code=1,
                duration_ms=0,
            )

        cmd_prefix = _resolve_language_cmd(request.language)
        if cmd_prefix is None:
            launcher = _LANGUAGE_COMMANDS[request.language][0]
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=_launcher_missing_stderr(request.language, launcher),
                exit_code=127,
                duration_ms=0,
            )

        start = time.monotonic()

        tmpdir = tempfile.mkdtemp(prefix="agentcore_sandbox_")
        try:
            ext = _FILE_EXTENSIONS[request.language]
            code_file = Path(tmpdir) / f"main{ext}"
            code_file.write_text(request.code, encoding="utf-8")

            cmd = cmd_prefix + [str(code_file)]
            cancel_flag = threading.Event()
            done_event = threading.Event()
            proc_holder: dict[str, subprocess.Popen[bytes]] = {}
            loop = asyncio.get_running_loop()

            def blocking() -> tuple[str, str, int]:
                return _execute_blocking(
                    cmd=cmd,
                    cwd=request.cwd or tmpdir,
                    env=(
                        {**os.environ, **request.env}
                        if request.env
                        else None
                    ),
                    stdin_bytes=request.stdin.encode() if request.stdin else None,
                    timeout_seconds=float(request.timeout_seconds),
                    cancel_flag=cancel_flag,
                    done_event=done_event,
                    proc_holder=proc_holder,
                    on_output=request.on_output,
                    loop=loop,
                )

            try:
                worker = loop.run_in_executor(None, blocking)
                try:
                    stdout_str, stderr_str, exit_code = await worker
                except asyncio.CancelledError:
                    # Caller aborted (engine tool-timeout backstop / user stop).
                    # Signal the worker, kill the tree from this side too (covers the
                    # race where Popen has not yet been registered), then wait for the
                    # worker to finish so cwd handles are released before temp cleanup.
                    cancel_flag.set()
                    proc = proc_holder.get("proc")
                    if proc is not None:
                        await asyncio.to_thread(_reap_tree_sync, proc, proc.pid)
                    with contextlib.suppress(Exception):
                        await asyncio.shield(
                            asyncio.to_thread(done_event.wait, 30.0)
                        )
                    raise

                duration_ms = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    success=exit_code == 0,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )

            except SandboxTimeoutError:
                duration_ms = int((time.monotonic() - start) * 1000)
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=f"Timeout: execution exceeded {request.timeout_seconds}s",
                    exit_code=-1,
                    duration_ms=duration_ms,
                )
            except OSError as e:
                raise SandboxError(f"代码执行环境启动失败：{e}") from e
        finally:
            await _cleanup_tempdir(tmpdir)

    async def health_check(self) -> bool:
        """Verify the sandbox can execute code."""
        try:
            result = await self.execute(
                ExecutionRequest(code="print('ok')", language="python", timeout_seconds=5)
            )
            return result.success and "ok" in result.stdout
        except Exception:
            return False

"""GVisor (runsc) based sandbox for secure code execution.

Execution model (安全权限与治理.md §五, as-built):

- **copy-in / copy-out 产物写回**: when the request carries a workspace ``cwd``,
  the workspace is COPIED into a per-run staging dir mounted **rw** at
  ``/workspace`` (cwd), so relative-path writes work like the local sandbox;
  after the process completes, new/changed files are copied back into the real
  workspace under caps and reported via ``ExecutionResult.written_files``.
  Timeout / cancel skip the copy-out (a killed run must not persist
  half-written artifacts).
- **灰度护栏**: a process-global slot limiter caps concurrent executions
  (``GVISOR_MAX_CONCURRENT_EXECUTIONS``), with a bounded grace wait before an
  explainable busy failure; memory/timeout ceilings come from settings.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from agentcore.config import settings
from agentcore.core.errors import SandboxError, SandboxTimeoutError
from agentcore.core.logging import get_logger
from agentcore.tools.sandbox.limits import try_acquire_execution_slot
from agentcore.tools.sandbox.protocol import (
    ExecutionRequest,
    ExecutionResult,
    SandboxCapabilities,
)
from agentcore.tools.sandbox.staging import (
    TreeState,
    collect_changes,
    prepare_bind_tree_for_sandbox,
    stage_workspace,
    write_back,
)

logger = get_logger(__name__)

_IS_LINUX = sys.platform == "linux"

_LANGUAGE_COMMANDS: dict[str, list[str]] = {
    "python": ["python3", "-u"],
    "javascript": ["node"],
    "bash": ["bash"],
}

_FILE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "bash": ".sh",
}

_HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")

# runsc bind mounts sourced from the api container overlay (default /tmp) fail
# mkdir with EINVAL inside gVisor; bundles must live on the DATA_DIR volume.
_LEGACY_RUNTIME_ROOT = "/tmp/agentcore-sandbox"
_ARTIFACT_MARKER = "__AGENTCORE_ARTIFACTS__"


def _resolve_runtime_root(explicit: str | None) -> str:
    if explicit:
        return explicit
    configured = settings.gvisor_runtime_root
    if configured != _LEGACY_RUNTIME_ROOT:
        return configured
    for candidate in (
        Path(settings.data_dir) / "sandbox",
        Path("/data/sandbox"),
    ):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return str(candidate.resolve())
        except OSError:
            continue
    return configured


def _strip_artifact_payload(stdout: str) -> tuple[str, dict[str, str]]:
    """Remove the sandbox artifact trailer from stdout (tmpfs → host bridge)."""
    idx = stdout.rfind(_ARTIFACT_MARKER)
    if idx == -1:
        return stdout, {}
    prefix = stdout[:idx]
    tail = stdout[idx + len(_ARTIFACT_MARKER) :].lstrip("\n")
    line = tail.split("\n", 1)[0].strip()
    if not line:
        return prefix, {}
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("sandbox.artifact_payload_invalid")
        return prefix, {}
    if not isinstance(payload, dict):
        return prefix, {}
    files = {k: v for k, v in payload.items() if isinstance(k, str) and isinstance(v, str)}
    return prefix, files


def _materialize_artifacts(staging_dir: Path, payload: dict[str, str]) -> None:
    """Write sandbox tmpfs artifacts onto the host staging tree (mkdir OK on host)."""
    for rel, encoded in payload.items():
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            continue
        dest = staging_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(encoded.encode("ascii")))


async def _read_stream(
    stream: asyncio.StreamReader | None,
    stream_name: str,
    buffer: list[str],
    on_output: Callable[[str, str], None] | None,
) -> None:
    """Read from a subprocess stream in chunks, optionally forwarding each chunk."""
    if stream is None:
        return
    while True:
        chunk = await stream.read(2048)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        buffer.append(text)
        if on_output:
            on_output(stream_name, text)


class GVisorSandbox:
    """SandboxProvider implementation using gVisor runsc."""

    def __init__(
        self,
        *,
        runsc_path: str = "runsc",
        workspace_root: str | None = None,
        runtime_root: str | None = None,
    ) -> None:
        self._runsc = runsc_path
        self._workspace_root = workspace_root
        self._runtime_root = _resolve_runtime_root(runtime_root)
        os.makedirs(self._runtime_root, exist_ok=True)

    def capabilities(self) -> SandboxCapabilities:
        return SandboxCapabilities(
            isolation="gvisor",
            supports_network=True,  # restricted mode can enable; default still none
            max_memory_mb=settings.gvisor_memory_limit_mb,
            max_timeout_seconds=settings.gvisor_timeout_max_seconds,
        )

    async def health_check(self) -> bool:
        """Smoke-run a minimal ``runsc run`` (not just ``--version``).

        Exercises global flags before ``run`` and the full bundle path so
        AppArmor / userns / flag-order faults fail the boot probe honestly.
        """
        if not _IS_LINUX:
            return False

        container_id = f"agentcore-health-{uuid.uuid4().hex[:12]}"
        bundle_dir = tempfile.mkdtemp(prefix="agentcore_gvisor_health_", dir=self._runtime_root)
        try:
            rootfs = Path(bundle_dir) / "rootfs"
            rootfs.mkdir()
            (Path(bundle_dir) / "config.json").write_text(
                json.dumps(self._build_health_oci_config()),
                encoding="utf-8",
            )
            cmd = self._build_run_cmd(
                bundle_dir=bundle_dir,
                container_id=container_id,
                network_mode="none",
            )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                logger.debug(
                    "sandbox.health_check_failed",
                    returncode=proc.returncode,
                    detail=detail[:200] or None,
                )
                return False
            return True
        except (FileNotFoundError, OSError) as exc:
            logger.debug("sandbox.health_check_failed", error=str(exc)[:200])
            return False
        finally:
            await self._runsc_cmd("delete", "--force", container_id)
            shutil.rmtree(bundle_dir, ignore_errors=True)

    # -- 会话面 (D9): long-lived browser sessions, added ALONGSIDE execute() -------
    # A separate surface for the L3 team browser — one-shot execute() is unchanged.
    def supports_browser_sessions(self) -> bool:
        """True where a real gVisor browser sandbox can run (Linux)."""
        from agentcore.tools.sandbox.browser.gvisor_session import browser_sessions_supported

        return browser_sessions_supported()

    async def open_browser_session(self, request):  # type: ignore[no-untyped-def]
        """Launch a long-lived browser sandbox (see ``browser.gvisor_session``)."""
        from agentcore.tools.sandbox.browser.gvisor_session import open_gvisor_browser_session

        return await open_gvisor_browser_session(
            request, runsc_path=self._runsc, runtime_root=self._runtime_root
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute code inside a gVisor sandbox (slot-limited, staged workspace)."""
        if not _IS_LINUX:
            raise SandboxError("GVisor sandbox is only available on Linux")

        if request.language not in _LANGUAGE_COMMANDS:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"Unsupported language: {request.language}",
                exit_code=1,
                duration_ms=0,
            )

        start = time.monotonic()
        # 灰度护栏: bounded wait for a global execution slot, then fail fast with an
        # explainable busy result (never queue past the engine's tool deadline).
        release = await try_acquire_execution_slot()
        if release is None:
            return self._slot_busy_result(start)
        try:
            return await self._execute_in_slot(request, start)
        finally:
            release()

    def _slot_busy_result(self, start: float) -> ExecutionResult:
        capacity = max(1, int(settings.gvisor_max_concurrent_executions))
        waited = float(settings.gvisor_slot_wait_seconds)
        logger.info("sandbox.slot_busy", capacity=capacity, waited_seconds=waited)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr=(
                f"云端执行位已满（并发上限 {capacity}），等待 {waited:g} 秒仍未获得执行位。"
                "请稍后重试；持续繁忙时可拆小任务或错峰执行。"
            ),
            exit_code=-1,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def _effective_timeout(self, request: ExecutionRequest) -> int:
        return min(int(request.timeout_seconds), int(settings.gvisor_timeout_max_seconds))

    async def _execute_in_slot(
        self, request: ExecutionRequest, start: float
    ) -> ExecutionResult:
        container_id = f"agentcore-{uuid.uuid4().hex[:12]}"
        bundle_dir = tempfile.mkdtemp(prefix="agentcore_gvisor_", dir=self._runtime_root)
        process: asyncio.subprocess.Process | None = None
        timeout_seconds = self._effective_timeout(request)

        try:
            scratch_dir = Path(bundle_dir) / "scratch"
            scratch_dir.mkdir()
            rootfs = Path(bundle_dir) / "rootfs"
            rootfs.mkdir()

            ext = _FILE_EXTENSIONS[request.language]
            script_name = f"main{ext}"
            (scratch_dir / script_name).write_text(request.code, encoding="utf-8")
            if request.stdin:
                (scratch_dir / "stdin.txt").write_text(request.stdin, encoding="utf-8")
            prepare_bind_tree_for_sandbox(scratch_dir)

            # 产物写回 copy-in leg: stage a rw copy of the workspace for the sandbox.
            # No workspace (bare/health-check runs) → old behaviour: scratch doubles
            # as a read-only /workspace and there is nothing to write back to.
            workspace_root = request.cwd or self._workspace_root
            staging_dir: Path | None = None
            staged_state: TreeState | None = None
            if workspace_root:
                staging_dir = Path(bundle_dir) / "workspace"
                staged_state = await asyncio.to_thread(
                    stage_workspace,
                    Path(workspace_root),
                    staging_dir,
                    max_bytes=settings.gvisor_stage_max_bytes,
                )
            workspace = str(staging_dir.resolve()) if staging_dir else str(scratch_dir)
            config = self._build_oci_config(
                request,
                script_name=script_name,
                workspace=workspace,
                scratch_dir=str(scratch_dir.resolve()),
                workspace_writable=staging_dir is not None,
                memory_limit_mb=settings.gvisor_memory_limit_mb,
            )
            (Path(bundle_dir) / "config.json").write_text(
                json.dumps(config),
                encoding="utf-8",
            )

            cmd = self._build_run_cmd(
                bundle_dir=bundle_dir,
                container_id=container_id,
                network_mode=request.network_mode,
            )

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE if request.stdin else None,
                )
            except OSError as e:
                raise SandboxError(f"代码执行环境启动失败：{e}") from e

            stdin_bytes = request.stdin.encode() if request.stdin else None

            try:

                async def _collect_output() -> tuple[str, str]:
                    if stdin_bytes is not None and process.stdin is not None:
                        process.stdin.write(stdin_bytes)
                        await process.stdin.drain()
                        process.stdin.close()

                    stdout_buf: list[str] = []
                    stderr_buf: list[str] = []
                    await asyncio.gather(
                        _read_stream(
                            process.stdout,
                            "stdout",
                            stdout_buf,
                            request.on_output,
                        ),
                        _read_stream(
                            process.stderr,
                            "stderr",
                            stderr_buf,
                            request.on_output,
                        ),
                    )
                    await process.wait()
                    return "".join(stdout_buf), "".join(stderr_buf)

                stdout_str, stderr_str = await asyncio.wait_for(
                    _collect_output(),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                raise SandboxTimeoutError(
                    f"Execution exceeded {timeout_seconds}s timeout"
                ) from None
            finally:
                await asyncio.shield(self._stop_container(container_id, process))

            if staging_dir is not None:
                clean_stdout, artifact_payload = _strip_artifact_payload(stdout_str)
                if artifact_payload:
                    _materialize_artifacts(staging_dir, artifact_payload)
                stdout_str = clean_stdout

            # Copy-out leg: only a run that COMPLETED (any exit code) persists its
            # artifacts — a partial success (chart saved, later step failed) still
            # delivers files; a timeout-killed run never lands half-written ones.
            written, skipped = await self._write_back_if_staged(
                staging_dir, staged_state, workspace_root
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                success=process.returncode == 0,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode or 0,
                duration_ms=duration_ms,
                written_files=written,
                write_back_skipped=skipped,
            )

        except SandboxTimeoutError:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=(
                    f"Timeout: execution exceeded {timeout_seconds}s"
                    "；执行被中断，中断前的文件改动未写回工作区。"
                ),
                exit_code=-1,
                duration_ms=duration_ms,
            )
        finally:
            shutil.rmtree(bundle_dir, ignore_errors=True)

    async def _write_back_if_staged(
        self,
        staging_dir: Path | None,
        staged_state: TreeState | None,
        workspace_root: str | None,
    ) -> tuple[list[str], int]:
        """Copy new/changed staged files back into the real workspace (capped)."""
        if staging_dir is None or staged_state is None or not workspace_root:
            return [], 0

        def _run() -> tuple[list[str], int]:
            changes = collect_changes(staging_dir, staged_state)
            if not changes:
                return [], 0
            report = write_back(
                staging_dir,
                Path(workspace_root),
                changes,
                max_bytes=settings.gvisor_write_back_max_bytes,
                max_files=settings.gvisor_write_back_max_files,
            )
            return report.written, len(report.skipped)

        written, skipped = await asyncio.to_thread(_run)
        if written or skipped:
            logger.info(
                "sandbox.write_back",
                written=len(written),
                skipped=skipped,
                files=written[:20],
            )
        return written, skipped

    def _build_run_cmd(
        self,
        *,
        bundle_dir: str,
        container_id: str,
        network_mode: str,
    ) -> list[str]:
        """Assemble ``runsc`` argv: global flags before ``run``, bundle after."""
        cmd = [self._runsc, "--rootless"]
        # P2: full_trust → restricted egress; observe/workspace stay offline.
        if network_mode != "restricted":
            cmd.append("--network=none")
        cmd.extend(
            [
                f"--root={self._runtime_root}",
                "run",
                f"--bundle={bundle_dir}",
                container_id,
            ]
        )
        return cmd

    def _build_health_oci_config(self) -> dict:
        """Minimal OCI bundle for boot-time ``/bin/true`` smoke."""
        return {
            "ociVersion": "1.0.2",
            "process": {
                "terminal": False,
                "user": {"uid": 65534, "gid": 65534},
                "args": ["/bin/true"],
                "env": ["PATH=/usr/bin:/bin"],
                "cwd": "/tmp",
            },
            "root": {"path": "rootfs", "readonly": True},
            "mounts": [
                {
                    "destination": "/tmp",
                    "type": "tmpfs",
                    "source": "tmpfs",
                    "options": ["nosuid", "nodev", "size=8m"],
                },
                *self._host_bind_mounts(),
            ],
            "linux": {
                "resources": {
                    "memory": {"limit": 64 * 1024 * 1024},
                    "pids": {"limit": 32},
                },
                "namespaces": [
                    {"type": "pid"},
                    {"type": "ipc"},
                    {"type": "uts"},
                    {"type": "mount"},
                ],
            },
        }

    def _build_command(self, request: ExecutionRequest, script_path: str) -> list[str]:
        if request.stdin and request.language == "bash":
            return ["bash", "-c", f"{script_path} < /scratch/stdin.txt"]
        return _LANGUAGE_COMMANDS[request.language] + [script_path]

    def _build_env(self, request: ExecutionRequest) -> list[str]:
        env: dict[str, str] = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            # Headless plotting: the sandbox has no display; without an explicit
            # backend matplotlib may probe for GUI toolkits and fail confusingly.
            "MPLBACKEND": "Agg",
            # Keep sandbox-created artifacts world-readable so the non-root API
            # user can copy them back after runsc exits (umask 022 → 644 files).
            "UMASK": "0022",
        }
        if request.env:
            env.update(request.env)
        return [f"{key}={value}" for key, value in env.items()]

    def _host_bind_mounts(self) -> list[dict]:
        mounts: list[dict] = []
        for path in _HOST_BIND_PATHS:
            if os.path.isdir(path):
                mounts.append(
                    {
                        "destination": path,
                        "type": "bind",
                        "source": path,
                        "options": ["ro", "rbind", "nosuid"],
                    }
                )
        return mounts

    def _wrap_staged_workspace_command(self, inner_cmd: list[str]) -> list[str]:
        """Seed tmpfs /workspace, run, then emit artifacts on stdout for host copy-out."""
        inner = " ".join(shlex.quote(part) for part in inner_cmd)
        script = (
            "cp -a /workspace-seed/. /workspace/ 2>/dev/null || true; "
            f"{inner}; "
            "ec=$?; "
            "python3 - <<'PY'\n"
            "import base64, json, sys\n"
            "from pathlib import Path\n"
            "root = Path('/workspace')\n"
            "payload = {\n"
            "    p.relative_to(root).as_posix(): "
            "base64.b64encode(p.read_bytes()).decode('ascii')\n"
            "    for p in root.rglob('*') if p.is_file()\n"
            "}\n"
            "marker = "
            f"{_ARTIFACT_MARKER!r}\n"
            "sys.stdout.write(marker + json.dumps(payload, separators=(',', ':')))\n"
            "sys.stdout.write('\\n')\n"
            "PY\n"
            "exit $ec"
        )
        return ["bash", "-c", script]

    def _build_oci_config(
        self,
        request: ExecutionRequest,
        *,
        script_name: str,
        workspace: str,
        scratch_dir: str,
        workspace_writable: bool = False,
        memory_limit_mb: int | None = None,
    ) -> dict:
        script_path = f"/scratch/{script_name}"
        namespaces = [
            {"type": "pid"},
            {"type": "ipc"},
            {"type": "uts"},
            {"type": "mount"},
        ]
        # P2: restricted mode adds a network namespace so the process can reach
        # the public internet (runsc without ``--network=none``). observe /
        # workspace keep the offline posture (no network ns + ``--network=none``).
        # Application-level SSRF for product HTTP tools remains ``core/net.py``;
        # in-sandbox raw sockets are OS-egress only (no private-IP filter inside
        # runsc — multi-tenant hardening is still gVisor's isolation boundary).
        if request.network_mode == "restricted":
            namespaces.append({"type": "network"})

        mounts = [
            {
                "destination": "/tmp",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "nodev", "size=64m"],
            },
        ]
        process_args = self._build_command(request, script_path)
        if workspace_writable:
            # runsc cannot mkdir on bind mounts (EINVAL) from inside Docker; use
            # tmpfs for live writes and copy-in/out via twin binds on staging.
            stage_mb = max(64, settings.gvisor_stage_max_bytes // (1024 * 1024))
            mounts.extend(
                [
                    {
                        "destination": "/workspace-seed",
                        "type": "bind",
                        "source": workspace,
                        "options": ["ro", "bind", "nosuid", "nodev"],
                    },
                    {
                        "destination": "/workspace",
                        "type": "tmpfs",
                        "source": "tmpfs",
                        "options": [
                            "rw",
                            "nosuid",
                            "nodev",
                            "mode=1777",
                            f"size={stage_mb}m",
                        ],
                    },
                ]
            )
            process_args = self._wrap_staged_workspace_command(process_args)
        else:
            mounts.append(
                {
                    "destination": "/workspace",
                    "type": "bind",
                    "source": workspace,
                    "options": ["ro", "rbind"],
                }
            )
        mounts.append(
            {
                "destination": "/scratch",
                "type": "bind",
                "source": scratch_dir,
                "options": ["ro", "bind", "nosuid", "nodev"],
            }
        )
        mounts.extend(self._host_bind_mounts())

        return {
            "ociVersion": "1.0.2",
            "process": {
                "terminal": False,
                "user": {"uid": 65534, "gid": 65534},
                "args": process_args,
                "env": self._build_env(request),
                "cwd": "/workspace",
            },
            "root": {"path": "rootfs", "readonly": True},
            "mounts": mounts,
            "linux": {
                "resources": {
                    # Cloud runs take the configured guardrail ceiling; the request's
                    # own field only applies when no explicit limit is passed (bare
                    # sandbox use in tests).
                    "memory": {
                        "limit": (memory_limit_mb or request.memory_limit_mb) * 1024 * 1024
                    },
                    "cpu": {
                        "quota": int(request.cpu_limit * 100000),
                        "period": 100000,
                    },
                    "pids": {"limit": request.pids_limit},
                },
                "namespaces": namespaces,
            },
        }

    async def _runsc_cmd(self, *args: str) -> None:
        with contextlib.suppress(Exception):
            proc = await asyncio.create_subprocess_exec(
                self._runsc,
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

    async def _stop_container(
        self,
        container_id: str,
        process: asyncio.subprocess.Process | None,
    ) -> None:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
        await self._runsc_cmd("kill", container_id, "SIGKILL")
        await self._runsc_cmd("delete", container_id)

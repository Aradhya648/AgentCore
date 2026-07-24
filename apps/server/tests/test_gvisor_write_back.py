"""GVisorSandbox 产物写回端到端（mock runsc，Windows / 无 runsc 主机可跑）。

真 runsc 是 Linux-only；这里用假 runsc 二进制模拟「容器内写文件」：
解析 ``--bundle=`` → 往 staging workspace 落产物 → 退出 0，让 copy-out 腿跑通。
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

import agentcore.tools.sandbox.gvisor as gvisor_mod
from agentcore.config import settings
from agentcore.tools.sandbox.gvisor import GVisorSandbox
from agentcore.tools.sandbox.limits import reset_execution_slots
from agentcore.tools.sandbox.protocol import ExecutionRequest


@pytest.fixture(autouse=True)
def _fresh_slots_and_linux(monkeypatch):
    reset_execution_slots()
    monkeypatch.setattr(gvisor_mod, "_IS_LINUX", True)
    monkeypatch.setattr(settings, "gvisor_max_concurrent_executions", 2)
    monkeypatch.setattr(settings, "gvisor_slot_wait_seconds", 1.0)
    monkeypatch.setattr(settings, "gvisor_timeout_max_seconds", 30)
    monkeypatch.setattr(settings, "gvisor_memory_limit_mb", 256)
    monkeypatch.setattr(settings, "gvisor_stage_max_bytes", 16 * 1024 * 1024)
    monkeypatch.setattr(settings, "gvisor_write_back_max_bytes", 8 * 1024 * 1024)
    monkeypatch.setattr(settings, "gvisor_write_back_max_files", 50)
    yield
    reset_execution_slots()


def _install_fake_runsc(tmp_path: Path, *, artifact_rel: str = "out/hello.txt") -> str:
    """Install a cross-platform fake ``runsc`` that writes ``artifact_rel`` into /workspace."""
    impl = tmp_path / "fake_runsc_impl.py"
    impl.write_text(
        textwrap.dedent(
            f"""\
            import json
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            if "--version" in args or (args[:1] == ["--version"]):
                print("runsc version fake")
                raise SystemExit(0)
            if args[:1] in (["kill"], ["delete"]):
                raise SystemExit(0)

            bundle = None
            for a in args:
                if a.startswith("--bundle="):
                    bundle = a.split("=", 1)[1]
            if not bundle:
                print("fake_runsc: missing --bundle=", file=sys.stderr)
                raise SystemExit(2)

            cfg = json.loads((Path(bundle) / "config.json").read_text(encoding="utf-8"))
            args_in = cfg.get("process", {{}}).get("args") or []
            if args_in == ["/bin/true"]:
                raise SystemExit(0)

            ws = None
            for m in cfg.get("mounts", []):
                if m.get("destination") in ("/workspace-seed", "/workspace-sync"):
                    ws = Path(m["source"])
                    break
            if ws is None:
                for m in cfg.get("mounts", []):
                    if m.get("destination") == "/workspace":
                        if m.get("type") == "bind" and "rw" in (m.get("options") or []):
                            ws = Path(m["source"])
                            break
            if ws is None:
                print("fake_runsc: no workspace staging mount", file=sys.stderr)
                raise SystemExit(2)

            rel = Path({artifact_rel!r})
            dest = ws / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("from-sandbox", encoding="utf-8")
            print("wrote", rel.as_posix())
            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    if sys.platform == "win32":
        wrapper = tmp_path / "fake_runsc.cmd"
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{impl}" %*\r\n',
            encoding="utf-8",
        )
        return str(wrapper)
    wrapper = tmp_path / "fake_runsc"
    wrapper.write_text(
        f"#!/usr/bin/env python3\nimport runpy\nrunpy.run_path({str(impl)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


async def test_gvisor_write_back_lands_artifact_in_real_workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "seed.txt").write_text("keep", encoding="utf-8")

    runsc = _install_fake_runsc(tmp_path)
    sandbox = GVisorSandbox(
        runsc_path=runsc,
        runtime_root=str(tmp_path / "rt"),
    )

    result = await sandbox.execute(
        ExecutionRequest(
            code="print('ignored-by-fake')",
            language="python",
            cwd=str(ws),
            timeout_seconds=10,
        )
    )

    assert result.success is True
    assert result.written_files == ["out/hello.txt"]
    assert result.write_back_skipped == 0
    assert (ws / "out" / "hello.txt").read_text(encoding="utf-8") == "from-sandbox"
    assert (ws / "seed.txt").read_text(encoding="utf-8") == "keep"


async def test_gvisor_timeout_skips_write_back(tmp_path: Path, monkeypatch):
    """Timeout path must not persist half-written artifacts (copy-out skipped)."""
    import time

    ws = tmp_path / "workspace"
    ws.mkdir()

    runsc = _install_fake_runsc(tmp_path)
    sandbox = GVisorSandbox(runsc_path=runsc, runtime_root=str(tmp_path / "rt"))

    # Force the wait_for deadline without relying on OS process kill timing
    # (Windows .cmd wrappers often leave a child Python alive after kill).
    # Call _execute_in_slot directly so we don't also patch the slot limiter's
    # asyncio.wait_for (same module object).
    async def _immediate_timeout(aw, timeout=None):  # noqa: ANN001
        if hasattr(aw, "close"):
            aw.close()
        raise TimeoutError

    monkeypatch.setattr(gvisor_mod.asyncio, "wait_for", _immediate_timeout)

    start = time.monotonic()
    result = await sandbox._execute_in_slot(  # noqa: SLF001
        ExecutionRequest(code="x", language="python", cwd=str(ws), timeout_seconds=1),
        start,
    )

    assert result.success is False
    assert "Timeout" in result.stderr
    assert "未写回" in result.stderr
    assert not (ws / "out").exists()
    assert result.written_files is None


def test_oci_workspace_mount_is_rw_when_staged(tmp_path: Path):
    sandbox = GVisorSandbox(runtime_root=str(tmp_path / "rt"))
    cfg = sandbox._build_oci_config(  # noqa: SLF001
        ExecutionRequest(code="x", language="python"),
        script_name="main.py",
        workspace=str(tmp_path / "staged"),
        scratch_dir=str(tmp_path / "scratch"),
        workspace_writable=True,
        memory_limit_mb=256,
    )
    mounts = {m["destination"]: m for m in cfg["mounts"]}
    assert mounts["/workspace"]["type"] == "tmpfs"
    assert mounts["/workspace-seed"]["type"] == "bind"
    assert mounts["/scratch"]["options"] == ["ro", "bind", "nosuid", "nodev"]
    # Memory ceiling comes from the guardrail knob, not the request default.
    assert cfg["linux"]["resources"]["memory"]["limit"] == 256 * 1024 * 1024


def test_oci_config_json_roundtrip_shape(tmp_path: Path):
    """config.json must be JSON-serializable for runsc (regression for Path/set leaks)."""
    sandbox = GVisorSandbox(runtime_root=str(tmp_path / "rt"))
    cfg = sandbox._build_oci_config(  # noqa: SLF001
        ExecutionRequest(code="print(1)", language="python", network_mode="none"),
        script_name="main.py",
        workspace=str(tmp_path),
        scratch_dir=str(tmp_path / "scratch"),
        workspace_writable=False,
    )
    dumped = json.dumps(cfg)
    assert '"cwd": "/workspace"' in dumped
    assert '"network"' not in dumped  # offline posture


def test_runsc_run_cmd_global_flags_before_run(tmp_path: Path):
    sandbox = GVisorSandbox(runtime_root=str(tmp_path / "rt"))
    cmd = sandbox._build_run_cmd(  # noqa: SLF001
        bundle_dir="/tmp/bundle",
        container_id="agentcore-test",
        network_mode="none",
    )
    assert cmd[0] == sandbox._runsc  # noqa: SLF001
    run_idx = cmd.index("run")
    assert "--rootless" in cmd[:run_idx]
    assert "--network=none" in cmd[:run_idx]
    assert f"--root={tmp_path / 'rt'}" in cmd[:run_idx]
    assert cmd[run_idx + 1] == "--bundle=/tmp/bundle"
    assert cmd[run_idx + 2] == "agentcore-test"


def test_runsc_run_cmd_restricted_omits_network_none(tmp_path: Path):
    sandbox = GVisorSandbox(runtime_root=str(tmp_path / "rt"))
    cmd = sandbox._build_run_cmd(  # noqa: SLF001
        bundle_dir="/tmp/bundle",
        container_id="agentcore-test",
        network_mode="restricted",
    )
    run_idx = cmd.index("run")
    assert "--network=none" not in cmd[:run_idx]


async def test_health_check_smoke_run(tmp_path: Path):
    runsc = _install_fake_runsc(tmp_path)
    sandbox = GVisorSandbox(runsc_path=runsc, runtime_root=str(tmp_path / "rt"))
    assert await sandbox.health_check() is True

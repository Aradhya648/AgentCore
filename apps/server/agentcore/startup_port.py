"""Fail-fast listen-port probe before uvicorn binds.

Windows can silently share a TCP listen port across processes (SO_REUSEADDR),
so a second ``python -m agentcore`` may appear to start while an orphan worker
still serves stale code. Probe with a short TCP connect before ``uvicorn.run``.
"""

from __future__ import annotations

import socket
import sys


def probe_host_for_connect(host: str) -> str:
    """Map bind-any hosts to a loopback target suitable for connect probes."""
    normalized = (host or "").strip().lower()
    if normalized in {"", "0.0.0.0", "*"}:
        return "127.0.0.1"
    if normalized in {"::", "[::]"}:
        return "::1"
    return host


def port_is_busy(host: str, port: int, *, timeout_s: float = 0.35) -> bool:
    """Return True when something already accepts TCP connections on host:port."""
    target = probe_host_for_connect(host)
    family = socket.AF_INET6 if ":" in target else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            return sock.connect_ex((target, port)) == 0
    except OSError:
        # Probe failures (e.g. no IPv6 stack) must not block startup.
        return False


def format_port_busy_message(host: str, port: int) -> str:
    target = probe_host_for_connect(host)
    return (
        f"ERROR: port {port} is already in use "
        f"(probed {target}; bind host was {host!r}).\n"
        "Another AgentCore server instance is likely still running — often an "
        "orphan uvicorn reload worker left behind after killing only the parent "
        "process.\n"
        "Cleanup (Windows):\n"
        "  • Preferred: powershell -File apps/server/scripts/start-dev-server.ps1\n"
        "  • Manual: taskkill /F /T /PID <pid>  "
        "(kill the whole tree; /T is required — killing only a child leaves a "
        "ghost worker holding the port)\n"
        "Refusing to start a second instance."
    )


def ensure_port_available(host: str, port: int) -> None:
    """Exit with code 1 when the listen port is already occupied."""
    if not port_is_busy(host, port):
        return
    print(format_port_busy_message(host, port), file=sys.stderr, flush=True)
    raise SystemExit(1)

"""Unit tests for launch-time listen-port fail-fast."""

from __future__ import annotations

import socket
import threading

import pytest

from agentcore import startup_port


def test_probe_host_for_connect_maps_bind_any():
    assert startup_port.probe_host_for_connect("0.0.0.0") == "127.0.0.1"
    assert startup_port.probe_host_for_connect("::") == "::1"
    assert startup_port.probe_host_for_connect("127.0.0.1") == "127.0.0.1"


def test_port_is_busy_detects_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        # Backlog >1: each connect probe consumes a slot until accept().
        listener.listen(8)
        port = listener.getsockname()[1]
        assert startup_port.port_is_busy("127.0.0.1", port) is True
        assert startup_port.port_is_busy("0.0.0.0", port) is True


def test_port_is_busy_false_when_free():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Socket closed — port should be free again.
    assert startup_port.port_is_busy("127.0.0.1", port) is False


def test_ensure_port_available_exits_when_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            startup_port.ensure_port_available("127.0.0.1", port)
        assert exc.value.code == 1


def test_format_port_busy_message_mentions_cleanup_hints():
    msg = startup_port.format_port_busy_message("0.0.0.0", 8000)
    assert "8000" in msg
    assert "start-dev-server.ps1" in msg
    assert "powershell" in msg
    assert "taskkill" in msg
    assert "/T" in msg


def test_port_is_busy_with_accepting_server_thread():
    """Connect probe succeeds against a real accept loop (not just listen)."""
    ready = threading.Event()
    stop = threading.Event()
    holder: list[socket.socket] = []

    def _serve() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        holder.append(sock)
        ready.set()
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
                conn.close()
            except (TimeoutError, OSError):
                continue

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    assert ready.wait(2.0)
    port = holder[0].getsockname()[1]
    try:
        assert startup_port.port_is_busy("127.0.0.1", port) is True
    finally:
        stop.set()
        holder[0].close()
        thread.join(timeout=2.0)

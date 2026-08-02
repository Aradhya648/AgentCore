"""Host-side allowlist CONNECT/HTTP proxy — packaging egress chokepoint.

Only dials hostnames in the packaging allowlist. Deliberately separate from
``browser.proxy`` (SSRF deny-private): a deny-private proxy is **not** an
allowlist and must not be reused as one.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.tools.sandbox.egress.hosts import host_is_allowed_registry

logger = get_logger(__name__)

_CONNECTION_ESTABLISHED = b"HTTP/1.1 200 Connection Established\r\n\r\n"


def _refusal(status: str) -> bytes:
    return f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()


async def resolve_allowlist_dial_target(
    host: str, port: int
) -> tuple[str | None, str]:
    """Allowlist-vet ``host`` and return ``(dial_ip_or_host, reason)``.

    Non-allowlisted hosts are refused before DNS. Allowed hostnames are resolved
    and dialed by address; literals must themselves be on the allowlist (normally
    they are not — registries are hostnames).
    """
    if not host_is_allowed_registry(host):
        return None, "NOT_ALLOWLISTED"
    try:
        # Rare: allowlist somehow contains an IP literal.
        socket.inet_pton(socket.AF_INET, host)
        return host, "ok_literal"
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return host, "ok_literal"
    except OSError:
        pass
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, proto=socket.IPPROTO_TCP
        )
    except OSError:
        return None, "DNS_FAIL"
    for info in infos:
        ip = info[4][0]
        if isinstance(ip, str) and ip:
            return ip, "ok"
    return None, "DNS_FAIL"


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(OSError):
            writer.write_eof()


class AllowlistEgressProxy:
    """Process-wide async CONNECT/HTTP proxy enforcing packaging host allowlist."""

    def __init__(
        self,
        *,
        on_decision: Callable[[str, str, bool, str], None] | None = None,
    ) -> None:
        self._on_decision = on_decision
        self._server: asyncio.AbstractServer | None = None
        self._host = ""
        self._port = 0

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> int:
        return self._port

    async def start(self, host: str, port: int) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle, host, port)
        self._host, self._port = host, port
        logger.info("package.egress_proxy_started", host=host, port=port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        with contextlib.suppress(Exception):
            await self._server.wait_closed()
        self._server = None
        logger.info("package.egress_proxy_stopped")

    def _decide(self, method: str, host: str, allowed: bool, reason: str) -> None:
        logger.info(
            "package.egress_proxy_decision",
            method=method,
            host=host,
            allowed=allowed,
            reason=reason,
        )
        if self._on_decision is not None:
            self._on_decision(method, host, allowed, reason)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=30)
            if not request_line:
                return
            parts = request_line.decode("latin-1").strip().split(" ")
            if len(parts) < 3:
                return
            method, target = parts[0].upper(), parts[1]
            if method == "CONNECT":
                await self._connect(reader, writer, target)
            else:
                await self._forward(reader, writer, method, target, parts[2])
        except (TimeoutError, OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                writer.close()

    @staticmethod
    async def _drain_headers(reader: asyncio.StreamReader) -> list[bytes]:
        headers: list[bytes] = []
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            headers.append(line)
        return headers

    async def _connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target: str
    ) -> None:
        host, _, port_s = target.rpartition(":")
        port = int(port_s or "443")
        await self._drain_headers(reader)
        ip, reason = await resolve_allowlist_dial_target(host, port)
        if ip is None:
            self._decide("CONNECT", host, False, reason)
            writer.write(_refusal("403 Forbidden"))
            await writer.drain()
            return
        self._decide("CONNECT", host, True, reason)
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=15
            )
        except (OSError, TimeoutError):
            writer.write(_refusal("502 Bad Gateway"))
            await writer.drain()
            return
        writer.write(_CONNECTION_ESTABLISHED)
        await writer.drain()
        await asyncio.gather(
            _pump(reader, up_writer), _pump(up_reader, writer), return_exceptions=True
        )
        with contextlib.suppress(OSError):
            up_writer.close()

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        method: str,
        url: str,
        version: str,
    ) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or 80
        ip, reason = await resolve_allowlist_dial_target(host, port)
        headers = await self._drain_headers(reader)
        if ip is None:
            self._decide(method, host, False, reason)
            writer.write(_refusal("403 Forbidden"))
            await writer.drain()
            return
        self._decide(method, host, True, reason)
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=15
            )
        except (OSError, TimeoutError):
            writer.write(_refusal("502 Bad Gateway"))
            await writer.drain()
            return
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        req = f"{method} {path} {version}\r\n".encode("latin-1") + b"".join(headers) + b"\r\n"
        up_writer.write(req)
        await up_writer.drain()
        await asyncio.gather(
            _pump(reader, up_writer), _pump(up_reader, writer), return_exceptions=True
        )
        with contextlib.suppress(OSError):
            up_writer.close()


_proxy: AllowlistEgressProxy | None = None


async def ensure_package_egress_proxy() -> AllowlistEgressProxy:
    """Start (once) the process-wide packaging allowlist proxy."""
    global _proxy
    if _proxy is None:
        _proxy = AllowlistEgressProxy()
    if not _proxy.running:
        await _proxy.start("0.0.0.0", int(settings.package_egress_proxy_port))
    return _proxy


async def shutdown_package_egress_proxy() -> None:
    global _proxy
    if _proxy is not None:
        await _proxy.stop()
        _proxy = None

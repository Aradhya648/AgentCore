"""Per-session network isolation (Linux-only) — validated by the M0 channel PoC.

Each browser sandbox gets its OWN network namespace with a veth pair to the host.
The host end runs (is reachable by) the SSRF proxy; the sandbox end has a default
route via the host end but the host does NOT NAT/forward, so the sandbox's ONLY
reachable off-link destination is the proxy (D10 network-layer egress control —
proven in the PoC: a raw socket to the public internet times out, only the proxy
is reachable). runsc ``--network=sandbox`` then clones this netns's veth + routes
into netstack (the OCI must reference the netns by PATH — see PoC finding #1).

All calls shell out to ``ip`` and only run on Linux under a real gVisor deploy;
they never execute in tests / on the dev host (the registry uses fakes there).

Boot / sticky health (``browser_netns_health``) gates cloud ``browser_*`` assembly —
``GVisorSandbox.health_check`` uses ``network_mode=none`` and does not cover netns.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

NETNS_RUN_DIR = "/var/run/netns"

# Dedicated name for the boot probe (must not collide with slot-derived ``acbrw{N}``).
_PROBE_NETNS_NAME = "acbrwprobe"

# None = never probed → ``browser_execution_enabled_for`` keeps cloud-health-only semantics.
_browser_netns_healthy: bool | None = None


class NetnsError(RuntimeError):
    """A per-session netns / veth setup or teardown step failed."""


# Stable tool ``metadata.code`` when sandbox network isolation cannot be created.
# Permanent for the run: retrying browser_* will hit the same host capability gap.
EGRESS_UNAVAILABLE_CODE = "egress_unavailable"


def browser_netns_health() -> bool | None:
    """Cached netns capability: ``True`` / ``False``, or ``None`` if never probed."""
    return _browser_netns_healthy


def reset_browser_netns_health_for_tests() -> None:
    """Clear the process-wide cache so tests cannot leak health across cases."""
    global _browser_netns_healthy
    _browser_netns_healthy = None


def set_browser_netns_health_for_tests(healthy: bool | None) -> None:
    """Inject netns health for unit tests. ``None`` = unprobed."""
    global _browser_netns_healthy
    _browser_netns_healthy = healthy


def mark_browser_netns_unavailable() -> None:
    """Sticky: host netns proven unavailable → withhold cloud browser_* until restart."""
    global _browser_netns_healthy
    _browser_netns_healthy = False


def is_netns_capability_error(exc: BaseException) -> bool:
    """True when ``exc`` (or its cause chain) is a host netns / veth capability failure.

    Covers :class:`NetnsError` and the common wrapped form
    ``mkdir /run/netns … Permission denied`` that appears after generic Exception
    → BrowserSessionError wrapping.
    """
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, NetnsError):
            return True
        text = str(cur)
        if "NetnsError" in text or "mkdir /run/netns" in text:
            return True
        if "ip netns" in text and "Permission denied" in text:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


async def _ip(*args: str, check: bool = True) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "ip", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise NetnsError(f"ip {' '.join(args)} failed ({proc.returncode}): {text.strip()}")
    return proc.returncode or 0, text


async def probe_browser_netns_at_startup() -> None:
    """One-shot boot probe when gVisor browser path is config-enabled. Never raises.

    Minimal check: ``ip netns add`` + ``del`` a dedicated probe name. Only runs on
    Linux with ``settings.gvisor_enabled``. Non-Linux / config-off leave the cache
    at ``None`` (tests / unbooted keep status-quo assembly semantics).
    """
    global _browser_netns_healthy
    from agentcore.config import settings

    if sys.platform != "linux" or not settings.gvisor_enabled:
        return

    reason = "unhealthy"
    detail = ""
    try:
        # Best-effort clear of a stale probe remnant, then add + del.
        await _ip("netns", "del", _PROBE_NETNS_NAME, check=False)
        await _ip("netns", "add", _PROBE_NETNS_NAME)
        await _ip("netns", "del", _PROBE_NETNS_NAME, check=False)
        ok = True
    except Exception as exc:  # noqa: BLE001 — probe must never break startup
        ok = False
        reason = type(exc).__name__
        detail = str(exc)[:200]
        with contextlib.suppress(Exception):
            await _ip("netns", "del", _PROBE_NETNS_NAME, check=False)

    _browser_netns_healthy = ok
    if ok:
        logger.debug("browser.netns_health_ok")
        return

    logger.warning(
        "browser.netns_health_failed",
        reason=reason,
        detail=detail or None,
        hint="云端 browser_* 将不装配，直到主机 netns 能力可用（不回退 Local）",
    )


class SessionNetns:
    """Names / addresses for one session's isolated stack (slot-derived, no clashes)."""

    def __init__(self, *, slot: int, subnet_base: str) -> None:
        self.slot = slot
        self.name = f"acbrw{slot}"
        self.veth_host = f"acbrwh{slot}"
        self.veth_sbx = f"acbrws{slot}"
        self.host_ip = f"{subnet_base}.{slot}.1"
        self.sbx_ip = f"{subnet_base}.{slot}.2"
        self.cidr = "24"

    @property
    def netns_path(self) -> str:
        return f"{NETNS_RUN_DIR}/{self.name}"

    async def setup(self) -> None:
        """Create the netns + veth, address both ends, default-route the sandbox."""
        await self.teardown()  # clear any stale remnant from a crashed prior run
        await _ip("netns", "add", self.name)
        await _ip("link", "add", self.veth_host, "type", "veth", "peer", "name", self.veth_sbx)
        await _ip("link", "set", self.veth_sbx, "netns", self.name)
        await _ip("addr", "add", f"{self.host_ip}/{self.cidr}", "dev", self.veth_host)
        await _ip("link", "set", self.veth_host, "up")
        await _ip(
            "-n", self.name, "addr", "add", f"{self.sbx_ip}/{self.cidr}", "dev", self.veth_sbx
        )
        await _ip("-n", self.name, "link", "set", self.veth_sbx, "up")
        await _ip("-n", self.name, "link", "set", "lo", "up")
        # Default route via the host veth end. No NAT/forward on the host ⇒ the ONLY
        # reachable off-link address is the proxy on host_ip (egress chokepoint).
        await _ip("-n", self.name, "route", "add", "default", "via", self.host_ip)
        logger.info("browser.netns_setup", netns=self.name, host_ip=self.host_ip)

    async def teardown(self) -> None:
        """Best-effort removal (deleting the netns drops its veth end; then the host end)."""
        await _ip("netns", "del", self.name, check=False)
        await _ip("link", "del", self.veth_host, check=False)

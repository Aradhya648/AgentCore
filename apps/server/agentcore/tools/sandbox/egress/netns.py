"""Per-install-run network isolation — packaging egress (not browser sessions).

Same netns+veth shape as browser, distinct names/subnet so slots never collide.
runsc ``--network=sandbox`` clones this netns; the only off-link route is the
allowlist proxy on the host veth end.
"""

from __future__ import annotations

import asyncio

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

NETNS_RUN_DIR = "/var/run/netns"


class PackageNetnsError(RuntimeError):
    """A packaging netns / veth setup or teardown step failed."""


async def _ip(*args: str, check: bool = True) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "ip", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise PackageNetnsError(
            f"ip {' '.join(args)} failed ({proc.returncode}): {text.strip()}"
        )
    return proc.returncode or 0, text


class PackageNetns:
    """Names / addresses for one install-run isolated stack (slot-derived)."""

    def __init__(self, *, slot: int, subnet_base: str) -> None:
        self.slot = slot
        # Prefix distinct from browser ``acbrw*``; iface names stay ≤15 chars.
        self.name = f"acpkg{slot}"
        self.veth_host = f"acpkgh{slot}"
        self.veth_sbx = f"acpkgs{slot}"
        self.host_ip = f"{subnet_base}.{slot}.1"
        self.sbx_ip = f"{subnet_base}.{slot}.2"
        self.cidr = "24"

    @property
    def netns_path(self) -> str:
        return f"{NETNS_RUN_DIR}/{self.name}"

    async def setup(self) -> None:
        await self.teardown()
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
        await _ip("-n", self.name, "route", "add", "default", "via", self.host_ip)
        logger.info("package.netns_setup", netns=self.name, host_ip=self.host_ip)

    async def teardown(self) -> None:
        await _ip("netns", "del", self.name, check=False)
        await _ip("link", "del", self.veth_host, check=False)

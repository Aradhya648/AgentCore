"""Hostname allowlist from packaging registries + egress-only CDN hosts (not deny-private)."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from agentcore.tools.builtin.package_install import (
    ALLOWED_NPM_HOSTS,
    ALLOWED_NPM_REGISTRIES,
)


@lru_cache(maxsize=1)
def allowed_registry_hosts() -> frozenset[str]:
    """Lowercased hostnames: registry URLs + ``ALLOWED_NPM_HOSTS`` (CDN ≠ pin registry)."""
    hosts: set[str] = set()
    for raw in ALLOWED_NPM_REGISTRIES:
        host = (urlsplit(raw).hostname or "").lower().rstrip(".")
        if host:
            hosts.add(host)
    for raw in ALLOWED_NPM_HOSTS:
        host = (raw or "").lower().strip().rstrip(".")
        if host:
            hosts.add(host)
    return frozenset(hosts)


def host_is_allowed_registry(host: str) -> bool:
    """True iff ``host`` is exactly one of the packaging allowlist hostnames."""
    normalized = (host or "").lower().strip().rstrip(".")
    if not normalized:
        return False
    return normalized in allowed_registry_hosts()

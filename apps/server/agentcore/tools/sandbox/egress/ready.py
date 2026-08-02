"""Readiness for packaging registry egress (honest preflight)."""

from __future__ import annotations

import sys

from agentcore.config import settings

# Align metadata.code with browser egress hard-fail when isolation cannot be created.
EGRESS_UNAVAILABLE_CODE = "egress_unavailable"


def registry_egress_available() -> bool:
    """True only when the host can enforce a real packaging allowlist chokepoint.

    Requires Linux + gVisor + a successful netns capability probe (shared with
    browser). Subprocess / unprobed / failed netns ⇒ False — callers must 甲-degrade
    rather than pretend argv/env pin is network-layer allowlisting.
    """
    if sys.platform != "linux" or not settings.gvisor_enabled:
        return False
    # Reuse browser netns probe: same host capability (ip netns add/del).
    from agentcore.tools.sandbox.browser.netns import browser_netns_health

    return browser_netns_health() is True

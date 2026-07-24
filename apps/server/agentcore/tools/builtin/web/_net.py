"""Per-host egress circuit breaker for direct-egress web tools.

Stateless networking primitives live in :mod:`agentcore.core.net`. This module
holds only the in-process per-host breaker used by ``read_url`` and search backends.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from agentcore.core.net import EgressError

__all__ = [
    "WEB_HOST_FAIL_THRESHOLD",
    "WEB_HOST_CIRCUIT_COOLDOWN",
    "EgressError",
    "circuit_remaining",
    "note_failure",
    "note_success",
]

WEB_HOST_FAIL_THRESHOLD = 3  # consecutive transport failures before tripping
WEB_HOST_CIRCUIT_COOLDOWN = 120.0  # how long a tripped host stays short-circuited


@dataclass
class _HostState:
    fails: int = 0
    open_until: float = 0.0


# Best-effort, in-process breaker. Single event loop → plain dict mutations are
# safe enough; state is intentionally ephemeral (resets on restart).
_states: dict[str, _HostState] = {}


def circuit_remaining(host: str) -> float:
    """Seconds the breaker stays open for ``host`` (``0.0`` = closed/allowed)."""
    st = _states.get(host)
    if st is None:
        return 0.0
    return max(0.0, st.open_until - time.monotonic())


def note_success(host: str) -> None:
    """Clear a host's failure streak after a successful request."""
    _states.pop(host, None)


def note_failure(host: str) -> None:
    """Record a transport failure; trip the breaker at the configured threshold."""
    if not host:
        return
    st = _states.setdefault(host, _HostState())
    st.fails += 1
    if st.fails >= WEB_HOST_FAIL_THRESHOLD:
        st.open_until = time.monotonic() + WEB_HOST_CIRCUIT_COOLDOWN

"""Per-host egress circuit breaker + run-scoped web-read retirement.

Stateless networking primitives live in :mod:`agentcore.core.net`. This module
holds the in-process per-host breaker used by ``read_url`` / search backends, and
the run-scoped ``read_url`` retirement latch that survives ``react_loop`` restart
(stream-stall → ``run.failed`` → Wave ``on_failure=retry``, contract write_pass /
retry) so a disabled web-read tool is not re-offered into another empty-spin pass.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from agentcore.core.net import EgressError

__all__ = [
    "WEB_HOST_FAIL_THRESHOLD",
    "WEB_HOST_CIRCUIT_COOLDOWN",
    "READ_URL_RETIRE_STEER",
    "EgressError",
    "circuit_remaining",
    "note_failure",
    "note_success",
    "mark_read_url_retired",
    "read_url_retire_message",
    "clear_read_url_retired",
    "is_read_url_retired",
]

WEB_HOST_FAIL_THRESHOLD = 3  # consecutive transport failures before tripping
WEB_HOST_CIRCUIT_COOLDOWN = 120.0  # how long a tripped host stays short-circuited

# Model-facing hard-stop after the run-scoped tool circuit breaker disables read_url.
# Survives loop restart via :func:`mark_read_url_retired` so Wave/contract retries
# cannot re-open the same empty-spin surface.
READ_URL_RETIRE_STEER = (
    "read_url 外网深读已因连续失败停用——请立即停止换 URL / 换策略重试；"
    "基于已有 web_search 摘要与已读材料收口写作或 handoff，不要再发起外网读页。"
)


@dataclass
class _HostState:
    fails: int = 0
    open_until: float = 0.0


# Best-effort, in-process breaker. Single event loop → plain dict mutations are
# safe enough; state is intentionally ephemeral (resets on restart).
_states: dict[str, _HostState] = {}
# run_id → steer message. Mirrors LoopController disable for read_url across
# react_loop death (same process / same run_id).
_read_url_retired: dict[str, str] = {}


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


def mark_read_url_retired(run_id: str, *, message: str | None = None) -> None:
    """Latch ``read_url`` as retired for this run (idempotent)."""
    rid = (run_id or "").strip()
    if not rid:
        return
    _read_url_retired[rid] = (message or READ_URL_RETIRE_STEER).strip()


def read_url_retire_message(run_id: str) -> str | None:
    """Steer text if ``read_url`` was retired for ``run_id``, else ``None``."""
    rid = (run_id or "").strip()
    if not rid:
        return None
    return _read_url_retired.get(rid)


def is_read_url_retired(run_id: str) -> bool:
    return read_url_retire_message(run_id) is not None


def clear_read_url_retired(run_id: str) -> None:
    """Drop the retirement latch (run teardown hygiene)."""
    rid = (run_id or "").strip()
    if rid:
        _read_url_retired.pop(rid, None)

"""Classify DB exceptions so best-effort background sweeps log loudly on real faults.

A schema / programming error (missing table or column, malformed SQL) is a
PERSISTENT misconfiguration — almost always a pending migration — not a transient
blip. The periodic retention / consolidation sweeps are best-effort (a failure must
not kill the loop), but a *whole background task silently failing every interval*
deserves ``error`` so a watchdog catches it; an ordinary transient DB hiccup stays
``warning`` (the next interval will likely clear it).

→ 见: conversation-logs.mdc「找优化点」/ logging.mdc 事件分级
"""

from __future__ import annotations

from sqlalchemy.exc import ProgrammingError


def is_schema_error(exc: BaseException) -> bool:
    """True if ``exc`` is a DB schema / programming fault (undefined table/column,
    bad SQL) — a persistent misconfiguration to surface at ``error``, vs a transient
    operational failure to log at ``warning``."""
    return isinstance(exc, ProgrammingError)

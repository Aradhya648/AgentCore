"""Billing attribution helpers — run/persona stamps on proxied LLM calls.

Sidecar workers bind ``run_id`` / ``agent_id`` / ``cost_role`` / ``persona`` into
log context; the OpenAI-compatible provider merges them into inference-proxy
headers on every request. The cloud proxy reads those headers when writing
``cost_calls`` detail rows so sidecar and in-process cloud turns share one
ledger topology.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from agentcore.core.log_context import get_log_value
from agentcore.core.types import new_id
from agentcore.llm.credentials import (
    INFERENCE_AGENT_HEADER,
    INFERENCE_CALL_HEADER,
    INFERENCE_PARENT_RUN_HEADER,
    INFERENCE_PERSONA_HEADER,
    INFERENCE_ROLE_HEADER,
    INFERENCE_RUN_HEADER,
)
from agentcore.runtime.costing import ROLE_CAPTAIN, ROLE_MEMBER

_ALLOWED_ROLES = frozenset({"captain", "member", "arena", "title", "memory", "vision"})


def _encode_persona(value: str) -> str:
    """RFC 3986 percent-encode a persona label for HTTP header transport.

    Personas are free-form human labels the CEO invents（「调研员」「前端工程师」…）—
    almost always non-ASCII, which httpx (rightly) refuses to put on the wire raw.
    Percent-encoding keeps the header ASCII; the proxy decodes symmetrically.
    ASCII-only labels pass through unchanged (``quote`` leaves unreserved chars).
    """
    return quote(value, safe="")


def _decode_persona(value: str) -> str:
    """Inverse of :func:`_encode_persona`; tolerates un-encoded legacy values."""
    try:
        return unquote(value)
    except Exception:  # noqa: BLE001 — untrusted client header; keep as-is
        return value


def attribution_headers_from_context() -> dict[str, str]:
    """Build inference-proxy attribution headers from the current log context.

    Always mints a fresh ``call_id`` so each successful HTTP attempt that reaches
    the proxy has a stable idempotency key for the ledger outbox. Empty context
    values are omitted (except call id).
    """
    headers: dict[str, str] = {INFERENCE_CALL_HEADER: f"call_{new_id()}"}
    run_id = get_log_value("run_id")
    if run_id:
        headers[INFERENCE_RUN_HEADER] = run_id
    parent = get_log_value("parent_run_id")
    if parent:
        headers[INFERENCE_PARENT_RUN_HEADER] = parent
    agent_id = get_log_value("agent_id")
    if agent_id:
        headers[INFERENCE_AGENT_HEADER] = agent_id
    role = get_log_value("cost_role")
    if role:
        headers[INFERENCE_ROLE_HEADER] = role
    persona = get_log_value("persona")
    if persona:
        headers[INFERENCE_PERSONA_HEADER] = _encode_persona(persona)
    return headers


def parse_attribution_headers(headers) -> dict[str, str | None]:
    """Extract attribution fields from an incoming inference-proxy request."""

    def _get(name: str) -> str | None:
        raw = headers.get(name)
        if raw is None:
            return None
        value = str(raw).strip()
        return value or None

    role = _get(INFERENCE_ROLE_HEADER)
    if role and role not in _ALLOWED_ROLES:
        # Untrusted client header — fall back rather than fail the turn.
        role = None
    persona_raw = _get(INFERENCE_PERSONA_HEADER)
    return {
        "run_id": _get(INFERENCE_RUN_HEADER),
        "parent_run_id": _get(INFERENCE_PARENT_RUN_HEADER),
        "agent_id": _get(INFERENCE_AGENT_HEADER),
        "role": role,
        "persona": _decode_persona(persona_raw) if persona_raw else None,
        "call_id": _get(INFERENCE_CALL_HEADER),
    }


def default_role_for_agent(*, agent_id: str | None, run_id: str | None) -> str:
    """Best-effort structural role when the client omitted ``cost_role``."""
    if agent_id in ("CEO", "captain"):
        return ROLE_CAPTAIN
    if run_id or agent_id:
        return ROLE_MEMBER
    return ROLE_CAPTAIN

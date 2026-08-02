"""Turn-scoped API-key auth death flag — single source of truth (甲+乙).

Within one user turn, the first confirmed ``LLMAuthError`` (real API key
rejection — **not** ``InferenceTokenExpiredError`` / remint path) latches a
shared mutable flag. Later *unstarted* LLM work short-circuits here instead of
hitting upstream again.

Scope: one turn only (ContextVar + mutable object, same pattern as
``turn_token_budget``). **No** process-wide / cross-turn / TTL negative cache
(丙 deferred; keeps ``平台LLM接入``「禁止进程内 auth 熔断缓存」).

Consumers (all read this module — do not invent parallel flags):

- ``ObservingLLMProvider`` — mark on auth death; raise before new complete/stream
- ``run_background_llm`` — skip chrome when latched
- ``resolve_wave_budget_hooks`` / materialise — stop admitting unstarted workers
- ``delegate`` / ``debate`` tools — hard-refuse new batches
"""

from __future__ import annotations

import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from agentcore.core.errors import InferenceTokenExpiredError, LLMAuthError

TURN_AUTH_DEAD_REJECT_MESSAGE = (
    "本回合 API Key 鉴权已失败，已跳过后续模型调用。请先更新密钥或改用可用凭据后再试。"
)

REASON_TURN_AUTH_DEAD = "turn_auth_dead"


@dataclass
class TurnAuthDeadState:
    """Mutable turn-scoped latch (shared across asyncio tasks via object identity)."""

    dead: bool = False
    credential_source: str | None = None  # "user" | "platform"
    message: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


_state: ContextVar[TurnAuthDeadState | None] = ContextVar("turn_auth_dead", default=None)


def bind_turn_auth_dead() -> Token[TurnAuthDeadState | None]:
    """Install a fresh latch for this user turn; returns reset token."""
    return _state.set(TurnAuthDeadState())


def reset_turn_auth_dead(token: Token[TurnAuthDeadState | None]) -> None:
    _state.reset(token)


def credential_source_from_auth_error(exc: LLMAuthError) -> str:
    """Map an auth error to wire ``credential_source`` (user BYOK vs platform)."""
    explicit = exc.details.get("credential_source")
    if explicit in ("user", "platform"):
        return str(explicit)
    provider = (exc.details.get("provider_name") or "").strip()
    if provider == "platform":
        return "platform"
    return "user"


def is_real_api_key_auth_death(exc: BaseException) -> bool:
    """True for mid-turn API key 401/403 — excludes inference-JWT remint path."""
    return isinstance(exc, LLMAuthError) and not isinstance(exc, InferenceTokenExpiredError)


def mark_turn_auth_dead(exc: BaseException) -> bool:
    """Latch on first real API-key auth death. Returns True when newly marked."""
    if not is_real_api_key_auth_death(exc):
        return False
    assert isinstance(exc, LLMAuthError)
    state = _state.get()
    if state is None:
        return False
    with state._lock:
        if state.dead:
            return False
        state.dead = True
        state.credential_source = credential_source_from_auth_error(exc)
        state.message = (exc.message or "").strip() or TURN_AUTH_DEAD_REJECT_MESSAGE
    try:
        from agentcore.core.logging import get_logger

        get_logger(__name__).info(
            "llm.turn_auth_dead",
            credential_source=state.credential_source,
        )
    except Exception:  # noqa: BLE001 — observability must not break the turn
        pass
    return True


def is_turn_auth_dead() -> bool:
    state = _state.get()
    return bool(state is not None and state.dead)


def turn_auth_dead_reject_message() -> str:
    state = _state.get()
    if state is not None and state.message:
        return state.message
    return TURN_AUTH_DEAD_REJECT_MESSAGE


def raise_if_turn_auth_dead() -> None:
    """Raise ``LLMAuthError`` when the turn latch is set (no upstream call)."""
    state = _state.get()
    if state is None or not state.dead:
        return
    source = state.credential_source or "user"
    raise LLMAuthError(
        turn_auth_dead_reject_message(),
        provider_name="platform" if source == "platform" else "user",
        credential_source=source,
        short_circuited=True,
    )

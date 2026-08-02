"""Turn-scoped LLM credential death flag — single source of truth (甲+乙 + 余额并入).

Within one user turn, the first confirmed **non-retryable credential failure**
latches a shared mutable flag:

- ``LLMAuthError`` — real API key 401/403 (**not** ``InferenceTokenExpiredError``)
- ``LLMInsufficientBalanceError`` — upstream 402 / exhausted balance

Later *unstarted* LLM work short-circuits here instead of hitting upstream again.
Re-raise preserves the original error class so client CTAs stay correct
(换钥匙 vs 去充值).

Scope: one turn only (ContextVar + mutable object, same pattern as
``turn_token_budget``). **No** process-wide / cross-turn / TTL negative cache
(丙 deferred; keeps ``平台LLM接入``「禁止进程内 auth 熔断缓存」).

Consumers (all read this module — do not invent parallel flags):

- ``ObservingLLMProvider`` — mark on death; raise before new complete/stream
- ``run_background_llm`` — skip chrome when latched
- ``resolve_wave_budget_hooks`` / materialise — stop admitting unstarted workers
- ``delegate`` / ``debate`` tools — hard-refuse new batches
"""

from __future__ import annotations

import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Literal

from agentcore.core.errors import (
    InferenceTokenExpiredError,
    LLMAuthError,
    LLMInsufficientBalanceError,
)

TURN_AUTH_DEAD_REJECT_MESSAGE = (
    "本回合 API Key 鉴权已失败，已跳过后续模型调用。请先更新密钥或改用可用凭据后再试。"
)

TURN_BALANCE_DEAD_REJECT_MESSAGE = (
    "本回合账户余额不足，已跳过后续模型调用。请充值或换用可用凭据后再试。"
)

REASON_TURN_AUTH_DEAD = "turn_auth_dead"

LatchKind = Literal["auth", "balance"]


@dataclass
class TurnAuthDeadState:
    """Mutable turn-scoped latch (shared across asyncio tasks via object identity)."""

    dead: bool = False
    kind: LatchKind = "auth"
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


def is_insufficient_balance_death(exc: BaseException) -> bool:
    """True for upstream 402 / exhausted balance (not retryable)."""
    return isinstance(exc, LLMInsufficientBalanceError)


def is_latchable_llm_death(exc: BaseException) -> bool:
    """True when this turn should short-circuit further unstarted LLM work."""
    return is_real_api_key_auth_death(exc) or is_insufficient_balance_death(exc)


def mark_turn_auth_dead(exc: BaseException) -> bool:
    """Latch on first auth or balance death. Returns True when newly marked."""
    if not is_latchable_llm_death(exc):
        return False
    state = _state.get()
    if state is None:
        return False
    with state._lock:
        if state.dead:
            return False
        state.dead = True
        if is_insufficient_balance_death(exc):
            assert isinstance(exc, LLMInsufficientBalanceError)
            state.kind = "balance"
            # Balance is almost always the caller's own key account.
            src = exc.details.get("credential_source")
            state.credential_source = src if src in ("user", "platform") else "user"
            state.message = (exc.message or "").strip() or TURN_BALANCE_DEAD_REJECT_MESSAGE
        else:
            assert isinstance(exc, LLMAuthError)
            state.kind = "auth"
            state.credential_source = credential_source_from_auth_error(exc)
            state.message = (exc.message or "").strip() or TURN_AUTH_DEAD_REJECT_MESSAGE
    try:
        from agentcore.core.logging import get_logger

        get_logger(__name__).info(
            "llm.turn_auth_dead",
            credential_source=state.credential_source,
            kind=state.kind,
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
    if state is not None and state.kind == "balance":
        return TURN_BALANCE_DEAD_REJECT_MESSAGE
    return TURN_AUTH_DEAD_REJECT_MESSAGE


def raise_if_turn_auth_dead() -> None:
    """Re-raise the latched error class when set (no upstream call)."""
    state = _state.get()
    if state is None or not state.dead:
        return
    source = state.credential_source or "user"
    msg = turn_auth_dead_reject_message()
    if state.kind == "balance":
        raise LLMInsufficientBalanceError(
            msg,
            credential_source=source,
            short_circuited=True,
        )
    raise LLMAuthError(
        msg,
        provider_name="platform" if source == "platform" else "user",
        credential_source=source,
        short_circuited=True,
    )

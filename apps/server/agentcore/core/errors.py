"""Exception hierarchy for AgentCore.

All module-specific errors inherit from AgentCoreError.
Each error carries a code, message, and retryable flag for the API layer to translate
into appropriate HTTP responses. Every ``code`` is a member of the single
:class:`~agentcore.core.error_codes.ErrorCode` catalog (the shared directory),
so codes never drift apart from the SSE emitters or the frontend mirror.
"""

from agentcore.core.error_codes import ErrorCode


class AgentCoreError(Exception):
    """Base exception for all AgentCore errors."""

    code: str = ErrorCode.INTERNAL_ERROR
    retryable: bool = False
    status_code: int = 500

    def __init__(self, message: str = "", **kwargs):
        self.message = message
        self.details = kwargs
        super().__init__(message)


class LLMError(AgentCoreError):
    """LLM provider call failure."""

    code = ErrorCode.LLM_ERROR
    status_code = 502


class LLMUpstreamError(LLMError):
    """Upstream provider returned 5xx (transient server error). Retryable."""

    retryable = True


class LLMRateLimitError(LLMError):
    """LLM API rate limit hit (429). User-facing zh message; retryable."""

    code = ErrorCode.LLM_RATE_LIMIT
    retryable = True

    def __init__(self, retry_after: float | None = None, **kwargs):
        self.retry_after = retry_after
        # 工程侧不睡满 >30s 的 Retry-After；文案也不承诺「等一小时」。
        if retry_after is not None and 0 < retry_after <= 30:
            message = (
                f"上游限流，暂时无法继续本回合。请约 {int(retry_after)} 秒后再试，或点重试。"
            )
        else:
            message = "上游限流，暂时无法继续本回合。请稍后再试或点重试。"
        # retry_after 进 details，供 SSE ErrorContext / history 复用。
        super().__init__(message, retry_after=retry_after, **kwargs)


class LLMTimeoutError(LLMError):
    """LLM API request timed out."""

    code = ErrorCode.LLM_TIMEOUT
    retryable = True


class LLMInsufficientBalanceError(LLMError):
    """The user's own DeepSeek key reached the API but the account balance is
    exhausted, so the upstream refuses the call with HTTP 402 Insufficient Balance.

    Distinct from ``BYOKKeyMissingError`` (no key at all, refused at the route
    preflight before the stream opens): here a *valid* key fails mid-turn, so the
    error surfaces as an inline ``error`` event rather than a 402 JSON response. Not
    retryable — an immediate retry just re-fails until the user tops up — and it
    carries a user-facing Chinese message pointing at DeepSeek's billing page, not
    AgentCore's key settings (the key is fine; the balance is not).
    """

    code = ErrorCode.LLM_INSUFFICIENT_BALANCE
    retryable = False

    def __init__(
        self,
        message: str = ("DeepSeek 账户余额不足，请前往 DeepSeek 开放平台充值后重试。"),
        **kwargs,
    ):
        super().__init__(message, **kwargs)


class LLMAuthError(LLMError):
    """Configured API key rejected upstream (HTTP 401/403): invalid, revoked,
    or lacking permission — for any provider (BYOK DeepSeek, platform Claude, …).

    Distinct from ``BYOKKeyMissingError`` (no key at all, refused at preflight): a
    *configured* key fails mid-turn, so it surfaces as an inline ``error`` event. Not
    retryable — re-sending with the same bad key just re-fails — and its message (and
    the ``LLM_KEY_INVALID`` code, which the client maps to a "去配置" action) routes
    the user back to 设置·模型配置 to fix the key.

    Platform keys are operator-owned: default copy must not echo upstream gateway
    help (e.g. CC Switch tutorials) or the internal provider label ``platform``.
    """

    code = ErrorCode.LLM_KEY_INVALID
    retryable = False

    _PLATFORM_MESSAGE = (
        "平台模型暂时不可用（上游鉴权失败）。请改用自己的 API Key，或联系管理员。"
    )

    def __init__(
        self,
        message: str | None = None,
        *,
        provider_name: str | None = None,
        **kwargs,
    ):
        name = (provider_name or "").strip()
        if message is None:
            if name == "platform":
                message = self._PLATFORM_MESSAGE
            else:
                label = name if name and name != "user" else "当前模型"
                message = (
                    f"{label} API Key 无效或无权限，请在「设置 · 模型配置」中更新后重试。"
                )
        # Wire CTA 分流：platform → 接入自己的 Key；user/BYOK → 去设置换 Key。
        if "credential_source" not in kwargs:
            kwargs["credential_source"] = "platform" if name == "platform" else "user"
        if provider_name is not None and "provider_name" not in kwargs:
            kwargs["provider_name"] = provider_name
        super().__init__(message, **kwargs)


class InferenceTokenExpiredError(LLMAuthError):
    """Sidecar→cloud inference proxy JWT rejected (invalid / expired).

    Distinct from BYOK ``LLM_KEY_INVALID``: the user should remint / re-login /
    retry the turn — not open「设置 · 服务商」to edit an API key. ``retryable``
    so the desktop can clear the cache, mint once, and retry the turn.
    """

    code = ErrorCode.INFERENCE_TOKEN_EXPIRED
    retryable = True

    _DEFAULT_MESSAGE = (
        "本地与云端的推理凭证已失效或过期。请点击重试（将自动换新凭证）；"
        "仍失败请重新登录后再试。"
    )

    def __init__(self, message: str | None = None, **kwargs):
        # Bypass LLMAuthError's BYOK「去设置」default copy.
        LLMError.__init__(self, message or self._DEFAULT_MESSAGE, **kwargs)


class LLMClientClosedError(LLMError):
    """httpx client was closed while a caller still tried to send (turn teardown race).

    Coordination background drives clone an independent client so chat-turn
    ``llm.close()`` cannot hit in-flight workers; residual paths that still share a
    closed client must not burn WaveScheduler infra retries — re-POST on the same
    closed client is deterministic failure.
    """

    code = ErrorCode.LLM_ERROR
    retryable = False

    def __init__(
        self,
        message: str = "Cannot send a request, as the client has been closed.",
        **kwargs,
    ):
        super().__init__(message, **kwargs)


def is_llm_client_closed_error(exc: BaseException) -> bool:
    """True for typed closed-client errors or httpx's RuntimeError wording."""
    if isinstance(exc, LLMClientClosedError):
        return True
    if isinstance(exc, RuntimeError):
        return "client has been closed" in str(exc).lower()
    return False


class ToolError(AgentCoreError):
    """Tool execution failure."""

    code = ErrorCode.TOOL_ERROR
    status_code = 500


class ToolNotFoundError(ToolError):
    """Requested tool not registered."""

    code = ErrorCode.TOOL_NOT_FOUND
    status_code = 404


class SandboxError(AgentCoreError):
    """Code sandbox execution failure."""

    code = ErrorCode.SANDBOX_ERROR
    status_code = 500


class SandboxTimeoutError(SandboxError):
    """Code execution exceeded timeout."""

    code = ErrorCode.SANDBOX_TIMEOUT


class AuthenticationError(AgentCoreError):
    """Authentication failure."""

    code = ErrorCode.AUTH_ERROR
    status_code = 401


class AuthorizationError(AgentCoreError):
    """Authorization/permission failure."""

    code = ErrorCode.FORBIDDEN
    status_code = 403


class AdminProductForbiddenError(AuthorizationError):
    """Admin accounts cannot authenticate on product clients (desktop / mobile)."""

    code = ErrorCode.ADMIN_PRODUCT_FORBIDDEN

    def __init__(self, message: str = "管理员账号请使用管理后台登录", **kwargs):
        super().__init__(message, **kwargs)


class MfaRequiredError(AgentCoreError):
    """Password verified; TOTP step still pending."""

    code = ErrorCode.MFA_REQUIRED
    status_code = 401


class MfaSetupRequiredError(AgentCoreError):
    """Admin session exists but MFA enrollment is incomplete."""

    code = ErrorCode.MFA_SETUP_REQUIRED
    status_code = 428


class NotFoundError(AgentCoreError):
    """Resource not found."""

    code = ErrorCode.NOT_FOUND
    status_code = 404


class ConflictError(AgentCoreError):
    """Request conflicts with the resource's current state (HTTP 409).

    e.g. moving a *started* conversation between folders: its folder decides which
    workspace directory it runs in — and whether cloud or local (双模式工作区 §七:
    folder = project = workspace) — so re-filing a chat that has already
    accumulated files would silently re-point it at a different directory. The
    workspace is fixed once a conversation has any messages, so the move is refused
    rather than quietly switching it.
    """

    code = ErrorCode.CONFLICT
    status_code = 409


class ValidationError(AgentCoreError):
    """Input validation failure."""

    code = ErrorCode.VALIDATION_ERROR
    status_code = 422


class RateLimitedError(AgentCoreError):
    """Too many requests in a rolling window; this one is refused (HTTP 429).

    The 速率 line of defense (成本配额与计费.md §一), orthogonal to 配额 (总量):
    rate limiting caps requests-per-window, quota caps cumulative usage. Per-user
    message-send throttling is enforced at the route layer against the authenticated
    user. ``retry_after`` (seconds) rides along so the API layer can emit a
    ``Retry-After`` header and the client can show a friendly cool-down. Reuses the
    ``RATE_LIMITED`` code shared with the auth-endpoint limiter so the client handles
    one rate-limit shape regardless of which layer tripped.
    """

    code = ErrorCode.RATE_LIMITED
    status_code = 429

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, retry_after=retry_after, **kwargs)


class QuotaExceededError(AgentCoreError):
    """A configured usage quota is exhausted; the next turn is refused.

    Three independent dimensions (daily tokens / monthly cost / daily requests),
    checked before a turn starts (成本配额与计费.md §一). Maps to HTTP 429 so the
    client can surface a "quota reached" state distinct from auth (401) or
    validation (422). ``dimension`` / ``used`` / ``limit`` ride along on the
    exception for logging and tests.
    """

    code = ErrorCode.QUOTA_EXCEEDED
    status_code = 429

    def __init__(
        self,
        message: str = "",
        *,
        dimension: str = "",
        used: int = 0,
        limit: int = 0,
        **kwargs,
    ):
        self.dimension = dimension
        self.used = used
        self.limit = limit
        super().__init__(message, dimension=dimension, used=used, limit=limit, **kwargs)


class BYOKKeyMissingError(AgentCoreError):
    """No usable BYOK LLM key is configured, so a turn cannot start.

    In BYOK billing mode every user-facing turn runs on the user's own API key;
    with none configured the turn is refused *before* the SSE opens (route preflight)
    so the client can route the user to 设置·模型配置 rather than getting a
    half-opened stream. 402 Payment Required fits "you must supply your own
    billing credentials to proceed", and the ``LLM_KEY_REQUIRED`` code lets the
    client distinguish it from auth (401) / quota (429).
    """

    code = ErrorCode.LLM_KEY_REQUIRED
    status_code = 402


class PlatformBillingUnavailableError(AgentCoreError):
    """User chose platform free quota but the operator key is not configured."""

    code = ErrorCode.PLATFORM_BILLING_UNAVAILABLE
    status_code = 503


class ResumeJournalDegradedError(AgentCoreError):
    """A durable pause frame survived but its ``turn_journal`` mirror did not.

    Resume cannot rebuild the CEO window from facts alone; the user must abandon the
    paused turn and start fresh rather than continuing on a silently empty context.
    """

    code = ErrorCode.STREAM_ERROR


class KeyStorageUnavailableError(AgentCoreError):
    """The server cannot store or read BYOK keys because no encryption master key
    is configured (settings.encryption_key).

    BYOK requires AES-256-GCM at-rest encryption (security.KeyEncryptor); without
    the master key the set-key endpoint refuses to store a key it could never read
    back (fail-safe: plaintext never lands on disk). 503 Service Unavailable —
    it's a server misconfiguration, not the user's fault, and is fixable by
    setting ENCRYPTION_KEY and restarting.
    """

    code = ErrorCode.KEY_STORAGE_UNAVAILABLE
    status_code = 503


def error_fields_for(
    exc: BaseException,
    *,
    fallback_code: str,
    fallback_message: str,
) -> tuple[str, str, dict | None]:
    """Decide the ``(code, message, context)`` an SSE ``error`` event should carry."""
    if isinstance(exc, AgentCoreError):
        from agentcore.llm.errors import error_context_from

        return (
            exc.code,
            (exc.message or fallback_message),
            error_context_from(exc),
        )
    return fallback_code, fallback_message, None

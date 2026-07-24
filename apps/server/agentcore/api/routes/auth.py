"""Authentication routes: register, login, refresh, logout, me (+ bearer-token twins).

The cookie flow delivers tokens as httpOnly cookies so the browser/Electron client
never handles them in JS (XSS-resistant); the refresh cookie is path-scoped to the
auth endpoints and the access cookie rides every API call. The ``/token*`` endpoints
are the body-returning twins for non-cookie clients (mobile web / Capacitor shell,
M2) whose origin can't rely on SameSite cookies — they send ``Authorization: Bearer``
instead (认证与会话.md §十; resolution in api/dependencies.py).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.admin.audit import record_admin_audit
from agentcore.api.account_cleanup import cleanup_account_resources
from agentcore.api.dependencies import (
    ACCESS_TOKEN_COOKIE,
    AdminSessionUser,
    AdminUser,
    AuthUser,
    get_admin_mfa_service,
    get_asset_storage,
    get_auth_service,
    get_conversation_repo,
    get_conversation_share_repo,
    get_credentials_repo,
    get_db,
    get_messaging_service,
    get_shared_space_service,
    get_user_llm_provider_repo,
    get_user_repo,
)
from agentcore.api.schemas import (
    BatchCreateInviteRequest,
    ChangePasswordRequest,
    CreateInviteRequest,
    DeleteAccountRequest,
    InviteListResponse,
    InviteResponse,
    InviteStatsResponse,
    LoginMfaRequest,
    LoginRequest,
    LoginResponse,
    MfaConfirmRequest,
    MfaConfirmResponse,
    MfaSetupResponse,
    MfaStatusResponse,
    RegisterRequest,
    SessionListResponse,
    SessionSummary,
    StatusResponse,
    TokenRefreshRequest,
    TokenResponse,
    TokenRevokeRequest,
    UpdateProfileRequest,
    UserResponse,
)
from agentcore.auth import AuthService, TokenPair
from agentcore.auth.client import ClientPlatform, parse_client_platform
from agentcore.auth.mfa import AdminMfaService
from agentcore.auth.service import LoginResult, SessionMeta
from agentcore.config import settings
from agentcore.core.errors import AuthenticationError, ValidationError
from agentcore.core.logging import get_logger
from agentcore.db.models import Invite, User
from agentcore.db.repositories import (
    ConversationRepository,
    ConversationShareRepository,
    CredentialsRepository,
    UserLlmProviderRepository,
    UserRepository,
)
from agentcore.messaging import MessagingService
from agentcore.middleware.csrf import clear_csrf_token, issue_csrf_token
from agentcore.security.tokens import decode_access_token_claims
from agentcore.shared_spaces.service import SharedSpaceService
from agentcore.storage.assets import AssetStorage

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_TOKEN_COOKIE = "refresh_token"
# The refresh cookie only needs to reach the refresh/logout endpoints, so it's
# path-scoped (keeps the long-lived token off every other request). The scope must
# carry the API's external mount prefix (settings.cookie_path_prefix, e.g. `/api`
# behind the prod Nginx): the browser path-matches the cookie against the REAL request
# path `/api/v1/auth/refresh`, so a bare `/v1/auth` scope would never be sent there →
# silent refresh failure once the access token expires (认证与会话.md §七). Empty prefix
# (dev / same-origin) keeps the original `/v1/auth`.
_REFRESH_COOKIE_SUFFIX = "/v1/auth"


def _refresh_cookie_path() -> str:
    prefix = settings.cookie_path_prefix.strip().rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return f"{prefix}{_REFRESH_COOKIE_SUFFIX}"


RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE)]


def _session_meta_from_request(
    request: Request, *, platform: ClientPlatform | None = None
) -> SessionMeta:
    from agentcore.middleware.rate_limit import get_client_ip

    return SessionMeta(
        platform=platform,
        user_agent=request.headers.get("user-agent"),
        ip=get_client_ip(request),
    )


def _current_family_from_request(request: Request) -> str | None:
    fam = getattr(request.state, "token_family", None)
    return fam if isinstance(fam, str) and fam else None


def _user_response(user: User, *, password_must_change: bool = False) -> UserResponse:
    return UserResponse.from_user(user, password_must_change=password_must_change)


async def _login_response_for(
    result,
    creds_repo: CredentialsRepository,
) -> LoginResponse:
    user_resp = None
    if result.user is not None and not result.mfa_required:
        user_resp = await _user_response_for(result.user, creds_repo)
    return LoginResponse(
        user=user_resp,
        mfa_required=result.mfa_required,
        pending_token=result.pending_token,
        mfa_setup_required=result.mfa_setup_required,
    )


async def _user_response_for(
    user: User, creds_repo: CredentialsRepository
) -> UserResponse:
    creds = await creds_repo.get_by_user_id(user.user_id)
    return _user_response(user, password_must_change=bool(creds and creds.password_must_change))


def _invite_status(invite: Invite, now: datetime) -> str:
    # Terminal first: a consumed code stays "used" even if later revoked/expired.
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at is not None and invite.expires_at <= now:
        return "expired"
    return "active"


def _invite_response(
    invite: Invite,
    now: datetime,
    *,
    users_by_id: dict[str, User] | None = None,
) -> InviteResponse:
    users_by_id = users_by_id or {}
    created_user = users_by_id.get(invite.created_by) if invite.created_by else None
    used_user = users_by_id.get(invite.used_by) if invite.used_by else None
    return InviteResponse(
        id=invite.id,
        code=invite.code,
        status=_invite_status(invite, now),
        created_by=invite.created_by,
        used_by=invite.used_by,
        created_by_username=created_user.username if created_user else None,
        used_by_username=used_user.username if used_user else None,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        revoked_at=invite.revoked_at,
    )


async def _invite_responses(
    invites: Sequence[Invite],
    now: datetime,
    user_repo: UserRepository,
) -> list[InviteResponse]:
    user_ids = {
        uid
        for inv in invites
        for uid in (inv.created_by, inv.used_by)
        if uid is not None
    }
    users_by_id = await user_repo.get_by_ids(list(user_ids))
    return [_invite_response(inv, now, users_by_id=users_by_id) for inv in invites]


def _set_auth_cookies(response: Response, tokens: TokenPair, *, user_id: str) -> None:
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=tokens.access_token,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=tokens.refresh_token,
        max_age=settings.jwt_refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=_refresh_cookie_path(),
    )
    if settings.csrf_enabled:
        issue_csrf_token(response, user_id)


def _clear_auth_cookies(response: Response, *, user_id: str | None = None) -> None:
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path=_refresh_cookie_path())
    clear_csrf_token(response, user_id)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    body: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
    messaging: MessagingService = Depends(get_messaging_service),
):
    user = await service.register(
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        email=body.email,
    )
    # Enroll the new account into every auto-join chat (the 内测全员群). Best-effort
    # so a messaging hiccup never blocks account creation — a missed enrollment can
    # be backfilled later; auto-join fires only here (not on login) so leaving sticks.
    try:
        await messaging.join_auto_join_chats(user_id=user.user_id)
    except Exception:
        logger.warning("chat.auto_join_failed", user=user.user_id, exc_info=True)
    # Activation funnel: registration (queryable in logs/dev.jsonl).
    logger.info("auth.register", user_id=user.user_id)
    return _user_response(user)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    platform: Annotated[ClientPlatform, Depends(parse_client_platform)],
    service: AuthService = Depends(get_auth_service),
    creds_repo: CredentialsRepository = Depends(get_credentials_repo),
):
    result = await service.login(
        username=body.username,
        password=body.password,
        platform=platform,
        meta=_session_meta_from_request(request, platform=platform),
    )
    if result.tokens is not None:
        _set_auth_cookies(response, result.tokens, user_id=result.user.user_id)
    return await _login_response_for(result, creds_repo)


@router.post("/login/mfa", response_model=LoginResponse)
async def login_mfa(
    body: LoginMfaRequest,
    request: Request,
    response: Response,
    platform: Annotated[ClientPlatform, Depends(parse_client_platform)],
    service: AuthService = Depends(get_auth_service),
    creds_repo: CredentialsRepository = Depends(get_credentials_repo),
):
    user, tokens = await service.complete_mfa_login(
        pending_token=body.pending_token,
        code=body.code,
        recovery_code=body.recovery_code,
        meta=_session_meta_from_request(request, platform=platform),
    )
    _set_auth_cookies(response, tokens, user_id=user.user_id)
    return await _login_response_for(LoginResult(user=user, tokens=tokens), creds_repo)


@router.post("/refresh", response_model=StatusResponse)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: RefreshCookie = None,
    service: AuthService = Depends(get_auth_service),
):
    if not refresh_token:
        raise AuthenticationError("Missing refresh token")
    try:
        tokens = await service.refresh(
            refresh_token=refresh_token,
            meta=_session_meta_from_request(request),
        )
    except AuthenticationError:
        # Token invalid/expired/reused: clear cookies so the client logs in again.
        _clear_auth_cookies(response)
        raise
    user_id = decode_access_token_claims(tokens.access_token)[0]
    _set_auth_cookies(response, tokens, user_id=user_id)
    return StatusResponse()


@router.post("/logout", response_model=StatusResponse)
async def logout(
    response: Response,
    refresh_token: RefreshCookie = None,
    access_token: Annotated[str | None, Cookie(alias=ACCESS_TOKEN_COOKIE)] = None,
    service: AuthService = Depends(get_auth_service),
):
    user_id: str | None = None
    if access_token:
        try:
            user_id = decode_access_token_claims(access_token)[0]
        except AuthenticationError:
            user_id = None
    if refresh_token:
        await service.logout(refresh_token=refresh_token)
    _clear_auth_cookies(response, user_id=user_id)
    return StatusResponse()


# --- Bearer-token flow (mobile web / Capacitor shell, M2) ---
# Body-returning twins of the cookie login/refresh/logout above, for clients whose
# origin (capacitor:// / a new web origin) can't rely on SameSite cookies (认证与会话.md
# §十). Same AuthService + token machinery; the client stores the returned tokens and
# sends `Authorization: Bearer <access>` on every call (resolved in api/dependencies.py).


def _token_response(
    tokens: TokenPair,
    *,
    user: User | None = None,
    password_must_change: bool = False,
) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        refresh_expires_in=settings.jwt_refresh_token_expire_days * 86400,
        user=_user_response(user, password_must_change=password_must_change)
        if user is not None
        else None,
    )


@router.post("/token", response_model=TokenResponse)
async def token_login(
    body: LoginRequest,
    request: Request,
    platform: Annotated[ClientPlatform, Depends(parse_client_platform)],
    service: AuthService = Depends(get_auth_service),
    creds_repo: CredentialsRepository = Depends(get_credentials_repo),
):
    """Bearer-token login: same credential check as cookie ``/login`` but returns the
    access + refresh tokens in the JSON body (plus the user — identity in one call)."""
    result = await service.login(
        username=body.username,
        password=body.password,
        platform=platform,
        meta=_session_meta_from_request(request, platform=platform),
    )
    if result.mfa_required:
        raise AuthenticationError("MFA required — complete /v1/auth/login/mfa first")
    if result.tokens is None:
        raise AuthenticationError("Login failed")
    must_change = await service.password_must_change(user_id=result.user.user_id)
    return _token_response(
        result.tokens, user=result.user, password_must_change=must_change
    )


@router.post("/token/refresh", response_model=TokenResponse)
async def token_refresh(
    body: TokenRefreshRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
):
    """Rotate a bearer client's token pair (refresh token carried in the body). Reuse /
    expiry detection is the same family-revoking logic as cookie refresh."""
    tokens = await service.refresh(
        refresh_token=body.refresh_token,
        meta=_session_meta_from_request(request),
    )
    return _token_response(tokens)


@router.post("/token/revoke", response_model=StatusResponse)
async def token_revoke(
    body: TokenRevokeRequest,
    service: AuthService = Depends(get_auth_service),
):
    """Bearer-client logout: revoke the refresh token's whole family. Idempotent — an
    unknown / already-revoked token still returns ok (never reveals token validity)."""
    await service.logout(refresh_token=body.refresh_token)
    return StatusResponse()


@router.get("/me", response_model=UserResponse)
async def me(
    user: AuthUser,
    response: Response,
    creds_repo: CredentialsRepository = Depends(get_credentials_repo),
):
    # Re-establish the CSRF token for a session resumed via the access cookie: app
    # cold-start calls /me (not login/refresh), so without this the client holds a
    # valid session but no CSRF token and its first mutating request 403s. The token
    # is stateless (security.sign_csrf_token) — cheap to re-mint, and any valid
    # signature for this user verifies, so minting one here is safe and idempotent.
    if settings.csrf_enabled:
        issue_csrf_token(response, user.user_id)
    return await _user_response_for(user, creds_repo)


# --- Sessions (device / login management) ---


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    user: AuthUser,
    service: AuthService = Depends(get_auth_service),
):
    """List the caller's active login devices (one row per refresh-token family)."""
    sessions = await service.list_sessions(
        user_id=user.user_id,
        current_family=_current_family_from_request(request),
    )
    data = [
        SessionSummary(
            id=s.id,
            platform=s.platform,
            user_agent=s.user_agent,
            ip=s.ip,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            current=s.current,
        )
        for s in sessions
    ]
    return SessionListResponse(data=data, total=len(data))


@router.delete("/sessions/{family_id}", response_model=StatusResponse)
async def revoke_session(
    family_id: str,
    user: AuthUser,
    service: AuthService = Depends(get_auth_service),
):
    """Log out one device (revoke its refresh-token family). Own current session OK."""
    await service.revoke_session(user_id=user.user_id, family_id=family_id)
    return StatusResponse()


@router.post("/sessions/revoke-others", response_model=StatusResponse)
async def revoke_other_sessions(
    request: Request,
    user: AuthUser,
    service: AuthService = Depends(get_auth_service),
):
    """Log out every other device; keep the caller's current family.

    Access tokens without a ``fam`` claim (pre-upgrade) cannot identify "current"
    → 422 rather than revoke-all (which would drop this session too).
    """
    current = _current_family_from_request(request)
    if not current:
        raise ValidationError("当前会话缺少 fam 声明，请重新登录后再试")
    await service.revoke_other_sessions(user_id=user.user_id, current_family=current)
    return StatusResponse()


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    user: AuthUser,
    service: AuthService = Depends(get_auth_service),
):
    """Edit the signed-in user's profile (个人资料编辑). PATCH semantics: only the fields
    present in the body change — an explicit ``null`` email clears it, an omitted field
    is left untouched (distinguished via ``model_fields_set``)."""
    fields = body.model_dump(include=body.model_fields_set)
    updated = await service.update_profile(user_id=user.user_id, **fields)
    return _user_response(updated)


@router.post("/change-password", response_model=StatusResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: AuthUser,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    """Change the signed-in user's password (修改密码). All other devices are logged out
    (their refresh families are revoked); this session is handed fresh cookies so the
    active device stays signed in."""
    tokens = await service.change_password(
        user_id=user.user_id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    _set_auth_cookies(response, tokens, user_id=user.user_id)
    if user.role == "admin":
        await record_admin_audit(
            db,
            actor_id=user.user_id,
            action="account.change_password",
            target_type="account",
        )
    return StatusResponse()


@router.delete("/me", response_model=StatusResponse)
async def delete_account(
    body: DeleteAccountRequest,
    user: AuthUser,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    conversations: ConversationRepository = Depends(get_conversation_repo),
    shares: ConversationShareRepository = Depends(get_conversation_share_repo),
    llm_providers: UserLlmProviderRepository = Depends(get_user_llm_provider_repo),
    assets: AssetStorage = Depends(get_asset_storage),
    shared_space_svc: SharedSpaceService = Depends(get_shared_space_service),
):
    """Self-service account deletion (注销账户). Verifies the password, then soft-deletes
    + anonymizes the account and revokes all sessions. Cross-domain cleanup lives here
    (outside the auth domain): soft-delete the user's conversations so the retention
    sweeper reclaims their workspaces, revoke every public share link so no shared
    snapshot outlives the account, drop all BYOK providers so no ciphertext outlives the
    account, and remove the avatar object. Finally clear this device's cookies."""
    avatar_key = user.avatar_key  # captured before soft_delete nulls it
    await service.delete_account(user_id=user.user_id, password=body.password)
    await cleanup_account_resources(
        user.user_id,
        avatar_key=avatar_key,
        conversations=conversations,
        shares=shares,
        llm_providers=llm_providers,
        assets=assets,
        shared_spaces=shared_space_svc,
    )
    _clear_auth_cookies(response, user_id=user.user_id)
    return StatusResponse()


# --- Admin MFA (TOTP) ---


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def mfa_status(
    user: AdminSessionUser,
    mfa: AdminMfaService = Depends(get_admin_mfa_service),
):
    return MfaStatusResponse(
        enrolled=await mfa.is_enrolled(user.user_id),
        required=settings.admin_mfa_required,
    )


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(
    user: AdminSessionUser,
    mfa: AdminMfaService = Depends(get_admin_mfa_service),
):
    payload = await mfa.begin_setup(user_id=user.user_id, username=user.username)
    return MfaSetupResponse(secret=payload.secret, otpauth_uri=payload.otpauth_uri)


@router.post("/mfa/confirm", response_model=MfaConfirmResponse)
async def mfa_confirm(
    user: AdminSessionUser,
    body: MfaConfirmRequest,
    mfa: AdminMfaService = Depends(get_admin_mfa_service),
    db: AsyncSession = Depends(get_db),
):
    result = await mfa.confirm_setup(user_id=user.user_id, code=body.code)
    await record_admin_audit(
        db,
        actor_id=user.user_id,
        action="mfa.enroll",
        target_type="user",
        target_id=user.user_id,
    )
    return MfaConfirmResponse(recovery_codes=result.recovery_codes)


@router.post("/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    admin: AdminUser,
    body: CreateInviteRequest | None = None,
    service: AuthService = Depends(get_auth_service),
    user_repo: UserRepository = Depends(get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    invite = await service.create_invite(
        created_by=admin.user_id,
        expires_in_days=body.expires_in_days if body else None,
    )
    await record_admin_audit(
        db,
        actor_id=admin.user_id,
        action="invite.create",
        target_type="invite",
        target_id=invite.id,
        detail={"expires_in_days": body.expires_in_days if body else None},
    )
    now = datetime.now(UTC)
    users = await user_repo.get_by_ids([admin.user_id])
    return _invite_response(invite, now, users_by_id=users)


@router.post("/invites/batch", response_model=InviteListResponse, status_code=201)
async def create_invites_batch(
    admin: AdminUser,
    body: BatchCreateInviteRequest,
    service: AuthService = Depends(get_auth_service),
    user_repo: UserRepository = Depends(get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    """Mint multiple single-use invite codes (admin batch issuance)."""
    invites = await service.create_invites_batch(
        created_by=admin.user_id,
        count=body.count,
        expires_in_days=body.expires_in_days,
    )
    await record_admin_audit(
        db,
        actor_id=admin.user_id,
        action="invite.batch_create",
        target_type="invite",
        detail={"count": body.count, "expires_in_days": body.expires_in_days},
    )
    now = datetime.now(UTC)
    data = await _invite_responses(invites, now, user_repo)
    return InviteListResponse(
        data=data,
        total=len(invites),
    )


@router.get("/invites/stats", response_model=InviteStatsResponse)
async def invite_stats(
    admin: AdminUser,
    service: AuthService = Depends(get_auth_service),
):
    counts = await service.invite_stats()
    return InviteStatsResponse(**counts)


@router.get("/invites", response_model=InviteListResponse)
async def list_invites(
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    status: Literal["active", "used", "expired", "revoked"] | None = Query(None),
    search: str | None = Query(None, max_length=64),
    service: AuthService = Depends(get_auth_service),
    user_repo: UserRepository = Depends(get_user_repo),
):
    now = datetime.now(UTC)
    invites, total = await service.list_invites(
        page=page,
        page_size=page_size,
        status=status,
        search=search,
    )
    data = await _invite_responses(invites, now, user_repo)
    return InviteListResponse(
        data=data,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/invites/{invite_id}/revoke", response_model=InviteResponse)
async def revoke_invite(
    invite_id: str,
    admin: AdminUser,
    service: AuthService = Depends(get_auth_service),
    user_repo: UserRepository = Depends(get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    """Retire an unused invite (邀请码撤销). 404 unknown id; 422 if already used/revoked.
    Returns the now-revoked invite so the client can update the row in place."""
    invite = await service.revoke_invite(invite_id=invite_id)
    await record_admin_audit(
        db,
        actor_id=admin.user_id,
        action="invite.revoke",
        target_type="invite",
        target_id=invite_id,
    )
    now = datetime.now(UTC)
    user_ids = [uid for uid in (invite.created_by, invite.used_by) if uid is not None]
    users = await user_repo.get_by_ids(user_ids)
    return _invite_response(invite, now, users_by_id=users)

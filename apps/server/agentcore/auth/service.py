"""Authentication service: registration, login, token refresh, logout.

Holds all auth business logic and policy:
- open registration gated by ``REGISTRATION_OPEN`` (invite codes deprecated),
- brute-force lockout (failed-attempt counting + temporary lock),
- refresh-token rotation with reuse detection (a presented token that was
  already rotated/revoked compromises the whole family -> revoke it).

Repositories do pure data access; ``security`` does hashing/JWT; the HTTP layer
stays thin. The service depends on repository instances so it is unit-testable
with in-memory fakes (no DB).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agentcore.auth.client import ClientPlatform, is_product_platform, platform_to_audience
from agentcore.auth.mfa import AdminMfaService
from agentcore.config import settings
from agentcore.core.errors import (
    AdminProductForbiddenError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.db.models import Invite, RefreshToken, User
from agentcore.db.repositories import (
    CredentialsRepository,
    InviteRepository,
    RefreshTokenRepository,
    UserRepository,
)
from agentcore.security import (
    create_access_token,
    create_mfa_pending_token,
    decode_mfa_pending_token,
    generate_invite_code,
    generate_refresh_token,
    generate_temp_password,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from agentcore.security.tokens import TokenAudience

logger = get_logger(__name__)

_MIN_PASSWORD_LENGTH = 8
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION = timedelta(minutes=15)
_USER_AGENT_MAX = 512
# Benign-concurrency grace for refresh rotation: a just-rotated token re-presented
# within this window is treated as the *same* logical refresh, not a leak. Clients
# routinely fire several requests at once; when the access token has expired they
# each 401 and refresh with the same refresh cookie before the rotated one lands,
# so revoking the family there would log the user out mid-session for no reason
# (认证与会话.md §五). Past the window, a rotated token reappearing is a genuine
# reuse/replay and still nukes the family. The frontend also single-flights its
# refresh calls (services/api.ts) so this window is a backstop, not the only guard.
_REFRESH_REUSE_GRACE = timedelta(seconds=10)

# Constant-time login: an argon2 hash of a throwaway value. When the username/credentials
# don't exist we still run one verify against this, so "no such user" costs the same
# wall-clock as "wrong password" — denying the timing oracle an unauthenticated caller
# would otherwise use to enumerate valid usernames (SEC-004). Computed once at import.
_DUMMY_PASSWORD_HASH = hash_password("agentcore-login-timing-equalizer")

# Sentinel for "field not provided" in a partial profile update, distinct from an
# explicit None (which clears the nullable email column).
_UNSET: Any = object()


@dataclass(frozen=True)
class TokenPair:
    """Access JWT + opaque refresh token (raw form, for the caller to set as cookies)."""

    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class LoginResult:
    """Outcome of a credential check — tokens may be deferred for MFA."""

    user: User
    tokens: TokenPair | None = None
    mfa_required: bool = False
    pending_token: str | None = None
    mfa_setup_required: bool = False


@dataclass(frozen=True)
class SessionMeta:
    """Request-bound session bookkeeping captured at login / refresh."""

    platform: ClientPlatform | None = None
    user_agent: str | None = None
    ip: str | None = None


@dataclass(frozen=True)
class AuthSession:
    """One active login device (refresh-token family), owner-scoped."""

    id: str
    platform: str | None
    user_agent: str | None
    ip: str | None
    created_at: datetime
    last_used_at: datetime
    current: bool


def _truncate_ua(user_agent: str | None) -> str | None:
    if user_agent is None:
        return None
    ua = user_agent.strip()
    if not ua:
        return None
    return ua[:_USER_AGENT_MAX]


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        credentials: CredentialsRepository,
        refresh_tokens: RefreshTokenRepository,
        invites: InviteRepository,
        mfa: AdminMfaService | None = None,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._refresh_tokens = refresh_tokens
        self._invites = invites
        self._mfa = mfa

    async def register(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> User:
        if not settings.registration_open:
            raise AuthorizationError("注册已关闭")

        username = username.strip()
        if not username:
            raise ValidationError("请输入用户名")
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise ValidationError(f"密码至少需要 {_MIN_PASSWORD_LENGTH} 个字符")

        if await self._users.get_by_username(username) is not None:
            raise ValidationError("该用户名已被占用")

        user = await self._users.create(
            username=username, display_name=display_name or username, email=email
        )
        await self._credentials.create(user_id=user.user_id, password_hash=hash_password(password))
        return user

    async def login(
        self,
        *,
        username: str,
        password: str,
        platform: ClientPlatform = "desktop",
        meta: SessionMeta | None = None,
    ) -> LoginResult:
        user = await self._users.get_by_username(username.strip())
        creds = await self._credentials.get_by_user_id(user.user_id) if user else None
        # Uniform failure: never reveal whether the username exists. Run one verify
        # against a dummy hash so a missing user takes the same wall-clock as a wrong
        # password — no timing oracle for username enumeration (SEC-004). Result ignored.
        if user is None or creds is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("用户名或密码错误")

        now = datetime.now(UTC)
        if creds.locked_until is not None and creds.locked_until > now:
            raise AuthenticationError("账户已临时锁定，请稍后再试")

        if not verify_password(password, creds.password_hash):
            await self._register_failure(creds.user_id, creds.failed_attempts, now)
            raise AuthenticationError("用户名或密码错误")

        if creds.failed_attempts or creds.locked_until is not None:
            await self._credentials.reset_failure_state(user.user_id)

        if user.role == "admin" and is_product_platform(platform):
            raise AdminProductForbiddenError()

        if user.role != "admin" and platform == "admin":
            raise AuthenticationError("用户名或密码错误")

        audience = platform_to_audience(platform)
        session_meta = meta or SessionMeta(platform=platform)

        if user.role == "admin":
            if (
                settings.admin_mfa_required
                and self._mfa is not None
                and await self._mfa.is_enrolled(user.user_id)
            ):
                pending = create_mfa_pending_token(user.user_id, audience=audience)
                return LoginResult(
                    user=user,
                    mfa_required=True,
                    pending_token=pending,
                )
            tokens = await self._issue_tokens(
                user.user_id,
                family=new_id(),
                now=now,
                audience=audience,
                meta=session_meta,
            )
            return LoginResult(
                user=user,
                tokens=tokens,
                mfa_setup_required=settings.admin_mfa_required,
            )

        tokens = await self._issue_tokens(
            user.user_id,
            family=new_id(),
            now=now,
            audience=audience,
            meta=session_meta,
        )
        return LoginResult(user=user, tokens=tokens)

    async def complete_mfa_login(
        self,
        *,
        pending_token: str,
        code: str | None = None,
        recovery_code: str | None = None,
        meta: SessionMeta | None = None,
    ) -> tuple[User, TokenPair]:
        if self._mfa is None:
            raise AuthenticationError("MFA not configured")
        user_id, audience = decode_mfa_pending_token(pending_token)
        user = await self._users.get_by_id(user_id)
        if user is None or user.status != "active" or user.role != "admin":
            raise AuthenticationError("Invalid or expired MFA session")
        verified = False
        if code:
            verified = await self._mfa.verify_code(user_id=user_id, code=code.strip())
        elif recovery_code:
            verified = await self._mfa.verify_recovery_code(
                user_id=user_id, code=recovery_code.strip()
            )
        else:
            raise ValidationError("请输入验证码或恢复码")
        if not verified:
            raise AuthenticationError("验证码无效或已过期")
        now = datetime.now(UTC)
        platform: ClientPlatform = "admin" if audience == "admin" else "desktop"
        session_meta = meta or SessionMeta(platform=platform)
        tokens = await self._issue_tokens(
            user.user_id,
            family=new_id(),
            now=now,
            audience=audience,
            meta=session_meta,
        )
        return user, tokens

    async def refresh(
        self, *, refresh_token: str, meta: SessionMeta | None = None
    ) -> TokenPair:
        record = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))
        now = datetime.now(UTC)

        if record is None:
            raise AuthenticationError("Invalid refresh token")

        # Already revoked (logout / password change / a prior reuse detection):
        # the session is dead -> keep the family revoked, force a fresh login.
        if record.revoked_at is not None:
            await self._refresh_tokens.revoke_family(record.token_family)
            raise AuthenticationError("Refresh token reuse detected")

        # Absolute family ceiling (sliding renewals must not outlive this).
        try:
            self._assert_family_within_max(record, now=now)
        except AuthenticationError:
            await self._refresh_tokens.revoke_family(record.token_family)
            raise

        # Already rotated: benign concurrent retry vs. a real replay/leak. Inside
        # the grace window it's the same logical refresh (the access token expired
        # and several requests refreshed with the same cookie at once) -> mint a
        # fresh successor in the same family without revoking anyone. Outside it,
        # a rotated token reappearing is a genuine reuse -> revoke the family.
        if record.rotated_at is not None:
            if now - record.rotated_at > _REFRESH_REUSE_GRACE:
                await self._refresh_tokens.revoke_family(record.token_family)
                raise AuthenticationError("Refresh token reuse detected")
            return await self._issue_tokens(
                record.user_id,
                family=record.token_family,
                now=now,
                audience=record.client_aud,  # type: ignore[arg-type]
                meta=self._meta_for_refresh(record, meta),
                family_started_at=record.family_started_at,
            )

        if record.expires_at <= now:
            raise AuthenticationError("Refresh token expired")

        await self._refresh_tokens.mark_rotated(record.id)
        return await self._issue_tokens(
            record.user_id,
            family=record.token_family,
            now=now,
            audience=record.client_aud,  # type: ignore[arg-type]
            meta=self._meta_for_refresh(record, meta),
            family_started_at=record.family_started_at,
        )

    async def logout(self, *, refresh_token: str) -> None:
        record = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))
        if record is not None:
            await self._refresh_tokens.revoke_family(record.token_family)

    # --- sessions (device management) ---

    async def list_sessions(
        self, *, user_id: str, current_family: str | None
    ) -> list[AuthSession]:
        """List active login devices for ``user_id``, aggregated by token family."""
        tips = await self._refresh_tokens.list_active_session_tips(user_id=user_id)
        by_family: dict[str, RefreshToken] = {}
        for tip in tips:
            prev = by_family.get(tip.token_family)
            if prev is None or tip.last_used_at >= prev.last_used_at:
                by_family[tip.token_family] = tip
        sessions = [
            AuthSession(
                id=row.token_family,
                platform=row.client_platform,
                user_agent=row.user_agent,
                ip=row.ip,
                created_at=row.family_started_at,
                last_used_at=row.last_used_at,
                current=bool(current_family and row.token_family == current_family),
            )
            for row in by_family.values()
        ]
        sessions.sort(key=lambda s: s.last_used_at, reverse=True)
        return sessions

    async def revoke_session(self, *, user_id: str, family_id: str) -> None:
        """Revoke one device family. Non-owner / unknown → 404 (no existence leak)."""
        owned = await self._refresh_tokens.family_belongs_to_user(
            user_id=user_id, token_family=family_id
        )
        if not owned:
            raise NotFoundError("会话不存在")
        await self._refresh_tokens.revoke_family(family_id)
        logger.info("auth.session_revoked", user_id=user_id, family_id=family_id)

    async def revoke_other_sessions(self, *, user_id: str, current_family: str) -> None:
        """Revoke every family except the caller's current one.

        Requires a ``fam`` claim on the access token so "current" is well-defined —
        legacy tokens without ``fam`` get 422 rather than silently logging the caller
        out (revoke-all) or guessing which family to keep.
        """
        await self._refresh_tokens.revoke_other_families(
            user_id, keep_family=current_family
        )
        logger.info(
            "auth.sessions_revoke_others", user_id=user_id, keep_family=current_family
        )

    # --- invites (admin) ---

    async def create_invite(self, *, created_by: str, expires_in_days: int | None = None) -> Invite:
        """Mint a single-use invite code (deprecated; registration no longer consumes codes)."""
        invites = await self.create_invites_batch(
            created_by=created_by,
            count=1,
            expires_in_days=expires_in_days,
        )
        return invites[0]

    async def create_invites_batch(
        self,
        *,
        created_by: str,
        count: int,
        expires_in_days: int | None = None,
    ) -> Sequence[Invite]:
        """Mint multiple single-use invite codes in one transaction."""
        expires_at = (
            datetime.now(UTC) + timedelta(days=expires_in_days)
            if expires_in_days is not None
            else None
        )
        codes = [generate_invite_code() for _ in range(count)]
        return await self._invites.create_many(
            codes=codes,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def list_invites(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Invite], int]:
        offset = (page - 1) * page_size
        return await self._invites.list_page(
            offset=offset,
            limit=page_size,
            status=status,
            search=search,
            now=datetime.now(UTC),
        )

    async def invite_stats(self) -> dict[str, int]:
        return await self._invites.count_by_status(now=datetime.now(UTC))

    async def revoke_invite(self, *, invite_id: str) -> Invite:
        """Retire an unused invite (邀请码撤销; registration no longer consumes codes).

        Only a still-active code can be revoked: a used one is already consumed and an
        already-revoked one is a no-op — both raise rather than silently succeed, so the
        admin gets clear feedback. (Expired-unused codes are still revocable: it makes
        their retirement explicit instead of relying on the time check.)
        """
        invite = await self._invites.get_by_id(invite_id)
        if invite is None:
            raise NotFoundError("邀请码不存在")
        if invite.used_at is not None:
            raise ValidationError("该邀请码已被使用，无法撤销")
        if invite.revoked_at is not None:
            raise ValidationError("该邀请码已撤销")
        revoked = await self._invites.revoke(invite_id, revoked_at=datetime.now(UTC))
        if revoked is None:  # pragma: no cover - existence just validated above
            raise NotFoundError("邀请码不存在")
        return revoked

    # --- admin account ops ---

    async def admin_reset_password(self, *, user_id: str) -> str:
        """Reset an account's password to a fresh one-off, returned once for the admin
        to hand over (重置密码). Revokes the user's refresh tokens (forces re-login on
        every device) and clears any brute-force lockout. The plaintext is never stored
        — only its hash. Raises ``NotFoundError`` for an unknown account.
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        creds = await self._credentials.get_by_user_id(user_id)
        if creds is None:  # pragma: no cover - an account always has credentials
            raise NotFoundError("用户凭据不存在")

        temp_password = generate_temp_password()
        await self._credentials.set_password(
            user_id, hash_password(temp_password), must_change=True
        )
        # Force re-login everywhere: the old sessions must not outlive the reset.
        await self._refresh_tokens.revoke_all_for_user(user_id)
        return temp_password

    async def admin_set_password(
        self, *, user_id: str, new_password: str, force_change: bool = True
    ) -> None:
        """Set an account's password to an admin-chosen value (设置密码).

        Revokes the user's refresh tokens (forces re-login on every device) and
        clears any brute-force lockout. The plaintext is never stored — only its
        hash. Raises ``NotFoundError`` for an unknown account, ``ValidationError``
        if the password is too short.
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        creds = await self._credentials.get_by_user_id(user_id)
        if creds is None:  # pragma: no cover - an account always has credentials
            raise NotFoundError("用户凭据不存在")
        if len(new_password) < _MIN_PASSWORD_LENGTH:
            raise ValidationError(f"密码至少需要 {_MIN_PASSWORD_LENGTH} 个字符")
        await self._credentials.set_password(
            user_id, hash_password(new_password), must_change=force_change
        )
        await self._refresh_tokens.revoke_all_for_user(user_id)

    async def admin_delete_account(self, *, actor_id: str, user_id: str) -> tuple[User, str | None]:
        """Admin-initiated 注销 (account deletion): soft-delete + anonymize the target
        and revoke its sessions — no password (the admin role gate + the client's
        二次确认 prove intent, and the operator can't know the target's password).

        Refuses self-deletion (``不能注销自己的账户``): the no-self-lockout guard that,
        with accounts never hard-deleted, keeps the platform at ≥1 active admin (the
        same invariant as ``AdminService.update_user``). Idempotent for an already-注销
        account (returns it untouched, no re-revoke). Returns ``(tombstone_record,
        pre-deletion avatar_key)`` so the route can GC the avatar object *after*
        anonymization has nulled the key. Cross-domain cleanup (conversations / shares
        / BYOK) is the route's, via the shared ``cleanup_account_resources``. Raises
        ``NotFoundError`` for an unknown account.
        """
        if actor_id == user_id:
            raise ValidationError("不能注销自己的账户")
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        if user.deleted_at is not None:
            return user, None
        avatar_key = user.avatar_key
        updated = await self._users.soft_delete(user_id)
        await self._refresh_tokens.revoke_all_for_user(user_id)
        return (updated or user), avatar_key

    async def password_must_change(self, *, user_id: str) -> bool:
        """Whether the account must set a new password before normal use."""
        creds = await self._credentials.get_by_user_id(user_id)
        return bool(creds and creds.password_must_change)

    # --- self-service account ops (账户设置: 改密码 / 改资料 / 注销) ---

    async def change_password(
        self, *, user_id: str, current_password: str, new_password: str
    ) -> TokenPair:
        """Change a logged-in user's password (修改密码), verifying the current one.

        Confirms the current password before rotating to the new one, enforces the same
        minimum length as registration, then revokes every refresh family (all other
        devices must re-login) and mints a fresh pair for the current session so the
        active device stays signed in. Raises ``AuthenticationError`` if the current
        password is wrong, ``ValidationError`` if the new password is too weak/unchanged.
        """
        creds = await self._credentials.get_by_user_id(user_id)
        if creds is None or not verify_password(current_password, creds.password_hash):
            raise AuthenticationError("当前密码不正确")
        if len(new_password) < _MIN_PASSWORD_LENGTH:
            raise ValidationError(f"密码至少需要 {_MIN_PASSWORD_LENGTH} 个字符")
        if verify_password(new_password, creds.password_hash):
            raise ValidationError("新密码不能与当前密码相同")
        await self._credentials.set_password(
            user_id, hash_password(new_password), must_change=False
        )
        await self._refresh_tokens.revoke_all_for_user(user_id)
        return await self._issue_tokens(user_id, family=new_id(), now=datetime.now(UTC))

    async def update_profile(
        self,
        *,
        user_id: str,
        display_name: str | object = _UNSET,
        email: str | None | object = _UNSET,
    ) -> User:
        """Update a user's profile (个人资料编辑: 显示名 / 邮箱), returning the new row.

        Patch semantics — only the passed fields change. Display name must be
        non-empty; email must be unique (a collision with another live account → 422),
        and an explicit ``None``/blank clears it. Raises ``NotFoundError`` for an
        unknown user, ``ValidationError`` on an empty display name or a taken email.
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")

        changed: dict[str, object | None] = {}
        if display_name is not _UNSET:
            name = display_name.strip() if isinstance(display_name, str) else ""
            if not name:
                raise ValidationError("显示名不能为空")
            changed["display_name"] = name
        if email is not _UNSET:
            normalized = email.strip() if isinstance(email, str) else ""
            if not normalized:
                changed["email"] = None
            else:
                existing = await self._users.get_by_email(normalized)
                if existing is not None and existing.user_id != user_id:
                    raise ValidationError("该邮箱已被占用")
                changed["email"] = normalized

        if not changed:
            return user
        updated = await self._users.update(user_id, **changed)
        return updated or user

    async def delete_account(self, *, user_id: str, password: str) -> None:
        """Self-service account deletion (注销账户): verify password, then soft-delete.

        Confirms the password — a destructive, irreversible action must prove intent —
        then soft-deletes + anonymizes the account (frees username/email, disables it)
        and revokes all refresh families. Cross-domain cleanup (the user's conversations
        + BYOK key) is the route's job, since those repos live outside the auth domain.
        Raises ``NotFoundError`` for an unknown user, ``AuthenticationError`` if the
        password is wrong.
        """
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        creds = await self._credentials.get_by_user_id(user_id)
        if creds is None or not verify_password(password, creds.password_hash):
            raise AuthenticationError("密码不正确")
        await self._users.soft_delete(user_id)
        await self._refresh_tokens.revoke_all_for_user(user_id)

    # --- internals ---

    async def _issue_tokens(
        self,
        user_id: str,
        *,
        family: str,
        now: datetime,
        audience: TokenAudience = "product",
        meta: SessionMeta | None = None,
        family_started_at: datetime | None = None,
    ) -> TokenPair:
        raw, token_hash = generate_refresh_token()
        expires_at = now + timedelta(days=settings.jwt_refresh_token_expire_days)
        platform = meta.platform if meta else None
        await self._refresh_tokens.create(
            user_id=user_id,
            token_hash=token_hash,
            token_family=family,
            expires_at=expires_at,
            client_aud=audience,
            client_platform=platform,
            user_agent=_truncate_ua(meta.user_agent if meta else None),
            ip=meta.ip if meta else None,
            family_started_at=family_started_at or now,
            last_used_at=now,
        )
        return TokenPair(
            access_token=create_access_token(
                user_id, audience=audience, family=family
            ),
            refresh_token=raw,
        )

    def _meta_for_refresh(
        self, record: RefreshToken, request_meta: SessionMeta | None
    ) -> SessionMeta:
        """Inherit platform from the family; refresh IP/UA from the current request
        when provided so the session list reflects latest activity location."""
        raw_platform = record.client_platform
        platform: ClientPlatform | None = (
            raw_platform if raw_platform in ("desktop", "mobile", "admin") else None  # type: ignore[assignment]
        )
        if request_meta is None:
            return SessionMeta(
                platform=platform,
                user_agent=record.user_agent,
                ip=record.ip,
            )
        return SessionMeta(
            platform=platform,
            user_agent=request_meta.user_agent or record.user_agent,
            ip=request_meta.ip or record.ip,
        )

    def _assert_family_within_max(self, record: RefreshToken, *, now: datetime) -> None:
        started = record.family_started_at
        if record.client_aud == "admin":
            max_age = timedelta(hours=settings.admin_refresh_family_max_hours)
        else:
            max_age = timedelta(days=settings.refresh_family_max_days)
        if now - started > max_age:
            raise AuthenticationError("Refresh token family expired")

    async def _register_failure(self, user_id: str, current_attempts: int, now: datetime) -> None:
        new_attempts = current_attempts + 1
        locked_until = now + _LOCKOUT_DURATION if new_attempts >= _MAX_FAILED_ATTEMPTS else None
        await self._credentials.set_failure_state(
            user_id, failed_attempts=new_attempts, locked_until=locked_until
        )

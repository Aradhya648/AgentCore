"""Auth / account-security data access: credentials, BYOK keys, refresh tokens,
invites."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.config import settings
from agentcore.core.types import new_id
from agentcore.db.models import Credentials, Invite, RefreshToken, UserLlmProvider
from agentcore.db.repositories._base import _UNSET, _ilike_pattern, commit_or_flush
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH


def _invite_status_clause(status: str, *, now: datetime):
    """SQL filter mirroring ``_invite_status`` in api/routes/auth.py."""
    if status == "used":
        return Invite.used_at.isnot(None)
    if status == "revoked":
        return and_(Invite.used_at.is_(None), Invite.revoked_at.isnot(None))
    if status == "expired":
        return and_(
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at.isnot(None),
            Invite.expires_at <= now,
        )
    if status == "active":
        return and_(
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
            or_(Invite.expires_at.is_(None), Invite.expires_at > now),
        )
    raise ValueError(f"unknown invite status filter: {status}")


class CredentialsRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, *, user_id: str, password_hash: str, commit: bool = True
    ) -> Credentials:
        cred = Credentials(user_id=user_id, password_hash=password_hash)
        self._session.add(cred)
        await commit_or_flush(self._session, commit=commit)
        await self._session.refresh(cred)
        return cred

    async def get_by_user_id(self, user_id: str) -> Credentials | None:
        result = await self._session.execute(
            select(Credentials).where(Credentials.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def increment_failure(
        self,
        user_id: str,
        *,
        max_attempts: int,
        lock_until: datetime,
    ) -> int:
        """Atomically bump ``failed_attempts`` and lock when threshold reached.

        Uses ``failed_attempts = failed_attempts + 1`` so concurrent wrong-password
        logins cannot lose increments via read-modify-write. Returns the new count.
        Exception (P1-8): immediate commit — lockout must survive a later handler
        failure; do not mix with other writes on this session.
        """
        new_attempts = Credentials.failed_attempts + 1
        result = await self._session.execute(
            update(Credentials)
            .where(Credentials.user_id == user_id)
            .values(
                failed_attempts=new_attempts,
                locked_until=case(
                    (new_attempts >= max_attempts, lock_until),
                    else_=None,
                ),
            )
            .returning(Credentials.failed_attempts)
        )
        await self._session.commit()
        return int(result.scalar_one())

    async def reset_failure_state(self, user_id: str) -> None:
        # Exception (P1-8): clear lockout immediately on successful login.
        await self._session.execute(
            update(Credentials)
            .where(Credentials.user_id == user_id)
            .values(failed_attempts=0, locked_until=None)
        )
        await self._session.commit()

    async def set_password(
        self,
        user_id: str,
        password_hash: str,
        *,
        must_change: bool | None = None,
        commit: bool = True,
    ) -> None:
        """Replace the stored hash and clear any lockout. An admin reset both rotates
        the secret and unlocks the account (a forgotten password may have tripped the
        brute-force lock). ``must_change`` optionally sets ``password_must_change``.

        Pass ``commit=False`` when pairing with token revoke / re-issue in one txn.
        """
        values: dict = {
            "password_hash": password_hash,
            "failed_attempts": 0,
            "locked_until": None,
        }
        if must_change is not None:
            values["password_must_change"] = must_change
        await self._session.execute(
            update(Credentials).where(Credentials.user_id == user_id).values(**values)
        )
        await commit_or_flush(self._session, commit=commit)


class UserLlmProviderRepository:
    """A user's BYOK LLM providers (多服务商列表, one row per provider). Stores the
    AES-256-GCM ciphertext plus endpoint/model/price card; encryption/decryption is
    the service layer's job. Rows are owner-scoped by ``user_id``.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_for_user(self, user_id: str) -> Sequence[UserLlmProvider]:
        """All of a user's providers, oldest-first (stable list order)."""
        result = await self._session.execute(
            select(UserLlmProvider)
            .where(UserLlmProvider.user_id == user_id)
            .order_by(UserLlmProvider.created_at.asc(), UserLlmProvider.id.asc())
        )
        return result.scalars().all()

    async def get(self, provider_id: str, *, user_id: str) -> UserLlmProvider | None:
        """Owner-scoped fetch (returns None for a missing / non-owned id)."""
        result = await self._session.execute(
            select(UserLlmProvider).where(
                UserLlmProvider.id == provider_id,
                UserLlmProvider.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_unscoped(self, provider_id: str) -> UserLlmProvider | None:
        """Fetch by id without an owner check — resolution layer only (already scoped
        by the account whose pointer / conversation referenced this id)."""
        result = await self._session.execute(
            select(UserLlmProvider).where(UserLlmProvider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def first_for_user(self, user_id: str) -> UserLlmProvider | None:
        """The user's oldest provider — the fallback default when no pointer is set."""
        result = await self._session.execute(
            select(UserLlmProvider)
            .where(UserLlmProvider.user_id == user_id)
            .order_by(UserLlmProvider.created_at.asc(), UserLlmProvider.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_for_user(self, user_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(UserLlmProvider)
            .where(UserLlmProvider.user_id == user_id)
        )
        return int(result.scalar_one() or 0)

    async def create(
        self,
        *,
        user_id: str,
        label: str,
        api_key_enc: bytes,
        base_url: str | None = None,
        default_model: str | None = None,
        provider_id: str | None = None,
    ) -> UserLlmProvider:
        """Add a provider row (status 'unchecked' — not connectivity-tested yet)."""
        resolved_base_url = (base_url or settings.platform_base_url).strip().rstrip("/")
        resolved_model = (default_model or DEEPSEEK_V4_FLASH).strip()
        row = UserLlmProvider(
            id=provider_id or new_id(),
            user_id=user_id,
            label=(label or "").strip(),
            api_key_enc=api_key_enc,
            base_url=resolved_base_url,
            default_model=resolved_model,
            status="unchecked",
            supports_tools=None,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def update(
        self,
        provider_id: str,
        *,
        user_id: str,
        label: str | object = _UNSET,
        api_key_enc: bytes | object = _UNSET,
        base_url: str | object = _UNSET,
        default_model: str | object = _UNSET,
    ) -> UserLlmProvider | None:
        """Owner-scoped patch of a provider; changing the key/endpoint/model resets the
        connectivity status to 'unchecked'. Returns None for a missing / non-owned id.
        """
        row = await self.get(provider_id, user_id=user_id)
        if row is None:
            return None
        reset_status = False
        if label is not _UNSET:
            row.label = str(label or "").strip()
        if api_key_enc is not _UNSET:
            row.api_key_enc = api_key_enc  # type: ignore[assignment]
            reset_status = True
        if base_url is not _UNSET:
            row.base_url = str(base_url or settings.platform_base_url).strip().rstrip("/")
            reset_status = True
        if default_model is not _UNSET:
            row.default_model = str(default_model or DEEPSEEK_V4_FLASH).strip()
            reset_status = True
        if reset_status:
            row.status = "unchecked"
            row.supports_tools = None
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def update_status(self, provider_id: str, status: str) -> None:
        await self._session.execute(
            update(UserLlmProvider)
            .where(UserLlmProvider.id == provider_id)
            .values(status=status)
        )
        await self._session.commit()

    async def update_supports_tools(self, provider_id: str, supports_tools: bool | None) -> None:
        await self._session.execute(
            update(UserLlmProvider)
            .where(UserLlmProvider.id == provider_id)
            .values(supports_tools=supports_tools)
        )
        await self._session.commit()

    async def delete(self, provider_id: str, *, user_id: str) -> bool:
        """Owner-scoped delete; returns True when a row was removed."""
        result = await self._session.execute(
            delete(UserLlmProvider).where(
                UserLlmProvider.id == provider_id,
                UserLlmProvider.user_id == user_id,
            )
        )
        await self._session.commit()
        return bool(int(getattr(result, "rowcount", 0) or 0))

    async def delete_all_for_user(self, user_id: str) -> None:
        """Drop every provider for an account (注销 cascade)."""
        await self._session.execute(
            delete(UserLlmProvider).where(UserLlmProvider.user_id == user_id)
        )
        await self._session.commit()


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        token_family: str,
        expires_at: datetime,
        client_aud: str = "product",
        client_platform: str | None = None,
        user_agent: str | None = None,
        ip: str | None = None,
        family_started_at: datetime | None = None,
        last_used_at: datetime | None = None,
        commit: bool = True,
    ) -> RefreshToken:
        now = datetime.now(UTC)
        token = RefreshToken(
            id=new_id(),
            user_id=user_id,
            token_hash=token_hash,
            token_family=token_family,
            expires_at=expires_at,
            client_aud=client_aud,
            client_platform=client_platform,
            user_agent=user_agent,
            ip=ip,
            family_started_at=family_started_at or now,
            last_used_at=last_used_at or now,
        )
        self._session.add(token)
        await commit_or_flush(self._session, commit=commit)
        await self._session.refresh(token)
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def mark_rotated(self, token_id: str, *, commit: bool = True) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(rotated_at=datetime.now(UTC))
        )
        await commit_or_flush(self._session, commit=commit)

    async def revoke_family(self, token_family: str) -> None:
        # Exception (P1-8): security revoke — persist immediately on reuse / logout.
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_family == token_family,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.commit()

    async def revoke_all_for_user(self, user_id: str, *, commit: bool = True) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await commit_or_flush(self._session, commit=commit)

    async def revoke_other_families(self, user_id: str, *, keep_family: str) -> int:
        """Revoke every non-revoked row for ``user_id`` whose family ≠ ``keep_family``.

        Returns the number of families touched (approximate via distinct families
        among updated rows is unnecessary for callers — we return rows updated).
        """
        result = await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_family != keep_family,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def family_belongs_to_user(self, *, user_id: str, token_family: str) -> bool:
        result = await self._session.execute(
            select(RefreshToken.id)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.token_family == token_family,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_active_session_tips(
        self, *, user_id: str, now: datetime | None = None
    ) -> Sequence[RefreshToken]:
        """Return the live tip row(s) per family for ``user_id``.

        A tip is unrotated, unrevoked, and unexpired. Concurrent refresh grace can
        briefly leave multiple tips in one family — callers should aggregate.
        """
        now = now or datetime.now(UTC)
        result = await self._session.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.rotated_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.last_used_at.desc())
        )
        return result.scalars().all()

    async def delete_terminal_stale(self, *, before: datetime, limit: int) -> int:
        """Hard-delete terminal rows whose terminal timestamp is older than ``before``.

        Terminal = revoked / rotated / expired. Active family tips (unrotated,
        unrevoked, unexpired) never match. Retention of recent rotated rows keeps
        reuse detection working for the grace + post-grace window.
        """
        ids_result = await self._session.execute(
            select(RefreshToken.id)
            .where(
                or_(
                    and_(
                        RefreshToken.revoked_at.is_not(None),
                        RefreshToken.revoked_at < before,
                    ),
                    and_(
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.rotated_at.is_not(None),
                        RefreshToken.rotated_at < before,
                    ),
                    and_(
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.rotated_at.is_(None),
                        RefreshToken.expires_at < before,
                    ),
                )
            )
            .limit(limit)
        )
        ids = list(ids_result.scalars().all())
        if not ids:
            return 0
        result = await self._session.execute(
            delete(RefreshToken).where(RefreshToken.id.in_(ids))
        )
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)


class InviteRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        code: str,
        created_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> Invite:
        invite = Invite(
            id=new_id(),
            code=code,
            created_by=created_by,
            expires_at=expires_at,
        )
        self._session.add(invite)
        await self._session.commit()
        await self._session.refresh(invite)
        return invite

    async def create_many(
        self,
        *,
        codes: list[str],
        created_by: str | None = None,
        expires_at: datetime | None = None,
    ) -> Sequence[Invite]:
        invites = [
            Invite(
                id=new_id(),
                code=code,
                created_by=created_by,
                expires_at=expires_at,
            )
            for code in codes
        ]
        self._session.add_all(invites)
        await self._session.commit()
        for invite in invites:
            await self._session.refresh(invite)
        return invites

    async def get_by_code(self, code: str) -> Invite | None:
        result = await self._session.execute(select(Invite).where(Invite.code == code))
        return result.scalar_one_or_none()

    async def get_by_id(self, invite_id: str) -> Invite | None:
        result = await self._session.execute(select(Invite).where(Invite.id == invite_id))
        return result.scalar_one_or_none()

    async def list_recent(self, *, limit: int = 100) -> Sequence[Invite]:
        result = await self._session.execute(
            select(Invite).order_by(Invite.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def list_page(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        search: str | None = None,
        now: datetime | None = None,
    ) -> tuple[Sequence[Invite], int]:
        now = now or datetime.now(UTC)
        filters = [_invite_status_clause(status, now=now)] if status is not None else []
        q = (search or "").strip()
        if q:
            filters.append(Invite.code.ilike(_ilike_pattern(q)))

        total_result = await self._session.execute(
            select(func.count()).select_from(Invite).where(*filters)
        )
        total = total_result.scalar_one()

        result = await self._session.execute(
            select(Invite)
            .where(*filters)
            .order_by(Invite.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def count_by_status(self, *, now: datetime | None = None) -> dict[str, int]:
        """Return mutually-exclusive status counts plus total (mirrors list filters)."""
        now = now or datetime.now(UTC)
        total = await self._session.scalar(select(func.count()).select_from(Invite))
        counts: dict[str, int] = {"total": int(total or 0)}
        for status in ("active", "used", "expired", "revoked"):
            n = await self._session.scalar(
                select(func.count())
                .select_from(Invite)
                .where(_invite_status_clause(status, now=now))
            )
            counts[status] = int(n or 0)
        return counts

    async def mark_used(self, invite_id: str, *, used_by: str) -> None:
        await self._session.execute(
            update(Invite)
            .where(Invite.id == invite_id)
            .values(used_by=used_by, used_at=datetime.now(UTC))
        )
        await self._session.commit()

    async def revoke(self, invite_id: str, *, revoked_at: datetime) -> Invite | None:
        """Stamp ``revoked_at`` and return the fresh row (ORM mutate + refresh so the
        returned object is fully populated under async expire-on-commit)."""
        invite = await self.get_by_id(invite_id)
        if invite is None:
            return None
        invite.revoked_at = revoked_at
        await self._session.commit()
        await self._session.refresh(invite)
        return invite

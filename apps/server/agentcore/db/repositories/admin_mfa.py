"""Admin MFA enrollment data access."""

import json
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import AdminMfa


class AdminMfaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_id(self, user_id: str) -> AdminMfa | None:
        result = await self._session.execute(
            select(AdminMfa).where(AdminMfa.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert_pending(
        self,
        *,
        user_id: str,
        totp_secret_enc: bytes,
    ) -> AdminMfa:
        row = await self.get_by_user_id(user_id)
        if row is None:
            row = AdminMfa(user_id=user_id, totp_secret_enc=totp_secret_enc)
            self._session.add(row)
        else:
            row.totp_secret_enc = totp_secret_enc
            row.enabled_at = None
            row.recovery_codes_hash = None
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def enable(
        self,
        user_id: str,
        *,
        recovery_codes_hash: list[str],
    ) -> AdminMfa | None:
        row = await self.get_by_user_id(user_id)
        if row is None:
            return None
        row.enabled_at = datetime.now(UTC)
        row.recovery_codes_hash = json.dumps(recovery_codes_hash)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def consume_recovery_code(self, user_id: str, code_hash: str) -> bool:
        row = await self.get_by_user_id(user_id)
        if row is None or not row.recovery_codes_hash:
            return False
        hashes: list[str] = json.loads(row.recovery_codes_hash)
        if code_hash not in hashes:
            return False
        hashes.remove(code_hash)
        await self._session.execute(
            update(AdminMfa)
            .where(AdminMfa.user_id == user_id)
            .values(recovery_codes_hash=json.dumps(hashes))
        )
        await self._session.commit()
        return True

    async def delete_for_user(self, user_id: str) -> None:
        row = await self.get_by_user_id(user_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.commit()

"""Admin TOTP MFA secrets and recovery codes."""

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base


class AdminMfa(Base):
    """Per-admin TOTP enrollment. Only ``role=admin`` users may have a row."""

    __tablename__ = "admin_mfa"

    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True)
    # AES-256-GCM ciphertext of the base32 TOTP secret (KeyEncryptor).
    totp_secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    # Set once the admin confirms the first valid code during enrollment.
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # JSON array of SHA-256 hashes of one-time recovery codes (never plaintext).
    recovery_codes_hash: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )

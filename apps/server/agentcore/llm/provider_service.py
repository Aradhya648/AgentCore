"""BYOK LLM provider configuration service (the write + admin surface).

The read path (resolve a turn's credentials, never raises) lives in ``llm/resolve.py``.
This module is its WRITE counterpart for 设置·模型配置 over a LIST of providers: add /
edit / remove / connectivity-test each OpenAI-compatible endpoint. Account model
selection uses ``llm/model_profiles.py`` (模型组合) — not per-slot pointers here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import (
    platform_catalog_visible,
)
from agentcore.config import settings
from agentcore.core.errors import (
    BYOKKeyMissingError,
    KeyStorageUnavailableError,
    LLMError,
    NotFoundError,
    ValidationError,
)
from agentcore.core.logging import get_logger
from agentcore.db.models import UserLlmProvider
from agentcore.db.repositories import (
    LlmModelProfileRepository,
    UserLlmProviderRepository,
    UserRepository,
)
from agentcore.llm.factory import build_provider
from agentcore.llm.model_profiles import ProfileSlot
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.resolve import resolve_provider_credentials
from agentcore.security.keys import KeyEncryptor

logger = get_logger(__name__)


@dataclass(frozen=True)
class LlmProviderView:
    """Settings view of one BYOK provider — never the plaintext key."""

    id: str
    label: str
    base_url: str
    default_model: str
    status: str
    masked_key: str | None = None
    supports_tools: bool | None = None
    message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LlmProvidersView:
    """Provider list + deployment caps (+ account default profile id)."""

    providers: list[LlmProviderView] = field(default_factory=list)
    default_model_profile_id: str | None = None
    billing_mode: str = "byok"
    platform_available: bool = False
    platform_model: str | None = None


def _mask_key_ciphertext(enc: KeyEncryptor | None, api_key_enc: bytes) -> str | None:
    if enc is None or not api_key_enc:
        return None
    try:
        plaintext = enc.decrypt(api_key_enc).decode()
    except Exception:  # noqa: BLE001
        return None
    return _mask_key(plaintext)


def _mask_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"


class LlmProviderService:
    """Add / edit / remove / connectivity-test a user's BYOK providers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = UserLlmProviderRepository(session)
        self._users = UserRepository(session)
        self._profiles = LlmModelProfileRepository(session)

    def _encryptor(self) -> KeyEncryptor | None:
        if not settings.encryption_key:
            return None
        try:
            return KeyEncryptor(settings.encryption_key)
        except ValueError:
            logger.error("byok.key_malformed")
            return None

    def _view(
        self,
        row: UserLlmProvider,
        *,
        enc: KeyEncryptor | None,
        message: str | None = None,
    ) -> LlmProviderView:
        return LlmProviderView(
            id=row.id,
            label=row.label or "",
            base_url=row.base_url,
            default_model=row.default_model,
            status=row.status,
            masked_key=_mask_key_ciphertext(enc, row.api_key_enc),
            supports_tools=row.supports_tools,
            message=message,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_providers(self, user_id: str) -> LlmProvidersView:
        enc = self._encryptor()
        user = await self._users.get_by_id(user_id)
        rows = await self._repo.list_for_user(user_id)
        providers = [self._view(row, enc=enc) for row in rows]
        platform_available = platform_catalog_visible()
        return LlmProvidersView(
            providers=providers,
            default_model_profile_id=(
                getattr(user, "default_model_profile_id", None) if user else None
            ),
            billing_mode=settings.billing_mode,
            platform_available=platform_available,
            platform_model=settings.platform_model if platform_available else None,
        )

    async def create_provider(
        self,
        user_id: str,
        *,
        label: str,
        api_key: str,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> LlmProviderView:
        """Add a provider. First provider auto-creates a「当前配置」profile as default."""
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValidationError("API Key 不能为空")
        from agentcore.llm.credentials import require_http_header_safe_api_key

        api_key = require_http_header_safe_api_key(api_key)
        enc = self._encryptor()
        if enc is None:
            raise KeyStorageUnavailableError(
                "服务端未配置加密主密钥，暂时无法保存 API Key，请联系管理员"
            )
        resolved_base_url = (base_url or settings.platform_base_url).strip()
        if not resolved_base_url:
            raise ValidationError("Base URL 不能为空")
        resolved_model = (default_model or DEEPSEEK_V4_FLASH).strip()
        if not resolved_model:
            raise ValidationError("模型名称不能为空")

        was_empty = (await self._repo.count_for_user(user_id)) == 0
        row = await self._repo.create(
            user_id=user_id,
            label=label,
            api_key_enc=enc.encrypt(api_key.encode()),
            base_url=resolved_base_url,
            default_model=resolved_model,
        )
        if was_empty:
            from agentcore.llm.model_profiles import LlmModelProfileService

            await LlmModelProfileService(self._session).create_profile(
                user_id,
                name="当前配置",
                main=ProfileSlot(
                    origin="byok", model=row.default_model, provider_id=row.id
                ),
                set_as_default=True,
            )
        return self._view(row, enc=enc)

    async def update_provider(
        self,
        user_id: str,
        provider_id: str,
        *,
        label: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        fields_set: set[str],
    ) -> LlmProviderView:
        existing = await self._repo.get(provider_id, user_id=user_id)
        if existing is None:
            raise NotFoundError("服务商不存在")

        kwargs: dict[str, object] = {}
        if "label" in fields_set:
            kwargs["label"] = label or ""
        if "api_key" in fields_set and (api_key or "").strip():
            enc = self._encryptor()
            if enc is None:
                raise KeyStorageUnavailableError(
                    "服务端未配置加密主密钥，暂时无法保存 API Key，请联系管理员"
                )
            from agentcore.llm.credentials import require_http_header_safe_api_key

            safe_key = require_http_header_safe_api_key(api_key.strip())
            kwargs["api_key_enc"] = enc.encrypt(safe_key.encode())
        if "base_url" in fields_set:
            resolved = (base_url or settings.platform_base_url).strip()
            if not resolved:
                raise ValidationError("Base URL 不能为空")
            kwargs["base_url"] = resolved
        if "default_model" in fields_set:
            resolved_model = (default_model or "").strip()
            if not resolved_model:
                raise ValidationError("模型名称不能为空")
            kwargs["default_model"] = resolved_model

        row = await self._repo.update(provider_id, user_id=user_id, **kwargs)  # type: ignore[arg-type]
        assert row is not None
        return self._view(row, enc=self._encryptor())

    async def delete_provider(self, user_id: str, provider_id: str) -> None:
        """Remove a provider; profile slots referencing it are cleared / retargeted."""
        removed = await self._repo.delete(provider_id, user_id=user_id)
        if not removed:
            raise NotFoundError("服务商不存在")

        fallback = await self._repo.first_for_user(user_id)
        if fallback is not None:
            await self._profiles.retarget_main_provider(
                user_id,
                from_provider_id=provider_id,
                to_provider_id=fallback.id,
                to_model=fallback.default_model,
                to_origin="byok",
            )
        else:
            await self._profiles.retarget_main_provider(
                user_id,
                from_provider_id=provider_id,
                to_provider_id=None,
                to_model=DEEPSEEK_V4_FLASH,
                to_origin="platform",
            )
        await self._profiles.clear_provider_refs(user_id, provider_id)

    async def test_provider(self, user_id: str, provider_id: str) -> LlmProviderView:
        row = await self._repo.get(provider_id, user_id=user_id)
        if row is None:
            raise NotFoundError("服务商不存在")
        if not row.api_key_enc:
            raise BYOKKeyMissingError("尚未配置 API Key，无法测试连接")
        credentials = await resolve_provider_credentials(self._session, user_id, provider_id)
        enc = self._encryptor()
        if credentials is None:
            await self._repo.update_status(provider_id, "error")
            fresh = await self._repo.get(provider_id, user_id=user_id)
            assert fresh is not None
            return self._view(
                fresh,
                enc=enc,
                message="无法解密已保存的 Key（服务端密钥变更或数据损坏），请重新填写",
            )
        provider = build_provider(credentials)
        model = credentials.default_model
        base_url = credentials.base_url
        supports_tools: bool | None = None
        logger.info(
            "llm_provider.test.start",
            user_id=user_id,
            provider_id=provider_id,
            base_url=base_url,
            model=model,
            provider_type=type(provider).__name__,
        )
        try:
            await provider.probe(model=model)
            status, message = "active", None
            supports_tools = await provider.probe_tools(model=model)
        except LLMError as e:
            status, message = "error", str(e)
            logger.warning(
                "llm_provider.test.failed",
                user_id=user_id,
                provider_id=provider_id,
                base_url=base_url,
                model=model,
                error_type=type(e).__name__,
                error=str(e),
            )
        except Exception:
            logger.exception(
                "llm_provider.test.unhandled",
                user_id=user_id,
                provider_id=provider_id,
                base_url=base_url,
                model=model,
                provider_type=type(provider).__name__,
            )
            raise
        else:
            logger.info(
                "llm_provider.test.ok",
                user_id=user_id,
                provider_id=provider_id,
                base_url=base_url,
                model=model,
                supports_tools=supports_tools,
            )
        finally:
            await provider.close()
        await self._repo.update_status(provider_id, status)
        if status == "active":
            await self._repo.update_supports_tools(provider_id, supports_tools)
        fresh = await self._repo.get(provider_id, user_id=user_id)
        assert fresh is not None
        return self._view(fresh, enc=enc, message=message)

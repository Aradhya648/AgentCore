"""BYOK LLM provider configuration service (the write + admin surface).

The read path (resolve a turn's credentials, never raises) lives in ``llm/resolve.py``.
This module is its WRITE counterpart for 设置·模型配置 over a LIST of providers: add /
edit / remove / connectivity-test each OpenAI-compatible endpoint, plus set the account
default chat / background pointers. Unlike the resolver it RAISES on misconfiguration
(no master key → the key can't be stored) and surfaces probe failures, so the settings
UI gets actionable errors. Only AES-256-GCM ciphertext is ever stored for the key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import is_free_tier_active, is_platform_available
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
from agentcore.db.repositories import UserLlmProviderRepository, UserRepository
from agentcore.llm.factory import build_provider
from agentcore.llm.pricing import parse_user_prices
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
    price_cache_hit: str | None = None
    price_cache_miss: str | None = None
    price_output: str | None = None
    is_default_chat: bool = False
    is_default_background: bool = False
    # Transient connectivity-test message (only set by ``test_provider``).
    message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class LlmDefaultPointer:
    provider_id: str
    model: str


@dataclass(frozen=True)
class LlmProvidersView:
    """The full 设置·模型配置 state: the provider list + account pointers + deploy caps."""

    providers: list[LlmProviderView] = field(default_factory=list)
    default_chat: LlmDefaultPointer | None = None
    default_background: LlmDefaultPointer | None = None
    billing_mode: str = "byok"
    platform_available: bool = False
    platform_model: str | None = None
    free_tier_active: bool = False


def _mask_key_ciphertext(enc: KeyEncryptor | None, api_key_enc: bytes) -> str | None:
    """Last-4 mask of a stored key, or None when it can't be decrypted."""
    if enc is None or not api_key_enc:
        return None
    try:
        plaintext = enc.decrypt(api_key_enc).decode()
    except Exception:  # noqa: BLE001 — corrupt cipher / rotated key: still "configured"
        return None
    return _mask_key(plaintext)


def _mask_key(api_key: str) -> str:
    """Display form: last 4 chars only (e.g. ``••••cdef``); never the full key."""
    if len(api_key) <= 4:
        return "••••"
    return f"••••{api_key[-4:]}"


def _validate_price_card(
    price_cache_hit: str | None,
    price_cache_miss: str | None,
    price_output: str | None,
) -> None:
    """Enforce the price-card shape (input + output required, or all blank)."""
    price_fields = (price_cache_hit, price_cache_miss, price_output)
    has_core = all(p and str(p).strip() for p in (price_cache_miss, price_output))
    if any(price_fields) and not has_core:
        raise ValidationError("单价须至少填写输入与输出两项（缓存命中价可选），或全部留空")
    if has_core and parse_user_prices(
        cache_hit=price_cache_hit, cache_miss=price_cache_miss, output=price_output
    ) is None:
        raise ValidationError("单价须为非负十进制数字（USD per 1M tokens）")


class LlmProviderService:
    """Add / edit / remove / connectivity-test a user's BYOK providers + set defaults."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = UserLlmProviderRepository(session)
        self._users = UserRepository(session)

    def _encryptor(self) -> KeyEncryptor | None:
        """The configured AES encryptor, or ``None`` when the master key is missing or
        malformed — fail-safe: a server that can't encrypt won't store a key."""
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
        user,
        message: str | None = None,
    ) -> LlmProviderView:
        chat_id = getattr(user, "default_chat_provider_id", None) if user else None
        bg_id = getattr(user, "default_background_provider_id", None) if user else None
        return LlmProviderView(
            id=row.id,
            label=row.label or "",
            base_url=row.base_url,
            default_model=row.default_model,
            status=row.status,
            masked_key=_mask_key_ciphertext(enc, row.api_key_enc),
            supports_tools=row.supports_tools,
            price_cache_hit=row.price_cache_hit,
            price_cache_miss=row.price_cache_miss,
            price_output=row.price_output,
            is_default_chat=chat_id == row.id,
            is_default_background=bg_id == row.id,
            message=message,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_providers(self, user_id: str) -> LlmProvidersView:
        """The full settings state: all providers + account pointers + deployment caps."""
        enc = self._encryptor()
        user = await self._users.get_by_id(user_id)
        rows = await self._repo.list_for_user(user_id)
        providers = [self._view(row, enc=enc, user=user) for row in rows]

        platform_available = is_platform_available()
        free_tier = is_free_tier_active(has_user_key=len(rows) > 0)

        def _pointer(provider_id: str | None, model: str | None) -> LlmDefaultPointer | None:
            if not provider_id or not any(r.id == provider_id for r in rows):
                return None
            return LlmDefaultPointer(
                provider_id=provider_id, model=(model or "").strip() or ""
            )

        return LlmProvidersView(
            providers=providers,
            default_chat=_pointer(
                getattr(user, "default_chat_provider_id", None),
                getattr(user, "default_chat_model", None),
            ),
            default_background=_pointer(
                getattr(user, "default_background_provider_id", None),
                getattr(user, "default_background_model", None),
            ),
            billing_mode=settings.billing_mode,
            platform_available=platform_available,
            platform_model=settings.platform_model if platform_available else None,
            free_tier_active=free_tier,
        )

    async def create_provider(
        self,
        user_id: str,
        *,
        label: str,
        api_key: str,
        base_url: str | None = None,
        default_model: str | None = None,
        price_cache_hit: str | None = None,
        price_cache_miss: str | None = None,
        price_output: str | None = None,
    ) -> LlmProviderView:
        """Add a provider (key encrypted at rest). The first provider becomes the
        account chat default automatically so a single-provider user needs no extra step.
        """
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValidationError("API Key 不能为空")
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
        _validate_price_card(price_cache_hit, price_cache_miss, price_output)

        was_empty = (await self._repo.count_for_user(user_id)) == 0
        row = await self._repo.create(
            user_id=user_id,
            label=label,
            api_key_enc=enc.encrypt(api_key.encode()),
            base_url=resolved_base_url,
            default_model=resolved_model,
            price_cache_hit=(price_cache_hit.strip() if price_cache_hit else None),
            price_cache_miss=(price_cache_miss.strip() if price_cache_miss else None),
            price_output=(price_output.strip() if price_output else None),
        )
        if was_empty:
            await self._users.set_llm_defaults(
                user_id, chat_provider_id=row.id, chat_model=row.default_model
            )
        user = await self._users.get_by_id(user_id)
        return self._view(row, enc=enc, user=user)

    async def update_provider(
        self,
        user_id: str,
        provider_id: str,
        *,
        label: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        price_cache_hit: str | None = None,
        price_cache_miss: str | None = None,
        price_output: str | None = None,
        fields_set: set[str],
    ) -> LlmProviderView:
        """Patch a provider — only the fields the caller sent (``fields_set``).

        An omitted ``api_key`` keeps the stored ciphertext (edit endpoint/model without
        re-entering the key). Editing key/endpoint/model resets connectivity status.
        """
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
            kwargs["api_key_enc"] = enc.encrypt(api_key.strip().encode())
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
        price_touched = {"price_cache_hit", "price_cache_miss", "price_output"} & fields_set
        if price_touched:
            _validate_price_card(price_cache_hit, price_cache_miss, price_output)
            kwargs["price_cache_hit"] = (
                price_cache_hit.strip() if price_cache_hit else None
            )
            kwargs["price_cache_miss"] = (
                price_cache_miss.strip() if price_cache_miss else None
            )
            kwargs["price_output"] = price_output.strip() if price_output else None

        row = await self._repo.update(provider_id, user_id=user_id, **kwargs)  # type: ignore[arg-type]
        assert row is not None  # existence checked above
        user = await self._users.get_by_id(user_id)
        return self._view(row, enc=self._encryptor(), user=user)

    async def delete_provider(self, user_id: str, provider_id: str) -> None:
        """Remove a provider; account pointers referencing it fall back to another
        provider (chat) or clear (background). Conversation overrides degrade lazily at
        resolve time (never a hard failure)."""
        removed = await self._repo.delete(provider_id, user_id=user_id)
        if not removed:
            raise NotFoundError("服务商不存在")
        user = await self._users.get_by_id(user_id)
        if user is None:
            return
        chat_patch: dict[str, object | None] = {}
        if getattr(user, "default_chat_provider_id", None) == provider_id:
            fallback = await self._repo.first_for_user(user_id)
            if fallback is not None:
                chat_patch = {
                    "chat_provider_id": fallback.id,
                    "chat_model": fallback.default_model,
                }
            else:
                chat_patch = {"chat_provider_id": None, "chat_model": None}
        if getattr(user, "default_background_provider_id", None) == provider_id:
            chat_patch["background_provider_id"] = None
            chat_patch["background_model"] = None
        if chat_patch:
            await self._users.set_llm_defaults(user_id, **chat_patch)  # type: ignore[arg-type]

    async def test_provider(self, user_id: str, provider_id: str) -> LlmProviderView:
        """Probe one provider's endpoint and persist connectivity + tool support."""
        row = await self._repo.get(provider_id, user_id=user_id)
        if row is None:
            raise NotFoundError("服务商不存在")
        if not row.api_key_enc:
            raise BYOKKeyMissingError("尚未配置 API Key，无法测试连接")
        credentials = await resolve_provider_credentials(self._session, user_id, provider_id)
        enc = self._encryptor()
        user = await self._users.get_by_id(user_id)
        if credentials is None:
            await self._repo.update_status(provider_id, "error")
            fresh = await self._repo.get(provider_id, user_id=user_id)
            assert fresh is not None
            return self._view(
                fresh,
                enc=enc,
                user=user,
                message="无法解密已保存的 Key（服务端密钥变更或数据损坏），请重新填写",
            )
        provider = build_provider(credentials)
        model = credentials.default_model
        supports_tools: bool | None = None
        try:
            await provider.probe(model=model)
            status, message = "active", None
            supports_tools = await provider.probe_tools(model=model)
        except LLMError as e:
            status, message = "error", str(e)
        finally:
            await provider.close()
        await self._repo.update_status(provider_id, status)
        if status == "active":
            await self._repo.update_supports_tools(provider_id, supports_tools)
        fresh = await self._repo.get(provider_id, user_id=user_id)
        assert fresh is not None
        return self._view(fresh, enc=enc, user=user, message=message)

    async def set_defaults(
        self,
        user_id: str,
        *,
        chat: LlmDefaultPointer | None,
        background: LlmDefaultPointer | None,
        set_chat: bool,
        set_background: bool,
    ) -> LlmProvidersView:
        """Set the account chat / background default pointers (each a provider+model).

        A pointer's provider must belong to the user; ``background`` may be cleared
        (``set_background`` with ``background=None``). Cross-provider is allowed.
        """
        patch: dict[str, object | None] = {}
        if set_chat:
            if chat is None:
                raise ValidationError("chat 默认必须指定服务商与模型")
            await self._require_owned(user_id, chat)
            patch["chat_provider_id"] = chat.provider_id
            patch["chat_model"] = chat.model
        if set_background:
            if background is None:
                patch["background_provider_id"] = None
                patch["background_model"] = None
            else:
                await self._require_owned(user_id, background)
                patch["background_provider_id"] = background.provider_id
                patch["background_model"] = background.model
        if patch:
            await self._users.set_llm_defaults(user_id, **patch)  # type: ignore[arg-type]
        return await self.list_providers(user_id)

    async def _require_owned(self, user_id: str, pointer: LlmDefaultPointer) -> None:
        if not (pointer.model or "").strip():
            raise ValidationError("默认模型不能为空")
        row = await self._repo.get(pointer.provider_id, user_id=user_id)
        if row is None:
            raise ValidationError("所选服务商不存在")

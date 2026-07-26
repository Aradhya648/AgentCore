"""Platform leaf — resolve upstream credentials per ``request.model``.

运营中转「一 key 一模型」(``PLATFORM_MODEL_CREDENTIALS``) 要求同一 ``platform/``
路由前缀下，不同 model id 使用不同 api_key。冻结单 key 的
``OpenAICompatibleProvider`` 无法表达这一点；本 leaf 在每次调用时经
``platform_llm_credentials(model=…)`` 取对 key，并按 (api_key, base_url) 缓存
底层 HTTP 客户端。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agentcore.core.errors import LLMError
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import LLMChunk, LLMRequest, LLMResponse

_LeafKey = tuple[str, str]  # (api_key, base_url)


class PlatformProvider:
    """Router leaf for ``PLATFORM_PROVIDER_SENTINEL`` — credentials follow the model."""

    def __init__(self) -> None:
        self._leaves: dict[_LeafKey, OpenAICompatibleProvider] = {}

    @property
    def name(self) -> str:
        return "platform"

    def clone(self) -> PlatformProvider:
        """Independent leaf cache (coordination drive ownership)."""
        return PlatformProvider()

    async def close(self) -> None:
        for leaf in self._leaves.values():
            await leaf.close()
        self._leaves.clear()

    def _leaf_for(self, model: str) -> OpenAICompatibleProvider:
        # Lazy import: provider package init must not pull resolve → credentials → profiles.
        from agentcore.llm.resolve import platform_llm_credentials

        mid = (model or "").strip()
        creds = platform_llm_credentials(model=mid or None)
        if creds is None:
            label = mid or "(empty)"
            raise LLMError(
                f"platform 模型 {label} 无可用凭据，"
                "请检查 PLATFORM_API_KEY / PLATFORM_MODEL_CREDENTIALS"
            )
        key: _LeafKey = (creds.api_key, creds.base_url)
        leaf = self._leaves.get(key)
        if leaf is None:
            leaf = OpenAICompatibleProvider(
                name="platform",
                api_key=creds.api_key,
                base_url=creds.base_url,
                extra_headers=creds.extra_headers,
            )
            self._leaves[key] = leaf
        return leaf

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self._leaf_for(request.model).complete(request)

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        return self._leaf_for(request.model).stream(request)

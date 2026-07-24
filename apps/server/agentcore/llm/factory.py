"""LLM provider assembly."""

from __future__ import annotations

from agentcore.config import settings
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import LLMProvider
from agentcore.llm.provider.router import ProviderRouter
from agentcore.llm.resolve import ProviderPurpose, platform_llm_credentials

_VENDOR_PROVIDERS: dict[str, tuple[str, str]] = {
    "kimi": ("moonshot_api_key", "moonshot_base_url"),
    "zhipu": ("zhipu_api_key", "zhipu_base_url"),
    "doubao": ("doubao_api_key", "doubao_base_url"),
}


def build_provider(
    credentials: LLMCredentials | None = None,
    *,
    purpose: ProviderPurpose = "user_facing",
) -> OpenAICompatibleProvider:
    """Build an upstream provider from resolved credentials.

    ``purpose`` is retained for call-site clarity; credentials are authoritative.
    D6: background callers resolve user-key-first via ``resolve_credentials`` /
    ``resolve_model_config`` — this factory must not override a user key with the
    platform key. Missing credentials still fall back to the platform key when
    configured (free-tier / platform-preference paths).

    Callers that need ambient call-level pricing should bind
    ``credential_source`` in log context (pipeline / proxy) from ``creds.source``.
    """
    _ = purpose  # call-site documentation only (D6: no force-platform override)
    creds = credentials
    if creds is None:
        creds = platform_llm_credentials()
    if creds is not None:
        return OpenAICompatibleProvider(
            name=creds.source,
            api_key=creds.api_key,
            base_url=creds.base_url,
            extra_headers=creds.extra_headers,
        )
    return OpenAICompatibleProvider(
        name="platform",
        api_key=settings.platform_api_key,
        base_url=settings.platform_base_url,
    )


def _vendor_extras() -> dict[str, OpenAICompatibleProvider]:
    extras: dict[str, OpenAICompatibleProvider] = {}
    for prefix, (key_attr, url_attr) in _VENDOR_PROVIDERS.items():
        api_key = getattr(settings, key_attr, "")
        if not api_key:
            continue
        extras[prefix] = OpenAICompatibleProvider(
            name=prefix,
            api_key=api_key,
            base_url=getattr(settings, url_attr),
        )
    return extras


def build_router_around(default: LLMProvider) -> ProviderRouter:
    return ProviderRouter(default=default, providers=_vendor_extras())


def build_router(
    credentials: LLMCredentials | None = None,
    *,
    purpose: ProviderPurpose = "user_facing",
) -> ProviderRouter:
    return build_router_around(build_provider(credentials, purpose=purpose))


def spawn_independent_llm(llm: LLMProvider) -> tuple[LLMProvider, bool]:
    """Spawn a client the coordination background drive owns and must close.

    Returns ``(client, owns)``. Production routers / OpenAI-compatible providers
    are cloned so turn teardown ``llm.close()`` cannot ReadError-kill workers.
    Test fakes without ``clone`` are returned as-is with ``owns=False``.
    """
    clone_fn = getattr(llm, "clone", None)
    if callable(clone_fn):
        return clone_fn(), True
    return llm, False

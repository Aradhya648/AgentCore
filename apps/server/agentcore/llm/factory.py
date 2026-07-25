"""LLM provider assembly."""

from __future__ import annotations

from agentcore.config import settings
from agentcore.llm.call_fence import observe_provider
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
) -> LLMProvider:
    """Build an upstream provider from resolved credentials.

    ``purpose`` is retained for call-site clarity; credentials are authoritative.
    Background callers resolve platform-first via ``resolve_and_gate_background`` /
    ``resolve_model_config`` — this factory must not override a resolved user-key
    fallback with the platform key. Missing credentials still fall back to the
    platform key when configured (legacy free-tier paths); prefer passing explicit
    credentials from the gate helper so quota skips are not silently re-platformed.

    Callers that need ambient call-level pricing should bind
    ``credential_source`` in log context (pipeline / proxy) from ``creds.source``.

    Every leaf is wrapped by :func:`observe_provider` so ``complete`` / ``stream``
    emit uniform ``llm.call`` / ``llm.call_failed`` (observation only — no retry).
    """
    _ = purpose  # call-site documentation only
    creds = credentials
    if creds is None:
        creds = platform_llm_credentials()
    if creds is not None:
        leaf: LLMProvider = OpenAICompatibleProvider(
            name=creds.source,
            api_key=creds.api_key,
            base_url=creds.base_url,
            extra_headers=creds.extra_headers,
        )
    else:
        leaf = OpenAICompatibleProvider(
            name="platform",
            api_key=settings.platform_api_key,
            base_url=settings.platform_base_url,
        )
    return observe_provider(leaf)


def _vendor_extras() -> dict[str, LLMProvider]:
    extras: dict[str, LLMProvider] = {}
    for prefix, (key_attr, url_attr) in _VENDOR_PROVIDERS.items():
        api_key = getattr(settings, key_attr, "")
        if not api_key:
            continue
        extras[prefix] = observe_provider(
            OpenAICompatibleProvider(
                name=prefix,
                api_key=api_key,
                base_url=getattr(settings, url_attr),
            )
        )
    return extras


def build_router_around(
    default: LLMProvider,
    *,
    extra_providers: dict[str, LLMProvider] | None = None,
) -> ProviderRouter:
    """Wrap ``default`` with vendor extras + optional BYOK extras (worker cross-provider)."""
    providers: dict[str, LLMProvider] = dict(_vendor_extras())
    if extra_providers:
        providers.update(extra_providers)
    return ProviderRouter(default=default, providers=providers)


async def build_turn_router(
    credentials: LLMCredentials | None = None,
    *,
    user_id: str | None = None,
    profiles: object | None = None,
    purpose: ProviderPurpose = "user_facing",
) -> ProviderRouter:
    """Build the turn ProviderRouter, injecting cross-provider / platform worker when needed.

    ``profiles.agent_provider_id`` (from ``resolve_turn_profiles``) that differs from the
    turn's chat credentials causes that provider to be registered under its id so
    ``TurnProfiles.route_model_for("agent")`` can dispatch with a ``provider_id/model``
    prefix. ``PLATFORM_PROVIDER_SENTINEL`` registers ``platform_llm_credentials`` for the
    worker model. Same-provider BYOK overrides need no extras.
    """
    from agentcore.db.base import async_session_factory
    from agentcore.llm.profiles import PLATFORM_PROVIDER_SENTINEL, TurnProfiles
    from agentcore.llm.resolve import platform_llm_credentials, resolve_provider_credentials

    extras: dict[str, LLMProvider] = {}
    turn_provider_id = credentials.provider_id if credentials is not None else None
    agent_provider_id = getattr(profiles, "agent_provider_id", None) if profiles else None
    if (
        isinstance(profiles, TurnProfiles)
        and agent_provider_id
        and agent_provider_id != turn_provider_id
    ):
        if agent_provider_id == PLATFORM_PROVIDER_SENTINEL:
            worker_model = profiles.model_for("agent")
            agent_creds = platform_llm_credentials(model=worker_model)
            if agent_creds is not None:
                extras[PLATFORM_PROVIDER_SENTINEL] = build_provider(
                    agent_creds, purpose=purpose
                )
        elif user_id:
            async with async_session_factory() as session:
                agent_creds = await resolve_provider_credentials(
                    session, user_id, agent_provider_id
                )
            if agent_creds is not None:
                extras[agent_provider_id] = build_provider(agent_creds, purpose=purpose)
    return build_router_around(
        build_provider(credentials, purpose=purpose),
        extra_providers=extras or None,
    )


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

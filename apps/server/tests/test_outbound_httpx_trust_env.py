"""Product outbound httpx must not inherit system SOCKS proxy env."""

from __future__ import annotations

import httpx

from agentcore.core.net import outbound_async_client
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider


def test_outbound_async_client_defaults_trust_env_false():
    client = outbound_async_client(timeout=1.0)
    assert client.trust_env is False


def test_outbound_async_client_allows_explicit_trust_env_true():
    client = outbound_async_client(timeout=1.0, trust_env=True)
    assert client.trust_env is True


def test_openai_compatible_provider_ignores_proxy_env():
    provider = OpenAICompatibleProvider(
        name="test",
        api_key="k",
        base_url="http://example.invalid/v1",
    )
    assert isinstance(provider._client, httpx.AsyncClient)
    assert provider._client.trust_env is False

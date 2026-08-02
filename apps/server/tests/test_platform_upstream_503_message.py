"""Platform leaf 5xx user-facing copy + body preview on upstream_error."""

from __future__ import annotations

import pytest

from agentcore.core.errors import LLMUpstreamError
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider


def test_platform_503_uses_upstream_capacity_copy():
    leaf = OpenAICompatibleProvider(
        name="platform", api_key="k", base_url="http://example.com/v1"
    )
    with pytest.raises(LLMUpstreamError) as ei:
        leaf._raise_for_status(
            503,
            1.0,
            {},
            body=b'{"error":{"message":"overloaded"}}',
            attempt=0,
        )
    err = ei.value
    assert "上游模型服务暂时不可用（503）" in str(err)
    assert "platform 服务端错误" not in str(err)
    assert err.details.get("upstream_status") == 503
    assert "overloaded" in (err.details.get("upstream_body_preview") or "")


def test_named_provider_503_keeps_provider_name():
    leaf = OpenAICompatibleProvider(
        name="deepseek", api_key="k", base_url="http://example.com/v1"
    )
    with pytest.raises(LLMUpstreamError) as ei:
        leaf._raise_for_status(503, 1.0, {}, body=None, attempt=0)
    assert "deepseek 服务端错误（503）" in str(ei.value)

"""Leaf call fence: structured llm.call / llm.call_failed via build_provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from agentcore.core.errors import LLMUpstreamError
from agentcore.llm.call_fence import ObservingLLMProvider, observe_provider, unwrap_provider
from agentcore.llm.factory import build_provider
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.protocol import (
    LLMChunk,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)


def _req(*, scenario: str = "chat") -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model=DEEPSEEK_V4_FLASH,
        scenario=scenario,
    )


class _FakeLeaf:
    def __init__(self) -> None:
        self.name = "platform"
        self._name = "platform"
        self.complete = AsyncMock(
            return_value=LLMResponse(
                content="ok",
                model=DEEPSEEK_V4_FLASH,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
                finish_reason="stop",
                latency_ms=12,
            )
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(delta_content="hi")
        yield LLMChunk(
            finish_reason="stop",
            usage=TokenUsage(input_tokens=2, output_tokens=3),
        )

    def clone(self) -> _FakeLeaf:
        return _FakeLeaf()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_fence_complete_success_emits_llm_call():
    leaf = _FakeLeaf()
    provider = observe_provider(leaf)
    with capture_logs() as caps:
        resp = await provider.complete(_req(scenario="title"))
    assert resp.content == "ok"
    call = next(c for c in caps if c.get("event") == "llm.call")
    assert call["scenario"] == "title"
    assert call["model"] == DEEPSEEK_V4_FLASH
    assert call["attempt"] == 1
    assert call["stream"] is False
    assert isinstance(call["latency_ms"], int)
    assert call["latency_ms"] >= 0
    assert not any(c.get("event") == "llm.call_failed" for c in caps)


@pytest.mark.asyncio
async def test_fence_complete_failure_emits_llm_call_failed():
    leaf = _FakeLeaf()
    leaf.complete = AsyncMock(
        side_effect=LLMUpstreamError("boom", upstream_status=502, retry_attempts=2)
    )
    provider = observe_provider(leaf)
    with capture_logs() as caps, pytest.raises(LLMUpstreamError):
        await provider.complete(_req())
    failed = next(c for c in caps if c.get("event") == "llm.call_failed")
    assert failed["scenario"] == "chat"
    assert failed["model"] == DEEPSEEK_V4_FLASH
    assert failed["attempt"] == 3  # 0-based retry_attempts=2 → 1-based 3
    assert failed["stream"] is False
    assert "boom" in failed["error"]
    assert "model" in failed
    assert not any(c.get("event") == "llm.call" for c in caps)


@pytest.mark.asyncio
async def test_fence_complete_failure_includes_ambient_credential_fields():
    """llm.call_failed surfaces ambient credential_source + provider_id (no base_url)."""
    from agentcore.core.log_context import bind_log_context, clear_log_context

    leaf = _FakeLeaf()
    leaf.complete = AsyncMock(
        side_effect=LLMUpstreamError("boom", upstream_status=502, retry_attempts=0)
    )
    provider = observe_provider(leaf)
    clear_log_context()
    bind_log_context(credential_source="user", provider_id="prov-1")
    try:
        with capture_logs() as caps, pytest.raises(LLMUpstreamError):
            await provider.complete(_req())
    finally:
        clear_log_context()
    failed = next(c for c in caps if c.get("event") == "llm.call_failed")
    assert failed["model"] == DEEPSEEK_V4_FLASH
    assert failed["credential_source"] == "user"
    assert failed["provider_id"] == "prov-1"
    assert "base_url" not in failed


@pytest.mark.asyncio
async def test_fence_stream_success_emits_llm_call():
    provider = observe_provider(_FakeLeaf())
    with capture_logs() as caps:
        chunks = [c async for c in provider.stream(_req(scenario="inference.proxy"))]
    assert any(c.delta_content == "hi" for c in chunks)
    call = next(c for c in caps if c.get("event") == "llm.call")
    assert call["scenario"] == "inference.proxy"
    assert call["model"] == DEEPSEEK_V4_FLASH
    assert call["stream"] is True
    assert call["attempt"] == 1
    assert call["output_tokens"] == 3


@pytest.mark.asyncio
async def test_fence_stream_failure_emits_llm_call_failed():
    class _BoomLeaf(_FakeLeaf):
        async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
            yield LLMChunk(delta_content="x")
            raise LLMUpstreamError("stream-down", upstream_status=503, retry_attempts=0)

    provider = observe_provider(_BoomLeaf())
    with capture_logs() as caps, pytest.raises(LLMUpstreamError):
        async for _ in provider.stream(_req()):
            pass
    failed = next(c for c in caps if c.get("event") == "llm.call_failed")
    assert failed["stream"] is True
    assert failed["attempt"] == 1
    assert "stream-down" in failed["error"]


def test_build_provider_wraps_with_fence(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.factory.platform_llm_credentials",
        lambda **_k: None,
    )
    monkeypatch.setattr("agentcore.llm.factory.settings.platform_api_key", "k")
    monkeypatch.setattr("agentcore.llm.factory.settings.platform_base_url", "http://x/v1")
    provider = build_provider()
    assert isinstance(provider, ObservingLLMProvider)
    assert unwrap_provider(provider).__class__.__name__ == "OpenAICompatibleProvider"
    assert observe_provider(provider) is provider  # idempotent
    # BYOK 设置·测试 calls probe on the fence-wrapped provider — must not AttributeError.
    assert callable(getattr(provider, "probe", None))
    assert callable(getattr(provider, "probe_tools", None))


@pytest.mark.asyncio
async def test_fence_forwards_probe_and_probe_tools():
    class _ProbeLeaf(_FakeLeaf):
        def __init__(self) -> None:
            super().__init__()
            self.probe_model: str | None = None
            self.tools_model: str | None = None

        async def probe(self, *, model: str) -> None:
            self.probe_model = model

        async def probe_tools(self, *, model: str) -> bool | None:
            self.tools_model = model
            return True

    leaf = _ProbeLeaf()
    provider = observe_provider(leaf)
    await provider.probe(model=DEEPSEEK_V4_FLASH)
    assert leaf.probe_model == DEEPSEEK_V4_FLASH
    assert await provider.probe_tools(model=DEEPSEEK_V4_FLASH) is True
    assert leaf.tools_model == DEEPSEEK_V4_FLASH


@pytest.mark.asyncio
async def test_fence_probe_tools_none_when_leaf_lacks_method():
    provider = observe_provider(_FakeLeaf())  # no probe_tools
    assert await provider.probe_tools(model=DEEPSEEK_V4_FLASH) is None


def test_log_llm_call_includes_attempt():
    from agentcore.llm.observability import log_llm_call

    with capture_logs() as caps:
        log_llm_call(
            scenario="chat",
            model=DEEPSEEK_V4_FLASH,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            finish_reason="stop",
            latency_ms=5,
            stream=False,
            attempt=2,
            credential_source="platform",
        )
    call = next(c for c in caps if c.get("event") == "llm.call")
    assert call["attempt"] == 2

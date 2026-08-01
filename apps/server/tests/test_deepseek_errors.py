"""Provider-level mapping of upstream HTTP errors raised during a turn."""

import json

import httpx
import pytest

from agentcore.core.errors import (
    InferenceTokenExpiredError,
    LLMAuthError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMUpstreamError,
)
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import LLMMessage, LLMRequest, ToolCall, ToolCallFunction


async def _mock_provider(handler) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(
        name="test", api_key="k", base_url="http://example.invalid/v1"
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="http://example.invalid/v1",
        transport=httpx.MockTransport(handler),
    )
    return provider


def _req() -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model=DEEPSEEK_V4_FLASH,
    )


async def test_complete_maps_402_to_insufficient_balance():
    provider = await _mock_provider(lambda request: httpx.Response(402))
    try:
        with pytest.raises(LLMInsufficientBalanceError) as ei:
            await provider.complete(_req())
        assert "余额" in str(ei.value)
    finally:
        await provider.close()


async def test_stream_maps_402_to_insufficient_balance():
    provider = await _mock_provider(lambda request: httpx.Response(402))
    try:
        with pytest.raises(LLMInsufficientBalanceError):
            async for _ in provider.stream(_req()):
                pass
    finally:
        await provider.close()


@pytest.mark.parametrize("code", [401, 403])
async def test_complete_maps_401_403_to_auth_error(code):
    body = b'{"error":{"message":"invalid api key","type":"authentication_error","code":"invalid_api_key"}}'
    provider = await _mock_provider(lambda request: httpx.Response(code, content=body))
    try:
        with pytest.raises(LLMAuthError) as ei:
            await provider.complete(_req())
        assert "DeepSeek" not in ei.value.message
        assert "invalid api key" in ei.value.message
        assert ei.value.details.get("upstream_status") == code
        assert "invalid api key" in (ei.value.details.get("upstream_body_preview") or "")
    finally:
        await provider.close()


@pytest.mark.parametrize("code", [401, 403])
async def test_inference_proxy_401_maps_to_inference_token_expired(code):
    """Sidecar→cloud /inference/ base_url: JWT rejection ≠ BYOK key invalid."""
    body = b'{"error":{"message":"Invalid or expired inference token"}}'
    provider = OpenAICompatibleProvider(
        name="user",
        api_key="tok",
        base_url="http://127.0.0.1:8000/v1/inference/v1",
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="http://127.0.0.1:8000/v1/inference/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(code, content=body)),
    )
    try:
        with pytest.raises(InferenceTokenExpiredError) as ei:
            await provider.complete(_req())
        assert ei.value.code == "INFERENCE_TOKEN_EXPIRED"
        assert ei.value.retryable is True
        assert "推理凭证" in ei.value.message
        assert ei.value.details.get("upstream_status") == code
    finally:
        await provider.close()


async def test_complete_maps_key_expired_to_auth_error_with_upstream_text():
    body = json.dumps(
        {
            "error": {
                "message": "This API key has expired. 请访问本站查看 CC Switch 配置教程。",
                "type": "invalid_request_error",
                "code": "key_expired",
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    provider = await _mock_provider(lambda request: httpx.Response(401, content=body))
    try:
        with pytest.raises(LLMAuthError) as ei:
            await provider.complete(_req())
        assert "expired" in ei.value.message.lower()
        assert ei.value.details.get("upstream_status") == 401
    finally:
        await provider.close()


async def test_platform_auth_uses_product_copy_not_upstream_gateway_text():
    """Platform 401 must not echo upstream gateway help (e.g. CC Switch)."""
    body = json.dumps(
        {
            "error": {
                "message": "This API key has been revoked. 请访问本站查看 CC Switch 配置教程。",
                "type": "invalid_request_error",
                "code": "key_revoked",
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    provider = OpenAICompatibleProvider(
        name="platform", api_key="k", base_url="http://example.invalid/v1"
    )
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(
        base_url="http://example.invalid/v1",
        transport=httpx.MockTransport(lambda request: httpx.Response(401, content=body)),
    )
    try:
        with pytest.raises(LLMAuthError) as ei:
            await provider.complete(_req())
        assert "CC Switch" not in ei.value.message
        assert "platform " not in ei.value.message
        assert "平台模型暂时不可用" in ei.value.message
        assert ei.value.details.get("upstream_status") == 401
        assert "revoked" in (ei.value.details.get("upstream_body_preview") or "").lower()
    finally:
        await provider.close()


async def test_llm_auth_error_platform_default_message():
    err = LLMAuthError(provider_name="platform")
    assert "平台模型暂时不可用" in err.message
    assert "platform" not in err.message
    assert "CC Switch" not in err.message
    assert "设置 · 模型配置" not in err.message  # BYOK remedy, not platform


async def test_complete_maps_model_not_allowed_403_to_client_error_not_auth():
    body = json.dumps(
        {
            "error": {
                "message": "模型 ID 配置不正确。",
                "type": "invalid_request_error",
                "code": "model_not_allowed",
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")
    provider = await _mock_provider(lambda request: httpx.Response(403, content=body))
    try:
        with pytest.raises(LLMError) as ei:
            await provider.complete(_req())
        assert not isinstance(ei.value, LLMAuthError)
        assert "模型 ID" in ei.value.message
        assert ei.value.details.get("upstream_status") == 403
    finally:
        await provider.close()


async def test_complete_maps_500_with_context():
    provider = await _mock_provider(
        lambda request: httpx.Response(500, content=b'{"error":"boom"}')
    )
    try:
        with pytest.raises(LLMUpstreamError) as ei:
            await provider.complete(_req())
        assert ei.value.details.get("upstream_status") == 500
        assert "boom" in (ei.value.details.get("upstream_body_preview") or "")
    finally:
        await provider.close()


async def test_complete_maps_400_to_llm_error_with_upstream_body():
    body = (
        b'{"error":{"message":"The `reasoning_content` in the thinking mode '
        b'must be passed back to the API."}}'
    )
    provider = await _mock_provider(lambda request: httpx.Response(400, content=body))
    try:
        with pytest.raises(LLMError) as ei:
            await provider.complete(_req())
        assert ei.value.retryable is False
        assert "reasoning_content" in ei.value.message
        assert ei.value.details.get("upstream_status") == 400
        assert "reasoning_content" in (ei.value.details.get("upstream_body_preview") or "")
    finally:
        await provider.close()


async def test_stream_maps_400_to_llm_error():
    body = b'{"error":{"message":"bad request"}}'
    provider = await _mock_provider(lambda request: httpx.Response(400, content=body))
    try:
        with pytest.raises(LLMError) as ei:
            async for _ in provider.stream(_req()):
                pass
        assert "bad request" in ei.value.message
    finally:
        await provider.close()


def test_build_payload_echoes_reasoning_content_for_tool_turns():
    provider = OpenAICompatibleProvider(name="test", api_key="k", base_url="http://x/v1")
    req = LLMRequest(
        messages=[
            LLMMessage(role="user", content="go"),
            LLMMessage(
                role="assistant",
                content="",
                reasoning_content="chain",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        function=ToolCallFunction(name="search", arguments="{}"),
                    )
                ],
            ),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="tc2",
                        function=ToolCallFunction(name="read", arguments="{}"),
                    )
                ],
            ),
        ],
        model=DEEPSEEK_V4_FLASH,
    )
    payload = provider._build_payload(req, stream=True)
    assistant_msgs = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant_msgs[0]["reasoning_content"] == "chain"
    assert assistant_msgs[1]["reasoning_content"] == ""


def test_build_payload_clean_openai_for_non_deepseek_tool_turns():
    """Non-DeepSeek models must not leak DeepSeek reasoning_content; empty
    assistant tool turns still carry content:\"\" (clean OpenAI form)."""
    provider = OpenAICompatibleProvider(name="test", api_key="k", base_url="http://x/v1")
    req = LLMRequest(
        messages=[
            LLMMessage(role="user", content="go"),
            LLMMessage(
                role="assistant",
                content=None,
                reasoning_content="should not be sent",
                tool_calls=[
                    ToolCall(
                        id="tooluse_abc",
                        function=ToolCallFunction(name="consult_skill", arguments='{"name":"x"}'),
                    )
                ],
            ),
            LLMMessage(role="tool", content="skill body", tool_call_id="tooluse_abc"),
        ],
        model="gpt-4o",
    )
    payload = provider._build_payload(req, stream=True)
    assistant = next(m for m in payload["messages"] if m["role"] == "assistant")
    assert assistant["content"] == ""
    assert "reasoning_content" not in assistant
    assert assistant["tool_calls"][0]["id"] == "tooluse_abc"


def test_build_payload_disables_thinking_for_deepseek_v4_background():
    """Title/memory one-shots must send thinking.disabled — otherwise V4's default
    thinking eats a tight max_tokens budget and the sidebar falls back to raw input."""
    provider = OpenAICompatibleProvider(name="test", api_key="k", base_url="http://x/v1")
    req = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model=DEEPSEEK_V4_FLASH,
        max_tokens=64,
        thinking=False,
        scenario="title",
    )
    payload = provider._build_payload(req, stream=False)
    assert payload["thinking"] == {"type": "disabled"}

    # Non-DeepSeek models must not get the DeepSeek-only field.
    other = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model="gpt-4o",
        thinking=False,
        scenario="title",
    )
    assert "thinking" not in provider._build_payload(other, stream=False)

    # Default (None) leaves thinking omitted so V4 keeps its enabled default.
    default = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model=DEEPSEEK_V4_FLASH,
    )
    assert "thinking" not in provider._build_payload(default, stream=False)


def test_balance_and_auth_errors_are_not_retryable():
    assert LLMInsufficientBalanceError().retryable is False
    assert LLMAuthError().retryable is False


def test_inference_token_expired_is_retryable():
    err = InferenceTokenExpiredError()
    assert err.retryable is True
    assert err.code == "INFERENCE_TOKEN_EXPIRED"
    assert "推理凭证" in err.message


def test_upstream_error_is_retryable():
    err = LLMUpstreamError("test", upstream_status=502)
    assert err.retryable is True

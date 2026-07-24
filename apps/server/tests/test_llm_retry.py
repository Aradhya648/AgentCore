"""LLM provider retry policy: transient upstream / transport failures."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from agentcore.core.errors import LLMError, LLMTimeoutError, LLMUpstreamError
from agentcore.llm.errors import is_non_retryable_client_status, is_retryable_upstream_status
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.openai_compatible import (
    _CONNECT_INITIAL_BACKOFF,
    _CONNECT_MAX_RETRIES,
    _INITIAL_BACKOFF,
    _MAX_RETRIES,
    _MAX_RETRY_AFTER,
    OpenAICompatibleProvider,
    _parse_retry_after,
    _retry_wait,
)
from agentcore.llm.provider.protocol import LLMMessage, LLMRequest


def _ok_body() -> dict:
    return {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "model": DEEPSEEK_V4_FLASH,
    }


def _sse_line(text: str = "hi") -> str:
    payload = {
        "choices": [{"delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n"


def _sse_reasoning(text: str = "think") -> str:
    payload = {
        "choices": [{"delta": {"reasoning_content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n"


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


def test_retryable_status_helpers():
    assert is_retryable_upstream_status(502) is True
    assert is_retryable_upstream_status(503) is True
    assert is_retryable_upstream_status(400) is False
    assert is_non_retryable_client_status(400) is True
    assert is_non_retryable_client_status(401) is True
    assert is_non_retryable_client_status(502) is False


@pytest.mark.parametrize("code", [502, 503])
async def test_complete_retries_transient_5xx_then_succeeds(code, monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(code, content=b'{"error":"upstream"}')
        return httpx.Response(200, json=_ok_body())

    provider = await _mock_provider(handler)
    try:
        result = await provider.complete(_req())
        assert result.content == "ok"
        assert calls["n"] == 2
        assert sleeps == [_INITIAL_BACKOFF]
    finally:
        await provider.close()


async def test_complete_does_not_retry_400(monkeypatch):
    calls = {"n": 0}

    async def fake_sleep(sec: float) -> None:
        raise AssertionError("should not sleep on 400")

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, content=b'{"error":{"message":"bad request"}}')

    provider = await _mock_provider(handler)
    try:
        with pytest.raises(LLMError) as ei:
            await provider.complete(_req())
        assert ei.value.retryable is False
        assert calls["n"] == 1
    finally:
        await provider.close()


async def test_complete_retries_connect_error_then_succeeds(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json=_ok_body())

    provider = await _mock_provider(handler)
    try:
        result = await provider.complete(_req())
        assert result.content == "ok"
        assert calls["n"] == 2
        assert sleeps == [_CONNECT_INITIAL_BACKOFF]
    finally:
        await provider.close()


async def test_complete_connect_timeout_fails_fast(monkeypatch):
    """ConnectTimeout: only 1 retry (2 attempts) with 1s backoff — not the 5xx budget."""
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("connect timed out")

    provider = await _mock_provider(handler)
    try:
        with pytest.raises(LLMTimeoutError):
            await provider.complete(_req())
        assert calls["n"] == _CONNECT_MAX_RETRIES
        assert sleeps == [_CONNECT_INITIAL_BACKOFF]
        assert calls["n"] < _MAX_RETRIES
    finally:
        await provider.close()


async def test_complete_read_timeout_keeps_full_retry_budget(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out")

    provider = await _mock_provider(handler)
    try:
        with pytest.raises(LLMTimeoutError):
            await provider.complete(_req())
        assert calls["n"] == _MAX_RETRIES
        assert sleeps == [_INITIAL_BACKOFF, _INITIAL_BACKOFF * 2]
    finally:
        await provider.close()


async def test_complete_exhausts_retries_on_persistent_502(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, content=b'{"error":"bad gateway"}')

    provider = await _mock_provider(handler)
    try:
        with pytest.raises(LLMUpstreamError) as ei:
            await provider.complete(_req())
        assert calls["n"] == _MAX_RETRIES
        assert sleeps == [_INITIAL_BACKOFF, _INITIAL_BACKOFF * 2]
        assert ei.value.details.get("retry_attempts") == _MAX_RETRIES
    finally:
        await provider.close()


async def test_stream_retries_502_before_any_sse_line(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502, content=b'{"error":"bad gateway"}')
        body = _sse_line("done") + "data: [DONE]\n"
        return httpx.Response(200, content=body.encode())

    provider = await _mock_provider(handler)
    try:
        chunks = [c async for c in provider.stream(_req())]
        assert any(c.delta_content == "done" for c in chunks)
        assert calls["n"] == 2
        assert sleeps == [_INITIAL_BACKOFF]
    finally:
        await provider.close()


def test_parse_retry_after_seconds_and_fallbacks():
    # Delta-seconds (the DeepSeek case) parses straight through (raw; sleep clamps later).
    assert _parse_retry_after("120", 2.0) == 120.0
    assert _parse_retry_after(" 5 ", 2.0) == 5.0
    # audit 01 F9: absent / blank / malformed must fall back to backoff, never raise
    # (a raised ValueError used to escape the retry path and surface as a generic 502).
    assert _parse_retry_after(None, 2.0) == 2.0
    assert _parse_retry_after("", 2.0) == 2.0
    assert _parse_retry_after("not-a-date", 2.0) == 2.0


def test_parse_retry_after_http_date():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    # An HTTP-date value (RFC 7231) resolves to a positive delta, not a ValueError.
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=60))
    delta = _parse_retry_after(future, 2.0)
    assert 0 < delta <= 60
    # A past HTTP-date has a non-positive delta → fall back to backoff.
    past = format_datetime(datetime.now(UTC) - timedelta(seconds=60))
    assert _parse_retry_after(past, 2.0) == 2.0


def test_retry_wait_honors_small_retry_after_and_ignores_absurd():
    # Interactive budgets (title 20s / followups 15s): honor modest Retry-After,
    # but a spurious 3600 must not become wait_sec (e80c6f99 title.timeout case).
    assert _retry_wait(5.0, 2.0) == (5.0, 5.0)
    assert _retry_wait(None, 2.0) == (2.0, None)
    wait, raw = _retry_wait(3600.0, 2.0)
    assert raw == 3600.0
    assert wait == 2.0
    assert wait <= _MAX_RETRY_AFTER
    # Exactly at the cap is still honored.
    assert _retry_wait(_MAX_RETRY_AFTER, 2.0) == (_MAX_RETRY_AFTER, _MAX_RETRY_AFTER)


async def test_complete_rate_limit_absurd_retry_after_uses_backoff(monkeypatch):
    """Retry-After: 3600 → sleep backoff, not an hour (log wait_sec ≠ raw header)."""
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "3600"},
                content=b'{"error":"rate_limited"}',
            )
        return httpx.Response(200, json=_ok_body())

    provider = await _mock_provider(handler)
    try:
        result = await provider.complete(_req())
        assert result.content == "ok"
        assert calls["n"] == 2
        assert sleeps == [_INITIAL_BACKOFF]
    finally:
        await provider.close()


async def test_complete_rate_limit_honors_short_retry_after_chain(monkeypatch):
    """2→4→8 Retry-After chain must be waited (not abandoned at MAX_RETRIES=3)."""
    from agentcore.llm.provider.openai_compatible import _RATE_LIMIT_MAX_RETRIES

    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # Three 429s then success — needs RATE_LIMIT_MAX_RETRIES > MAX_RETRIES.
        if calls["n"] <= 3:
            return httpx.Response(
                429,
                headers={"retry-after": str(2 ** calls["n"])},
                content=b'{"error":"rate_limited"}',
            )
        return httpx.Response(200, json=_ok_body())

    provider = await _mock_provider(handler)
    try:
        result = await provider.complete(_req())
        assert result.content == "ok"
        assert calls["n"] == 4
        assert sleeps == [2.0, 4.0, 8.0]
        assert _RATE_LIMIT_MAX_RETRIES > _MAX_RETRIES
    finally:
        await provider.close()


async def test_stream_does_not_retry_after_committed_content():
    """Content delta commits the stream: disconnect yields aborted, no retry."""
    provider = OpenAICompatibleProvider(
        name="test", api_key="k", base_url="http://example.invalid/v1"
    )

    async def line_iter():
        yield _sse_line("partial")
        raise httpx.ReadError("peer closed connection")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.aread = AsyncMock(return_value=b"")
    mock_response.aiter_lines = line_iter
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    provider._client.stream = MagicMock(return_value=mock_response)
    try:
        chunks = [c async for c in provider.stream(_req())]
        assert [c.delta_content for c in chunks if c.delta_content] == ["partial"]
        assert chunks[-1].aborted is True
        provider._client.stream.assert_called_once()
    finally:
        await provider.close()


async def test_stream_retries_after_reasoning_only_disconnect(monkeypatch):
    """Reasoning deltas do not commit: RemoteProtocolError → transparent retry."""
    calls = {"n": 0}
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr("agentcore.llm.provider.openai_compatible.asyncio.sleep", fake_sleep)

    provider = OpenAICompatibleProvider(
        name="test", api_key="k", base_url="http://example.invalid/v1"
    )

    async def first_lines():
        yield _sse_reasoning("step1")
        yield _sse_reasoning("step2")
        raise httpx.RemoteProtocolError("peer closed connection")

    async def second_lines():
        yield _sse_reasoning("fresh")
        yield _sse_line("final answer")
        yield "data: [DONE]\n"

    def make_response(line_iter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.aread = AsyncMock(return_value=b"")
        mock_response.aiter_lines = line_iter
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        return mock_response

    responses = [make_response(first_lines), make_response(second_lines)]

    def stream_side_effect(*_a, **_kw):
        calls["n"] += 1
        return responses[calls["n"] - 1]

    provider._client.stream = MagicMock(side_effect=stream_side_effect)
    try:
        chunks = [c async for c in provider.stream(_req())]
        assert calls["n"] == 2
        assert sleeps == [_INITIAL_BACKOFF]
        assert any(c.stream_reset for c in chunks)
        assert [c.delta_reasoning for c in chunks if c.delta_reasoning] == [
            "step1",
            "step2",
            "fresh",
        ]
        assert [c.delta_content for c in chunks if c.delta_content] == ["final answer"]
        assert not any(c.aborted for c in chunks)
    finally:
        await provider.close()

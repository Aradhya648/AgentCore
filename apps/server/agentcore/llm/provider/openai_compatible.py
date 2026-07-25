"""Generic OpenAI-compatible LLM provider — the single production implementation."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal

import httpx

from agentcore.core.errors import (
    LLMAuthError,
    LLMClientClosedError,
    LLMError,
    LLMInsufficientBalanceError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUpstreamError,
    is_llm_client_closed_error,
)
from agentcore.core.logging import get_logger
from agentcore.llm.errors import (
    body_preview,
    client_error_message,
    diagnose_empty_response,
    is_auth_rejection,
    is_non_retryable_client_status,
    upstream_client_error,
    upstream_error,
)
from agentcore.llm.provider.protocol import (
    BACKOFF_MULTIPLIER,
    CONNECT_INITIAL_BACKOFF,
    CONNECT_MAX_RETRIES,
    INITIAL_BACKOFF,
    MAX_RETRIES,
    MAX_RETRY_AFTER,
    RATE_LIMIT_MAX_RETRIES,
    LLMChunk,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
    ToolCallFunction,
)
from agentcore.llm.sub2api_probe import probe_sub2api_diagnosis_result

logger = get_logger(__name__)


def _request_attribution_headers() -> dict[str, str]:
    """Merge billing attribution headers when talking to the cloud inference proxy.

    No-op (empty) when log context has no run stamps — BYOK / direct upstream
    calls ignore unknown headers; the cloud proxy uses them for cost_calls.
    """
    try:
        from agentcore.billing.attribution import attribution_headers_from_context

        return attribution_headers_from_context()
    except Exception:  # noqa: BLE001 — never let billing headers break LLM I/O
        return {}


# Local aliases keep call sites readable; values live on the public protocol layer.
_MAX_RETRIES = MAX_RETRIES
_INITIAL_BACKOFF = INITIAL_BACKOFF
_BACKOFF_MULTIPLIER = BACKOFF_MULTIPLIER
_CONNECT_MAX_RETRIES = CONNECT_MAX_RETRIES
_CONNECT_INITIAL_BACKOFF = CONNECT_INITIAL_BACKOFF
_RATE_LIMIT_MAX_RETRIES = RATE_LIMIT_MAX_RETRIES
_MAX_RETRY_AFTER = MAX_RETRY_AFTER
# Loop ceiling must cover the longest retry policy (429 chains need more slots
# than generic 5xx); per-error ``_can_retry_attempt`` still enforces the tighter
# cap for non-rate-limit failures.
_IO_ATTEMPT_CEILING = max(_MAX_RETRIES, _RATE_LIMIT_MAX_RETRIES, _CONNECT_MAX_RETRIES)
# Unary completions can run 150s+ for long-form writing; streaming read timeout is
# per-chunk idle, so a generous ceiling avoids false positives on slow generations.
_REQUEST_TIMEOUT = 300.0
# Thinking models (e.g. DeepSeek V4) burn tokens on reasoning before any tool_calls;
# keep a floor so the probe is not starved by a tiny completion budget.
_PROBE_TOOLS_MAX_TOKENS = 256
_PROBE_TOOLS_RETRY = "retry_without_required"
# Body must mention tools/function-calling AND a rejection cue — avoids treating
# generic 4xx (auth, quota, bad model id) as "does not support tools".
_TOOLS_PARAM_MARKERS = re.compile(
    r"\b(tools?|tool[_-]?choice|function[_-]?call(?:ing)?|functions)\b",
    re.IGNORECASE,
)
_TOOLS_REJECT_MARKERS = re.compile(
    r"(not\s+support|unsupported|does\s+not\s+support|invalid|unknown|"
    r"not\s+allowed|not\s+available|unrecognized|no\s+longer\s+supported|"
    r"不支持|无效|未知)",
    re.IGNORECASE,
)


def _is_tools_unsupported_rejection(status: int, body: str) -> bool:
    """True when a 4xx body clearly rejects tools / function calling parameters."""
    if status < 400 or status >= 500 or status == 429:
        return False
    # Auth / payment / missing route are not evidence about tool support.
    if status in (401, 402, 403, 404):
        return False
    if not body.strip():
        return False
    return bool(_TOOLS_PARAM_MARKERS.search(body) and _TOOLS_REJECT_MARKERS.search(body))


def _is_deepseek_model(model: str) -> bool:
    """True for DeepSeek ids (incl. ``provider/deepseek-…`` routed names)."""
    name = model.rsplit("/", 1)[-1].lower()
    return name.startswith("deepseek")


def _is_deepseek_v4(model: str) -> bool:
    """True for DeepSeek V4 ids (incl. ``provider/deepseek-v4-…`` routed names)."""
    name = model.rsplit("/", 1)[-1].lower()
    return name.startswith("deepseek-v4")


def _usage_from(usage_data: dict) -> TokenUsage:
    """Wire-usage parse — both DeepSeek and OpenAI prompt-cache dialects (protocol.py)."""
    return TokenUsage.from_openai_wire(usage_data)


def _parse_retry_after(raw: str | None, backoff: float) -> float:
    """Parse an HTTP ``Retry-After`` header (RFC 7231): either delta-seconds or an
    HTTP-date. Any absent/malformed value falls back to ``backoff`` so a 429 never
    escapes the retry/error mapping as a generic 502 (audit 01 F9).

    Returns the **raw** parsed seconds (may be hour-scale). Callers must pass it
    through :func:`_retry_wait` before sleeping — ``wait_sec`` in logs is the
    clamped sleep, not this raw value.
    """
    if raw is None:
        return backoff
    raw = raw.strip()
    if not raw:
        return backoff
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return backoff
    if when is None:
        return backoff
    now = datetime.now(when.tzinfo or UTC)
    delta = (when - now).total_seconds()
    return delta if delta > 0 else backoff


def _retry_wait(retry_after: float | None, backoff: float) -> tuple[float, float | None]:
    """Map a parsed Retry-After (or None) to the seconds we will actually sleep.

    Returns ``(wait_sec, retry_after_sec)`` where ``wait_sec`` is what
    ``asyncio.sleep`` uses and ``retry_after_sec`` is the raw header value when
    present (for logs). Values above ``MAX_RETRY_AFTER`` fall back to ``backoff``
    so a spurious ``Retry-After: 3600`` cannot starve title/followups budgets.
    """
    if retry_after is None:
        return backoff, None
    if retry_after > _MAX_RETRY_AFTER:
        return backoff, retry_after
    return (retry_after if retry_after > 0 else backoff), retry_after


class OpenAICompatibleProvider:
    """OpenAI-compatible ``/chat/completions`` provider."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._extra_headers = dict(extra_headers) if extra_headers else None
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self._extra_headers:
            headers.update(self._extra_headers)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=10.0),
        )

    @property
    def name(self) -> str:
        return self._name

    def clone(self) -> OpenAICompatibleProvider:
        """Independent HTTP client with the same credentials (coordination drive ownership)."""
        return OpenAICompatibleProvider(
            name=self._name,
            api_key=self._api_key,
            base_url=self._base_url,
            extra_headers=self._extra_headers,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request, stream=False)
        start = time.monotonic()
        data = await self._request_with_retry(payload)
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = data["choices"][0]
        message = choice["message"]
        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    function=ToolCallFunction(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                )
                for tc in message["tool_calls"]
            ]
        usage = _usage_from(data.get("usage", {}))
        finish_reason = choice.get("finish_reason", "stop")
        content = message.get("content") or ""
        raw_body_preview = body_preview(json.dumps(data, ensure_ascii=False))
        empty_diagnosis: str | None = None
        if not content and not tool_calls:
            diagnosis = diagnose_empty_response(
                raw_body=raw_body_preview,
                finish_reason=finish_reason,
            )
            empty_diagnosis = diagnosis.value
            logger.warning(
                "llm.empty_response",
                model=data.get("model", request.model),
                scenario=request.scenario,
                raw_body_preview=raw_body_preview,
                finish_reason=finish_reason,
                usage=usage.as_dict(),
                diagnosis=empty_diagnosis,
            )
        # Success / failure metrics: ``observe_provider`` fence (build_provider).
        return LLMResponse(
            content=content,
            reasoning_content=message.get("reasoning_content"),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            model=data.get("model", request.model),
            latency_ms=latency_ms,
            empty_diagnosis=empty_diagnosis,
            empty_raw_preview=raw_body_preview if empty_diagnosis else None,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        """Parse-and-retry stream: retry loop sees semantic commit state in-place.

        ``committed`` flips on the first content or tool_call delta. Reasoning,
        role-only, usage-only, and keepalive chunks do not commit. Pre-commit
        transport/upstream failures transparently retry the whole request;
        post-commit disconnect yields ``aborted`` instead of raising so the
        engine can keep the partial. A transparent retry yields ``stream_reset``
        so consumers drop ephemeral reasoning before the next attempt.
        """
        payload = self._build_payload(request, stream=True)
        last_error: Exception | None = None
        backoff = _INITIAL_BACKOFF
        yielded_ephemeral = False
        self._ensure_client_open()

        for attempt in range(_IO_ATTEMPT_CEILING):
            committed = False
            lines_seen = 0
            has_content = False
            has_tool_calls = False
            last_lines: list[str] = []
            last_finish_reason: str | None = None
            last_usage: TokenUsage | None = None
            json_parse_failures = 0
            parsed_chunks = 0
            forwarded_diagnosis: str | None = None
            forwarded_preview: str | None = None

            try:
                self._ensure_client_open()
                async with self._client.stream(
                    "POST",
                    "/chat/completions",
                    json=payload,
                    headers=_request_attribution_headers() or None,
                ) as response:
                    body = await response.aread() if response.status_code >= 400 else None
                    self._raise_for_status(
                        response.status_code,
                        backoff,
                        response.headers,
                        body=body,
                        attempt=attempt,
                    )
                    async for line in response.aiter_lines():
                        lines_seen += 1
                        if len(last_lines) >= 5:
                            last_lines.pop(0)
                        last_lines.append(line)

                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            json_parse_failures += 1
                            continue
                        parsed_chunks += 1
                        # Proxied upstream forwards empty-response diagnosis inline (01 F8).
                        if data.get("empty_diagnosis"):
                            forwarded_diagnosis = data["empty_diagnosis"]
                            forwarded_preview = data.get("empty_raw_preview")
                            continue
                        # Proxied upstream relays the stream-control signals inline (mirror
                        # of empty_diagnosis) so this hop reconstructs the same LLMChunk
                        # protocol it would see talking to the real upstream directly:
                        # a transparent pre-commit retry (stream_reset) and a post-commit
                        # disconnect salvage (aborted) survive the proxy re-serialization.
                        if data.get("stream_reset"):
                            yield LLMChunk(stream_reset=True)
                            continue
                        if data.get("aborted"):
                            yield LLMChunk(aborted=True)
                            return
                        choices = data.get("choices") or [{}]
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        content_delta = delta.get("content")
                        reasoning_delta = delta.get("reasoning_content")
                        raw_tool_calls = delta.get("tool_calls")
                        if content_delta:
                            has_content = True
                            committed = True
                        if raw_tool_calls:
                            has_tool_calls = True
                            committed = True
                        tc_deltas = None
                        if raw_tool_calls:
                            tc_deltas = [
                                ToolCallDelta(
                                    index=tc.get("index", 0),
                                    id=tc.get("id"),
                                    function_name=tc.get("function", {}).get("name"),
                                    arguments_delta=tc.get("function", {}).get("arguments"),
                                )
                                for tc in raw_tool_calls
                            ]
                        if choice.get("finish_reason"):
                            last_finish_reason = choice.get("finish_reason")
                        usage = _usage_from(data["usage"]) if data.get("usage") else None
                        if usage:
                            last_usage = usage
                        if reasoning_delta:
                            yielded_ephemeral = True
                        yield LLMChunk(
                            delta_content=content_delta,
                            delta_reasoning=reasoning_delta,
                            delta_tool_calls=tc_deltas,
                            finish_reason=choice.get("finish_reason"),
                            usage=usage,
                        )

                if not has_content and not has_tool_calls:
                    if forwarded_diagnosis is not None:
                        yield LLMChunk(
                            empty_diagnosis=forwarded_diagnosis,
                            empty_raw_preview=forwarded_preview,
                        )
                        return
                    raw_body_preview = body_preview("\n".join(last_lines))
                    format_mismatch = json_parse_failures > 0 and parsed_chunks == 0
                    diagnosis = diagnose_empty_response(
                        raw_body=raw_body_preview,
                        finish_reason=last_finish_reason,
                        format_mismatch=format_mismatch,
                    )
                    logger.warning(
                        "llm.empty_response",
                        model=request.model,
                        scenario=request.scenario,
                        raw_body_preview=raw_body_preview,
                        finish_reason=last_finish_reason,
                        usage=last_usage.as_dict() if last_usage else {},
                        diagnosis=diagnosis.value,
                        sse_tail=last_lines,
                    )
                    yield LLMChunk(
                        empty_diagnosis=diagnosis.value,
                        empty_raw_preview=raw_body_preview,
                    )
                return

            except LLMUpstreamError as e:
                last_error = e
                if committed:
                    logger.warning(
                        "llm.stream_partial_disconnect",
                        provider=self._name,
                        partial_sse_lines=lines_seen,
                        reason=f"upstream_{e.details.get('upstream_status', 500)}",
                        committed=True,
                    )
                    yield LLMChunk(aborted=True)
                    return
                if not e.retryable or not self._can_retry_attempt(attempt):
                    await self._finalize_upstream_error(e, attempt)
                if yielded_ephemeral:
                    yield LLMChunk(stream_reset=True)
                    yielded_ephemeral = False
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=backoff,
                    stream=True,
                    reason=f"upstream_{e.details.get('upstream_status', 500)}",
                    partial_sse_lines=lines_seen,
                )
            except (LLMRateLimitError, LLMError) as e:
                last_error = e
                if committed:
                    logger.warning(
                        "llm.stream_partial_disconnect",
                        provider=self._name,
                        partial_sse_lines=lines_seen,
                        reason=type(e).__name__,
                        committed=True,
                    )
                    yield LLMChunk(aborted=True)
                    return
                max_attempts = (
                    _RATE_LIMIT_MAX_RETRIES
                    if isinstance(e, LLMRateLimitError)
                    else _MAX_RETRIES
                )
                if not e.retryable or not self._can_retry_attempt(
                    attempt, max_attempts=max_attempts
                ):
                    raise
                if yielded_ephemeral:
                    yield LLMChunk(stream_reset=True)
                    yielded_ephemeral = False
                retry_after = e.retry_after if isinstance(e, LLMRateLimitError) else None
                wait, raw_retry_after = _retry_wait(retry_after, backoff)
                logger.info(
                    "llm.call_retried",
                    provider=self._name,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    wait_sec=wait,
                    retry_after_sec=raw_retry_after,
                    stream=True,
                    reason=type(e).__name__,
                )
                await asyncio.sleep(wait)
                backoff *= _BACKOFF_MULTIPLIER
            except httpx.TimeoutException as e:
                last_error = LLMTimeoutError(f"连接 {self._name} 超时，请检查网络后重试")
                if committed:
                    logger.warning(
                        "llm.stream_partial_disconnect",
                        provider=self._name,
                        partial_sse_lines=lines_seen,
                        reason="timeout",
                        committed=True,
                    )
                    yield LLMChunk(aborted=True)
                    return
                is_connect = isinstance(e, httpx.ConnectTimeout)
                max_attempts = _CONNECT_MAX_RETRIES if is_connect else _MAX_RETRIES
                if not self._can_retry_attempt(attempt, max_attempts=max_attempts):
                    raise last_error from e
                if yielded_ephemeral:
                    yield LLMChunk(stream_reset=True)
                    yielded_ephemeral = False
                retry_backoff = _CONNECT_INITIAL_BACKOFF if is_connect else backoff
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=retry_backoff,
                    stream=True,
                    reason="connect_timeout" if is_connect else "timeout",
                    partial_sse_lines=lines_seen,
                    max_attempts=max_attempts,
                )
            except httpx.HTTPError as e:
                last_error = self._network_error_to_llm(e)
                if committed:
                    logger.warning(
                        "llm.stream_partial_disconnect",
                        provider=self._name,
                        partial_sse_lines=lines_seen,
                        reason=type(e).__name__,
                        committed=True,
                    )
                    yield LLMChunk(aborted=True)
                    return
                is_connect = self._is_connect_failure(e)
                max_attempts = _CONNECT_MAX_RETRIES if is_connect else _MAX_RETRIES
                if not last_error.retryable or not self._can_retry_attempt(
                    attempt, max_attempts=max_attempts
                ):
                    raise last_error from e
                if yielded_ephemeral:
                    yield LLMChunk(stream_reset=True)
                    yielded_ephemeral = False
                retry_backoff = _CONNECT_INITIAL_BACKOFF if is_connect else backoff
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=retry_backoff,
                    stream=True,
                    reason=type(e).__name__,
                    partial_sse_lines=lines_seen,
                    max_attempts=max_attempts,
                )
            except RuntimeError as e:
                translated = self._translate_closed_client(e)
                if isinstance(translated, LLMClientClosedError):
                    raise translated from e
                raise

        raise last_error or LLMError(f"{self._name} 多次重试后仍失败，请稍后重试")

    def _build_payload(self, request: LLMRequest, *, stream: bool) -> dict:
        # Default wire shape is clean OpenAI Chat Completions. DeepSeek thinking
        # dialect (reasoning_content echo) is gated by model id — broadcasting it
        # to Claude/other relays triggers invalid_request on multi-turn tool loops.
        deepseek = _is_deepseek_model(request.model)
        messages = []
        for msg in request.messages:
            m: dict = {"role": msg.role}
            if msg.content is not None:
                m["content"] = msg.content
            elif msg.role == "assistant" and msg.tool_calls:
                # OpenAI-compatible tool turns always carry content (possibly empty).
                m["content"] = ""
            if msg.tool_calls:
                m["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if deepseek:
                if msg.reasoning_content is not None:
                    m["reasoning_content"] = msg.reasoning_content
                elif msg.role == "assistant" and msg.tool_calls:
                    # DeepSeek thinking mode: assistant tool-call turns must echo
                    # reasoning_content (empty string when the model omitted it).
                    m["reasoning_content"] = ""
            messages.append(m)

        payload: dict = {
            "model": request.model,
            "messages": messages,
            "stream": stream,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice
        if stream:
            payload["stream_options"] = {"include_usage": True}
        # DeepSeek V4 defaults to thinking on. Background one-shots (title / memory / …)
        # must disable it or a tight max_tokens budget is spent on reasoning_content and
        # the JSON body comes back empty → fallback_title = raw user input in the sidebar.
        if request.thinking is False and _is_deepseek_v4(request.model):
            payload["thinking"] = {"type": "disabled"}
        elif request.thinking is True and _is_deepseek_v4(request.model):
            payload["thinking"] = {"type": "enabled"}
        return payload

    async def _attach_sub2api_diagnosis(self, err: LLMUpstreamError) -> LLMUpstreamError:
        from agentcore.config.settings import settings

        status = err.details.get("upstream_status", 0)
        if settings.billing_mode != "platform" or status != 503:
            return err

        probe = await probe_sub2api_diagnosis_result()
        if probe is None:
            return err

        err.message = f"{err.message}\n诊断：{probe.diagnosis}"
        err.details["sub2api_diagnosis"] = probe.diagnosis
        if probe.account_email_masked:
            err.details["sub2api_account"] = probe.account_email_masked
        logger.warning(
            "llm.upstream_error",
            provider=self._name,
            status_code=status,
            sub2api_diagnosis=probe.diagnosis,
            sub2api_account=probe.account_email_masked,
        )
        return err

    def _raise_for_status(
        self,
        status_code: int,
        backoff: float,
        headers,
        *,
        body: bytes | None = None,
        attempt: int = 0,
    ) -> None:
        if status_code == 429:
            retry_after = _parse_retry_after(headers.get("retry-after"), backoff)
            raise LLMRateLimitError(retry_after=retry_after)
        if status_code in (401, 403):
            logger.warning(
                "llm.client_error",
                provider=self._name,
                status_code=status_code,
                body_preview=body_preview(body),
            )
            if is_auth_rejection(status_code, body):
                extracted = client_error_message(self._name, status_code, body)
                # Prefer upstream text (e.g. key_expired) over the generic default.
                raise LLMAuthError(
                    extracted,
                    provider_name=self._name,
                    upstream_status=status_code,
                    upstream_body_preview=body_preview(body),
                )
            raise upstream_client_error(
                client_error_message(self._name, status_code, body),
                status=status_code,
                body=body,
            )
        if status_code == 402:
            raise LLMInsufficientBalanceError()
        if status_code >= 500:
            logger.warning(
                "llm.upstream_error",
                provider=self._name,
                status_code=status_code,
                attempt=attempt + 1,
            )
            err = upstream_error(
                f"{self._name} 服务端错误（{status_code}），请稍后再试",
                status=status_code,
                body=body,
                retry_attempts=attempt,
            )
            if headers.get("x-upstream-retried"):
                err.retryable = False
            raise err
        if is_non_retryable_client_status(status_code) or 400 <= status_code < 500:
            logger.warning(
                "llm.client_error",
                provider=self._name,
                status_code=status_code,
                body_preview=body_preview(body),
            )
            raise upstream_client_error(
                client_error_message(self._name, status_code, body),
                status=status_code,
                body=body,
            )

    def _network_error_to_llm(self, exc: httpx.HTTPError) -> LLMError:
        """Map transient transport failures to retryable LLM errors."""
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeoutError(f"连接 {self._name} 超时，请检查网络后重试")
        detail = str(exc).strip() or type(exc).__name__
        return upstream_error(
            f"{self._name} 连接中断，请稍后再试",
            status=502,
            body=detail.encode(),
        )

    @staticmethod
    def _is_connect_failure(exc: BaseException) -> bool:
        """True for httpx connect-class failures (not read / write timeouts)."""
        return isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError))

    def _can_retry_attempt(self, attempt: int, *, max_attempts: int | None = None) -> bool:
        limit = _MAX_RETRIES if max_attempts is None else max_attempts
        return attempt < limit - 1

    async def _sleep_before_retry(
        self,
        *,
        attempt: int,
        backoff: float,
        stream: bool,
        reason: str,
        partial_sse_lines: int = 0,
        max_attempts: int | None = None,
    ) -> float:
        wait = backoff
        logger.info(
            "llm.call_retried",
            provider=self._name,
            attempt=attempt + 1,
            max_attempts=max_attempts if max_attempts is not None else _MAX_RETRIES,
            wait_sec=wait,
            stream=stream,
            reason=reason,
            partial_sse_lines=partial_sse_lines or None,
        )
        await asyncio.sleep(wait)
        return backoff * _BACKOFF_MULTIPLIER

    async def _finalize_upstream_error(
        self, err: LLMUpstreamError, attempt: int
    ) -> LLMUpstreamError:
        final = upstream_error(
            err.message,
            status=err.details.get("upstream_status", 500),
            body=err.details.get("upstream_body_preview"),
            retry_attempts=attempt + 1,
        )
        raise await self._attach_sub2api_diagnosis(final) from err

    async def _request_with_retry(self, payload: dict) -> dict:
        last_error: Exception | None = None
        backoff = _INITIAL_BACKOFF
        self._ensure_client_open()
        for attempt in range(_IO_ATTEMPT_CEILING):
            try:
                self._ensure_client_open()
                response = await self._client.post(
                    "/chat/completions",
                    json=payload,
                    headers=_request_attribution_headers() or None,
                )
                body = response.content if response.status_code >= 400 else None
                self._raise_for_status(
                    response.status_code, backoff, response.headers, body=body, attempt=attempt
                )
                return response.json()
            except LLMUpstreamError as e:
                last_error = e
                if not e.retryable or not self._can_retry_attempt(attempt):
                    await self._finalize_upstream_error(e, attempt)
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=backoff,
                    stream=False,
                    reason=f"upstream_{e.details.get('upstream_status', 500)}",
                )
            except (LLMRateLimitError, LLMError) as e:
                last_error = e
                max_attempts = (
                    _RATE_LIMIT_MAX_RETRIES
                    if isinstance(e, LLMRateLimitError)
                    else _MAX_RETRIES
                )
                if not e.retryable or not self._can_retry_attempt(
                    attempt, max_attempts=max_attempts
                ):
                    raise
                retry_after = e.retry_after if isinstance(e, LLMRateLimitError) else None
                wait, raw_retry_after = _retry_wait(retry_after, backoff)
                logger.info(
                    "llm.call_retried",
                    provider=self._name,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    wait_sec=wait,
                    retry_after_sec=raw_retry_after,
                    stream=False,
                    reason=type(e).__name__,
                )
                await asyncio.sleep(wait)
                backoff *= _BACKOFF_MULTIPLIER
            except RuntimeError as e:
                translated = self._translate_closed_client(e)
                if isinstance(translated, LLMClientClosedError):
                    raise translated from e
                raise
            except httpx.TimeoutException as e:
                last_error = LLMTimeoutError(f"连接 {self._name} 超时，请检查网络后重试")
                is_connect = isinstance(e, httpx.ConnectTimeout)
                max_attempts = _CONNECT_MAX_RETRIES if is_connect else _MAX_RETRIES
                if not self._can_retry_attempt(attempt, max_attempts=max_attempts):
                    raise last_error from e
                retry_backoff = _CONNECT_INITIAL_BACKOFF if is_connect else backoff
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=retry_backoff,
                    stream=False,
                    reason="connect_timeout" if is_connect else "timeout",
                    max_attempts=max_attempts,
                )
            except httpx.HTTPError as e:
                last_error = self._network_error_to_llm(e)
                is_connect = self._is_connect_failure(e)
                max_attempts = _CONNECT_MAX_RETRIES if is_connect else _MAX_RETRIES
                if not last_error.retryable or not self._can_retry_attempt(
                    attempt, max_attempts=max_attempts
                ):
                    raise last_error from e
                retry_backoff = _CONNECT_INITIAL_BACKOFF if is_connect else backoff
                backoff = await self._sleep_before_retry(
                    attempt=attempt,
                    backoff=retry_backoff,
                    stream=False,
                    reason=type(e).__name__,
                    max_attempts=max_attempts,
                )
        raise last_error or LLMError(f"{self._name} 多次重试后仍失败，请稍后重试")

    async def probe(self, *, model: str) -> None:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"连接 {self._name} 超时，请检查网络后重试") from e
        except httpx.HTTPError as e:
            raise LLMError(f"无法连接 {self._name}：{e}") from e
        code = response.status_code
        if code < 300 or code == 429:
            return
        if code in (401, 403):
            raise LLMError(f"{self._name} API Key 无效或无权限（鉴权失败），请检查后重试")
        if code == 402:
            raise LLMInsufficientBalanceError(
                f"{self._name} API Key 有效，但账户余额不足，请充值后使用。"
            )
        if code == 404:
            raise LLMError(f"{self._name} 接口地址不可达（404），请检查 base_url 配置")
        if code >= 500:
            raise LLMError(f"{self._name} 服务端错误（{code}），请稍后再试")
        raise LLMError(f"{self._name} 连通测试失败（HTTP {code}）")

    async def probe_tools(self, *, model: str) -> bool | None:
        """Probe whether the endpoint *accepts* tool calling (three-state).

        - ``True``: strong evidence — response included ``tool_calls``
        - ``False``: 4xx body clearly rejects tools / tools parameters
        - ``None``: unknown — 2xx without tool_calls, timeout, network, 429,
          auth errors, or any ambiguous failure (never pretend False)

        Strategy: try ``tool_choice="required"`` first; on HTTP 400 (e.g. DeepSeek
        V4 rejecting forced tool_choice) fall back to omitting tool_choice.
        """
        outcome = await self._probe_tools_once(model=model, tool_choice="required")
        if outcome == _PROBE_TOOLS_RETRY:
            outcome = await self._probe_tools_once(model=model, tool_choice=None)
        if outcome == _PROBE_TOOLS_RETRY:
            return None
        return outcome

    async def _probe_tools_once(
        self, *, model: str, tool_choice: str | None
    ) -> bool | None | Literal["retry_without_required"]:
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": "Call the dummy tool."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "dummy_probe",
                        "description": "Connectivity probe",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            "max_tokens": _PROBE_TOOLS_MAX_TOKENS,
            "stream": False,
        }
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except (httpx.TimeoutException, httpx.HTTPError):
            return None
        code = response.status_code
        if code == 429 or code >= 500:
            return None
        if 200 <= code < 300:
            try:
                data = response.json()
            except ValueError:
                return None
            choices = data.get("choices") or []
            if not choices:
                return None
            message = choices[0].get("message") or {}
            return True if message.get("tool_calls") else None
        # Any 400 under forced tool_choice → retry without it (DeepSeek V4 etc.).
        if code == 400 and tool_choice == "required":
            return _PROBE_TOOLS_RETRY
        try:
            body = response.text or ""
        except Exception:  # noqa: BLE001 — body read is best-effort for classification
            body = ""
        if _is_tools_unsupported_rejection(code, body):
            return False
        return None

    async def list_models(self) -> list[str]:
        """Discover the endpoint's real model ids via the OpenAI-standard ``GET /models``.

        Returns the ``data[].id`` list (order preserved, de-duped). Raises ``LLMError``
        on any transport / non-2xx / malformed-body failure so the caller (the model
        catalog) can degrade gracefully instead of surfacing a 500 — this is a
        best-effort discovery probe, never a turn-critical path.
        """
        try:
            response = await self._client.get("/models")
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"连接 {self._name} 超时，请检查网络后重试") from e
        except httpx.HTTPError as e:
            raise LLMError(f"无法连接 {self._name}：{e}") from e
        code = response.status_code
        if code in (401, 403):
            raise LLMAuthError(
                provider_name=self._name,
                upstream_status=code,
                upstream_body_preview=body_preview(response.content),
            )
        if code == 402:
            raise LLMInsufficientBalanceError()
        if code >= 400:
            raise LLMError(f"{self._name} 列出模型失败（HTTP {code}）")
        try:
            data = response.json()
        except ValueError as e:
            raise LLMError(f"{self._name} 模型列表响应格式无效") from e
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LLMError(f"{self._name} 模型列表响应缺少 data 字段")
        ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id and model_id not in seen:
                seen.add(model_id)
                ids.append(model_id)
        return ids

    def _ensure_client_open(self) -> None:
        """Fail fast with a typed non-retryable error when turn teardown closed us."""
        if self._client.is_closed:
            raise LLMClientClosedError()

    @staticmethod
    def _translate_closed_client(exc: BaseException) -> BaseException:
        if is_llm_client_closed_error(exc) and not isinstance(exc, LLMClientClosedError):
            msg = str(exc).strip()
            return LLMClientClosedError(msg) if msg else LLMClientClosedError()
        return exc

    async def close(self) -> None:
        await self._client.aclose()

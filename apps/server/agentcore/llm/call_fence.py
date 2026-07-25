"""Leaf LLM call observation fence — wrap providers from ``build_provider``.

Observes every logical ``complete`` / ``stream`` invocation (success → ``llm.call``,
failure → ``llm.call_failed``). Does **not** retry, swap models, or alter chunk
contracts (``stream_reset`` / ``aborted`` pass through unchanged).

Inner provider I/O retries stay inside the leaf; this fence sees one attempt per
outer call (``attempt`` defaults to 1; exhausted upstream retries surface via
exception ``retry_attempts`` on failure).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, cast

from agentcore.core.errors import AgentCoreError
from agentcore.llm.observability import log_llm_call, log_llm_call_failed
from agentcore.llm.provider.protocol import (
    LLMChunk,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)


class ObservingLLMProvider:
    """Observation-only decorator around a leaf :class:`LLMProvider`."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return str(getattr(self._inner, "name", getattr(self._inner, "_name", "llm")))

    @property
    def _name(self) -> str:
        # Compat for call sites that read ``getattr(llm, "_name", …)``.
        return str(getattr(self._inner, "_name", self.name))

    def clone(self) -> ObservingLLMProvider:
        clone_fn = getattr(self._inner, "clone", None)
        if callable(clone_fn):
            return ObservingLLMProvider(clone_fn())
        return ObservingLLMProvider(self._inner)

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            await close()

    def _provider_name(self) -> str | None:
        name = getattr(self._inner, "name", None) or getattr(self._inner, "_name", None)
        return str(name) if name else None

    @staticmethod
    def _attempt_from_exc(exc: BaseException) -> int:
        """Map leaf ``retry_attempts`` (0-based fail index) → 1-based attempt."""
        if isinstance(exc, AgentCoreError):
            raw = exc.details.get("retry_attempts")
            if isinstance(raw, int) and raw >= 0:
                return raw + 1
        return 1

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.monotonic()
        try:
            response = await self._inner.complete(request)
        except Exception as e:
            log_llm_call_failed(
                scenario=request.scenario,
                model=request.model,
                latency_ms=int((time.monotonic() - start) * 1000),
                attempt=self._attempt_from_exc(e),
                error=str(e),
                error_type=type(e).__name__,
                stream=False,
            )
            raise
        log_llm_call(
            scenario=request.scenario,
            model=response.model or request.model,
            usage=response.usage,
            finish_reason=response.finish_reason,
            latency_ms=response.latency_ms
            if response.latency_ms
            else int((time.monotonic() - start) * 1000),
            stream=False,
            messages=request.messages,
            content=response.content,
            reasoning=response.reasoning_content,
            tool_names=[tc.function.name for tc in response.tool_calls]
            if response.tool_calls
            else None,
            provider_name=self._provider_name(),
            attempt=1,
        )
        return response

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        start = time.monotonic()
        usage: TokenUsage | None = None
        finish_reason: str | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_names: list[str] = []
        seen_tool_names: set[str] = set()
        aborted = False
        outcome = "open"
        try:
            # Protocol types ``async def stream`` as Coroutine→AsyncIterator; real
            # leaves are async generators (call returns the iterator, no await).
            async for chunk in cast(AsyncIterator[LLMChunk], self._inner.stream(request)):
                if chunk.aborted:
                    aborted = True
                if chunk.stream_reset:
                    content_parts.clear()
                    reasoning_parts.clear()
                    tool_names.clear()
                    seen_tool_names.clear()
                    usage = None
                    finish_reason = None
                    aborted = False
                else:
                    if chunk.delta_content:
                        content_parts.append(chunk.delta_content)
                    if chunk.delta_reasoning:
                        reasoning_parts.append(chunk.delta_reasoning)
                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason
                    if chunk.usage is not None:
                        usage = chunk.usage
                    if chunk.delta_tool_calls:
                        for tc in chunk.delta_tool_calls:
                            name = tc.function_name
                            if name and name not in seen_tool_names:
                                seen_tool_names.add(name)
                                tool_names.append(name)
                yield chunk
            outcome = "ok"
        except GeneratorExit:
            if outcome != "ok":
                outcome = "closed"
            raise
        except Exception as e:
            outcome = "failed"
            log_llm_call_failed(
                scenario=request.scenario,
                model=request.model,
                latency_ms=int((time.monotonic() - start) * 1000),
                attempt=self._attempt_from_exc(e),
                error=str(e),
                error_type=type(e).__name__,
                stream=True,
            )
            raise
        finally:
            if outcome == "ok":
                log_llm_call(
                    scenario=request.scenario,
                    model=request.model,
                    usage=usage,
                    finish_reason=finish_reason
                    or ("aborted" if aborted else ("tool_calls" if tool_names else "stop")),
                    latency_ms=int((time.monotonic() - start) * 1000),
                    stream=True,
                    messages=request.messages,
                    content="".join(content_parts) or None,
                    reasoning="".join(reasoning_parts) or None,
                    tool_names=tool_names or None,
                    provider_name=self._provider_name(),
                    attempt=1,
                )
            elif outcome == "closed":
                log_llm_call_failed(
                    scenario=request.scenario,
                    model=request.model,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    attempt=1,
                    error="stream_closed_by_consumer",
                    error_type="GeneratorExit",
                    stream=True,
                )


def observe_provider(provider: LLMProvider) -> LLMProvider:
    """Wrap ``provider`` once (idempotent)."""
    if isinstance(provider, ObservingLLMProvider):
        return provider
    # Same async-generator vs Protocol Coroutine mismatch as ``stream`` above.
    return cast(LLMProvider, ObservingLLMProvider(provider))


def unwrap_provider(provider: Any) -> Any:
    """Return the leaf under an observing fence (tests / diagnostics)."""
    if isinstance(provider, ObservingLLMProvider):
        return provider._inner
    return provider

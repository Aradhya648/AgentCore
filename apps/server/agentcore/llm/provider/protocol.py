"""LLMProvider protocol and core data types."""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# Shared retry / backoff knobs for provider I/O and engine stream consumers.
# Public so runtime.engine.stream (and tests) never touch provider privates.
MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
BACKOFF_MULTIPLIER = 2.0
# Connect-class failures (ConnectTimeout / ConnectError): fail fast — 1 retry,
# 1s backoff (worst case ≈ connect_timeout + 1s + connect_timeout ≈ 21s with
# the 10s connect ceiling). Read timeout / 5xx keep MAX_RETRIES above.
CONNECT_MAX_RETRIES = 2
CONNECT_INITIAL_BACKOFF = 1.0
# 429 / Retry-After: allow more attempts than generic I/O so short exponential
# Retry-After chains (2→4→8…) are actually waited, not abandoned on the 3rd hit.
RATE_LIMIT_MAX_RETRIES = 6
# Honor HTTP Retry-After up to this many seconds. Upstream sometimes returns
# hour-scale values (e.g. 3600) that starve short outer budgets (title 20s /
# followups 15s) even though a second-scale retry then succeeds — past this
# cap we fall back to exponential backoff and log the raw header separately.
MAX_RETRY_AFTER = 30.0


@dataclass
class ToolCallFunction:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction = field(default_factory=lambda: ToolCallFunction("", ""))


@dataclass
class ToolCallDelta:
    index: int
    id: str | None = None
    function_name: str | None = None
    arguments_delta: str | None = None


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None


@dataclass
class LLMRequest:
    messages: list[LLMMessage]
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict] | None = None
    tool_choice: Literal["auto", "none", "required"] = "auto"
    stream: bool = True
    scenario: str = "chat"
    # None = omit (provider default). False/True → DeepSeek V4 ``thinking.type``.
    thinking: bool | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cache_hit_tokens=self.cache_hit_tokens + other.cache_hit_tokens,
            cache_miss_tokens=self.cache_miss_tokens + other.cache_miss_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "reasoning": self.reasoning_tokens,
            "cache_hit": self.cache_hit_tokens,
            "cache_miss": self.cache_miss_tokens,
        }

    @classmethod
    def from_usage_dict(cls, usage: Mapping[str, int]) -> "TokenUsage":
        return cls(
            input_tokens=usage.get("input", 0),
            output_tokens=usage.get("output", 0),
            reasoning_tokens=usage.get("reasoning", 0),
            cache_hit_tokens=usage.get("cache_hit", 0),
            cache_miss_tokens=usage.get("cache_miss", 0),
        )

    @classmethod
    def from_openai_wire(cls, usage_data: Mapping[str, Any]) -> "TokenUsage":
        """Parse a ``usage`` block from an OpenAI-compatible ``/chat/completions`` reply.

        The single wire-usage parser (gateway / vision reader / inference proxy all
        route here). Two prompt-cache dialects exist in the wild and we must read
        both — a cache hit the parser can't see is billed as a full miss for platform
        models and invisible in usage observability:

        - **DeepSeek style** (explicit split): ``prompt_cache_hit_tokens`` +
          ``prompt_cache_miss_tokens``. Preferred when present (authoritative).
        - **OpenAI style** (hit only): ``prompt_tokens_details.cached_tokens`` is the
          cached portion; the uncached remainder is derived as
          ``prompt_tokens − cached_tokens`` (clamped at 0). Mirrors the pricing-side
          reconciliation ``cache_miss = max(input − hit, miss)`` so the two layers
          agree (llm/pricing.py::calculate_cost).

        Neither present → both 0; pricing then reconciles the whole prompt as a miss.
        Values ride ``int(x or 0)`` so ``null`` fields from lenient proxies parse as 0.
        """
        completion_details = usage_data.get("completion_tokens_details") or {}
        prompt_details = usage_data.get("prompt_tokens_details") or {}
        input_tokens = int(usage_data.get("prompt_tokens", 0) or 0)
        cache_hit = int(usage_data.get("prompt_cache_hit_tokens", 0) or 0)
        cache_miss = int(usage_data.get("prompt_cache_miss_tokens", 0) or 0)
        if not cache_hit and not cache_miss:
            cached = int(prompt_details.get("cached_tokens", 0) or 0)
            if cached:
                cache_hit = cached
                cache_miss = max(input_tokens - cached, 0)
        return cls(
            input_tokens=input_tokens,
            output_tokens=int(usage_data.get("completion_tokens", 0) or 0),
            reasoning_tokens=int(completion_details.get("reasoning_tokens", 0) or 0),
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
        )


@dataclass
class LLMResponse:
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"] = "stop"
    model: str = ""
    latency_ms: int = 0
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None


@dataclass
class LLMChunk:
    delta_content: str | None = None
    delta_reasoning: str | None = None
    delta_tool_calls: list[ToolCallDelta] | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None
    # Control signals (mutually exclusive with normal deltas when set):
    # stream_reset — transparent pre-commit retry; consumer must drop ephemeral
    #   reasoning and reset the live view before the next attempt's chunks.
    # aborted — post-commit disconnect; consumer keeps the partial and must not
    #   treat the stream as a hard raise/discard.
    stream_reset: bool = False
    aborted: bool = False


class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    # Sync ``def`` (not ``async def``): real leaves are async generators — calling
    # ``stream()`` returns an AsyncIterator immediately; mypy models ``async def``
    # Protocol stubs as Coroutine[…, AsyncIterator] which breaks callers.
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]: ...

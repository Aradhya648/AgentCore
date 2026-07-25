"""One-round LLM streaming for the ReAct loop."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from agentcore.config import settings
from agentcore.core.errors import LLMTimeoutError
from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import (
    BACKOFF_MULTIPLIER,
    INITIAL_BACKOFF,
    MAX_RETRIES,
    LLMChunk,
    LLMProvider,
    LLMRequest,
    TokenUsage,
    ToolCall,
    ToolCallFunction,
)

from .constants import TOOL_PROGRESS_STEP

logger = get_logger(__name__)

# Wall-clock cap for pre-commit stall retries: without this, a true stall costs
# ``idle × MAX_RETRIES`` (+ backoff). Factor 2 keeps production (idle≈100s) under
# ~200s worst case while still allowing full ``MAX_RETRIES`` when idle is short
# (unit tests). Attempt count still aligns with provider ``MAX_RETRIES``.
_STALL_BUDGET_IDLE_MULTIPLIER = 2.0


def _chunk_resets_idle_timer(chunk: LLMChunk) -> bool:
    """Whether a provider chunk counts as forward progress for the stall gate.

    Some upstreams emit periodic SSE frames with empty ``delta`` objects (keepalive /
    heartbeat). Those must NOT reset the per-chunk idle ceiling — otherwise a hung
    stream after the last real token never trips ``llm.stream_stalled`` and the whole
    turn (including a detached SSE client) stays ``live_running`` indefinitely.
    """
    if chunk.stream_reset or chunk.aborted:
        return True
    if chunk.delta_content or chunk.delta_reasoning:
        return True
    if chunk.delta_tool_calls:
        return True
    if chunk.finish_reason or chunk.usage is not None:
        return True
    return bool(chunk.empty_diagnosis or chunk.empty_raw_preview)


@dataclass(frozen=True)
class StreamRoundResult:
    """Outcome of one streamed LLM call (including post-commit abort salvage)."""

    content: str
    reasoning: str
    tool_calls: list[ToolCall] | None
    usage: TokenUsage | None
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None
    aborted: bool = False


async def stream_llm_round(
    llm: LLMProvider,
    request: LLMRequest,
    emit_content: Callable[[str], None],
    emit_reasoning: Callable[[str], None],
    on_tool_progress: Callable[[str, int], None] | None = None,
    on_reset: Callable[[str], None] | None = None,
) -> StreamRoundResult:
    """Stream one LLM call. Returns accumulated text plus an optional aborted flag.

    Consumes provider control signals:
    - ``stream_reset`` — clear local accumulators and reset the live view (CEO
      ``content_reset`` / worker ``run_output_reset`` via ``on_reset``).
    - ``aborted`` — keep the partial and return normally (no raise).

    Pre-commit idle stall (no content / tool_call yet; reasoning does not commit)
    is retryable at this layer — aligned with the provider's pre-commit transparent
    retry philosophy. Post-commit stall salvages the partial via ``aborted``.
    """

    idle = settings.engine_llm_stream_idle_timeout_seconds
    start = time.monotonic()
    budget = (idle * _STALL_BUDGET_IDLE_MULTIPLIER) if idle > 0 else None
    backoff = INITIAL_BACKOFF
    last_stall_error: LLMTimeoutError | None = None

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tc_accumulators: dict[int, dict] = {}
    tc_progress_at: dict[int, int] = {}
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None
    aborted = False

    def _clear_accumulators() -> None:
        content_parts.clear()
        reasoning_parts.clear()
        tc_accumulators.clear()
        tc_progress_at.clear()

    def _reset_attempt_state() -> None:
        _clear_accumulators()
        nonlocal usage, finish_reason, empty_diagnosis, empty_raw_preview, aborted
        usage = None
        finish_reason = None
        empty_diagnosis = None
        empty_raw_preview = None
        aborted = False
        if on_reset is not None:
            on_reset("retry")

    loop = asyncio.get_running_loop()

    for attempt in range(MAX_RETRIES):
        if budget is not None and (time.monotonic() - start) >= budget:
            if last_stall_error is not None:
                raise last_stall_error
            break
        if attempt > 0:
            _reset_attempt_state()

        try:
            # 流式停滞闸 (卡死根因): consume the stream under a per-chunk IDLE ceiling. The
            # deadline resets only on *progress* chunks (content / reasoning / tool_calls /
            # finish / usage) — empty upstream keepalives must not defer stall detection.
            # ``0`` disables the gate. Post-commit stall salvages the partial; pre-commit
            # stall retries (below) then raises.
            async with asyncio.timeout(idle if idle > 0 else None) as cm:
                async for chunk in llm.stream(request):
                    if idle > 0 and _chunk_resets_idle_timer(chunk):
                        cm.reschedule(loop.time() + idle)

                    if chunk.stream_reset:
                        _clear_accumulators()
                        usage = None
                        finish_reason = None
                        empty_diagnosis = None
                        empty_raw_preview = None
                        if on_reset is not None:
                            on_reset("retry")
                        continue

                    if chunk.aborted:
                        aborted = True
                        break

                    if chunk.empty_diagnosis:
                        empty_diagnosis = chunk.empty_diagnosis
                    if chunk.empty_raw_preview:
                        empty_raw_preview = chunk.empty_raw_preview

                    if chunk.delta_content:
                        content_parts.append(chunk.delta_content)
                        emit_content(chunk.delta_content)

                    if chunk.delta_reasoning:
                        reasoning_parts.append(chunk.delta_reasoning)
                        emit_reasoning(chunk.delta_reasoning)

                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason

                    if chunk.delta_tool_calls:
                        for tc_delta in chunk.delta_tool_calls:
                            idx = tc_delta.index
                            if idx not in tc_accumulators:
                                tc_accumulators[idx] = {
                                    "id": tc_delta.id or "",
                                    "name": tc_delta.function_name or "",
                                    "arguments": "",
                                }
                            else:
                                if tc_delta.id:
                                    tc_accumulators[idx]["id"] = tc_delta.id
                                if tc_delta.function_name:
                                    tc_accumulators[idx]["name"] = tc_delta.function_name
                            if tc_delta.arguments_delta:
                                tc_accumulators[idx]["arguments"] += tc_delta.arguments_delta
                            if on_tool_progress is not None:
                                name = tc_accumulators[idx]["name"]
                                chars = len(tc_accumulators[idx]["arguments"])
                                last = tc_progress_at.get(idx)
                                if name and (last is None or chars - last >= TOOL_PROGRESS_STEP):
                                    tc_progress_at[idx] = chars
                                    on_tool_progress(name, chars)

                    if chunk.usage:
                        usage = chunk.usage
        except TimeoutError:
            committed = bool(content_parts) or bool(tc_accumulators)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "llm.stream_stalled",
                scenario=request.scenario,
                model=request.model,
                idle_seconds=idle,
                elapsed_ms=elapsed_ms,
                content_chars=sum(len(p) for p in content_parts),
                reasoning_chars=sum(len(p) for p in reasoning_parts),
                committed=committed,
                attempt=attempt + 1,
                max_attempts=MAX_RETRIES,
            )
            if committed:
                aborted = True
                break

            last_stall_error = LLMTimeoutError(
                "模型流式响应停滞（长时间无输出），请稍后重试"
            )
            can_retry = attempt < MAX_RETRIES - 1
            if budget is not None:
                # Need room for another idle window; otherwise raise now.
                remaining = budget - (time.monotonic() - start)
                if remaining < idle:
                    can_retry = False
            if not can_retry:
                raise last_stall_error from None

            logger.info(
                "llm.call_retried",
                provider=getattr(llm, "_name", "llm"),
                attempt=attempt + 1,
                max_attempts=MAX_RETRIES,
                wait_sec=backoff,
                stream=True,
                reason="stream_stall",
            )
            await asyncio.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER
            continue

        # Stream finished normally (or aborted mid-stream) — leave the retry loop.
        break
    else:
        # Exhausted attempts without a normal break (budget / retries).
        if last_stall_error is not None:
            raise last_stall_error

    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)

    # Incomplete tool-call deltas after abort are not executable — drop them so the
    # engine keeps prose only (设计: 保留半成品正文, 不执行残缺 tool_calls).
    tool_calls: list[ToolCall] | None = None
    if tc_accumulators and not aborted:
        tool_calls = []
        for _idx in sorted(tc_accumulators):
            acc = tc_accumulators[_idx]
            tool_calls.append(
                ToolCall(
                    id=acc["id"],
                    function=ToolCallFunction(
                        name=acc["name"],
                        arguments=acc["arguments"],
                    ),
                )
            )

    # Per-call ``llm.call`` is emitted by the ``observe_provider`` fence on the
    # leaf (build_provider) when each ``stream()`` completes — not here — so
    # stall retries and proxy paths share one emit point without double-metering.

    return StreamRoundResult(
        content=content,
        reasoning=reasoning,
        tool_calls=tool_calls,
        usage=usage,
        empty_diagnosis=empty_diagnosis,
        empty_raw_preview=empty_raw_preview,
        aborted=aborted,
    )

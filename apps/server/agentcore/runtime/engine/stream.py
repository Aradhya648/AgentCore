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

# Pre-commit stall retry budget, measured in idle *windows* (not a pristine
# ``remaining >= idle`` wall check). Factor 2 → first attempt + one transparent
# retry in production (idle≈100s ⇒ ~200s stall-wait ceiling) while still allowing
# full provider ``MAX_RETRIES`` when tests raise the multiplier. Do not treat
# first-window overshoot (TTFT / scheduling ms) as "no room for retry".
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

    # Phase-0 TTFT: only the first CEO/captain stream of the turn (cost_role).
    from agentcore.core.log_context import get_log_value
    from agentcore.runtime.turn_latency import get_turn_latency

    latency_probe = get_turn_latency()
    record_ttft = bool(
        latency_probe is not None
        and get_log_value("cost_role") == "captain"
        and latency_probe.begin_captain_stream()
    )

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
        if record_ttft and latency_probe is not None:
            latency_probe.clear_ttft()
        if on_reset is not None:
            on_reset("retry")

    loop = asyncio.get_running_loop()
    # Once ``llm.call_retried`` is emitted we must actually open the next stream —
    # never wall-clock-abort at the top of the next iteration (no post-retry 收口).
    retry_committed = False
    max_stall_windows = max(1, int(_STALL_BUDGET_IDLE_MULTIPLIER))

    try:
        for attempt in range(MAX_RETRIES):
            if (
                budget is not None
                and not retry_committed
                and (time.monotonic() - start) >= budget
            ):
                if last_stall_error is not None:
                    raise last_stall_error
                break
            retry_committed = False
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
                            if record_ttft and latency_probe is not None:
                                latency_probe.clear_ttft()
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
                            if record_ttft and latency_probe is not None:
                                latency_probe.note_content_or_tool_chunk()

                        if chunk.delta_reasoning:
                            reasoning_parts.append(chunk.delta_reasoning)
                            emit_reasoning(chunk.delta_reasoning)
                            if record_ttft and latency_probe is not None:
                                latency_probe.note_reasoning_chunk()

                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason

                        if chunk.delta_tool_calls:
                            if record_ttft and latency_probe is not None:
                                latency_probe.note_content_or_tool_chunk()
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
                                    if name and (
                                        last is None or chars - last >= TOOL_PROGRESS_STEP
                                    ):
                                        tc_progress_at[idx] = chars
                                        on_tool_progress(name, chars)

                        if chunk.usage:
                            usage = chunk.usage
            except TimeoutError:
                committed = bool(content_parts) or bool(tc_accumulators)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                stall_extra: dict[str, object] = {}
                cred_src = get_log_value("credential_source")
                if cred_src:
                    stall_extra["credential_source"] = cred_src
                provider_id = get_log_value("provider_id")
                if provider_id:
                    stall_extra["provider_id"] = provider_id
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
                    **stall_extra,
                )
                if committed:
                    aborted = True
                    break

                last_stall_error = LLMTimeoutError("模型流式响应停滞（长时间无输出），请稍后重试")
                # Window accounting: attempt 0 stall consumes window 1. With
                # multiplier=2, allow one more stream attempt; do NOT use
                # ``remaining < idle`` (first-window overshoot made retries dead).
                windows_used = attempt + 1
                can_retry = attempt < MAX_RETRIES - 1 and windows_used < max_stall_windows
                if budget is not None and (time.monotonic() - start) >= budget:
                    # Already past wall budget — don't claim a retry we won't start.
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
                retry_committed = True
                continue

            # Stream finished normally (or aborted mid-stream) — leave the retry loop.
            break
        else:
            # Exhausted attempts without a normal break (budget / retries).
            if last_stall_error is not None:
                raise last_stall_error
    finally:
        if record_ttft and latency_probe is not None:
            latency_probe.end_captain_stream()

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

"""SSE StreamingResponse wrapper.

Consumes an EventSink and serializes events as text/event-stream lines.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from starlette.responses import StreamingResponse

from agentcore.runtime.events import EventSink, SSEEvent

# Idle keep-alive cadence. When the producer is mid-thought (no events queued),
# the generator emits a comment frame this often so the connection keeps flowing
# bytes; the client's stall watchdog uses those bytes to tell "still working"
# from "dead stream". Must stay well under the client idle timeout (see
# streamConversation.ts) so a slow-but-alive turn is never mistaken for a drop.
_HEARTBEAT_INTERVAL_S = 15.0


def _format_sse(event: SSEEvent, *, seq: int | None = None) -> str:
    """Serialize one SSE frame. Envelope JSON (type/timestamp/payload) is unchanged.

    Optional ``seq`` (or ``event.seq``) emits a standard SSE ``id:`` line (journal seq
    for DURABLE facts; ``Last-Event-ID`` resume). EPHEMERAL / delta events omit ``seq``
    so they attach after the nearest durable id.
    """
    id_seq = seq if seq is not None else event.seq
    data = json.dumps(
        {"type": event.type, "timestamp": event.timestamp, "payload": event.payload},
        ensure_ascii=False,
    )
    parts = [f"event: {event.type}"]
    if id_seq is not None:
        parts.append(f"id: {id_seq}")
    parts.append(f"data: {data}")
    return "\n".join(parts) + "\n\n"


async def _event_generator(
    sink: EventSink,
    producer: asyncio.Task | None,
    *,
    detach_on_disconnect: bool = False,
) -> AsyncIterator[str]:
    try:
        while True:
            try:
                event = await asyncio.wait_for(sink.get(), _HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                # No event for a while — the turn is alive but thinking. Emit an
                # SSE comment line (begins with ':'): the client ignores it at the
                # parse layer but counts the bytes as liveness, so its watchdog
                # holds. Cancelling the queue.get() here is loss-safe on 3.12.
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield _format_sse(event)
    except (asyncio.CancelledError, GeneratorExit):
        # The client disconnected before the stream finished. Two policies:
        #
        # - detach_on_disconnect (chat turns, 执行与请求解耦 C1 · slice 1a): the run
        #   is detached + tracked in the TurnRunRegistry, so a dropped connection
        #   must NOT kill it (案例 1: 断连即丢交付). Detach the sink so the unread
        #   queue stops growing; the run finishes + persists in the background, and
        #   an explicit 停止 routes through POST .../stop instead.
        # - else (handoff archive/dispatch/apply SSEs): cancel the producer so it
        #   stops burning work for a response nobody will read.
        #
        # Normal completion (sink closed by the pipeline) skips this branch.
        if detach_on_disconnect:
            sink.detach()
        elif producer is not None and not producer.done():
            producer.cancel()
        raise


def sse_response(
    sink: EventSink,
    *,
    producer: asyncio.Task | None = None,
    detach_on_disconnect: bool = False,
) -> StreamingResponse:
    """Create a StreamingResponse that consumes an EventSink.

    Two client-disconnect policies (mutually exclusive):

    - ``producer`` (default): the background task feeding the sink is cancelled when
      the client disconnects, so generation stops together with the client. Used by
      the short handoff SSEs.
    - ``detach_on_disconnect=True``: the run is decoupled from the request (执行与请求
      解耦 C1 · slice 1a) — a disconnect only detaches the sink and the run keeps
      going + persists in the background; cancellation is done explicitly via the
      stop endpoint. Used by the chat-turn SSEs (send / regenerate / resume), which
      register their task in the ``TurnRunRegistry`` instead of passing it here.
    """
    return StreamingResponse(
        _event_generator(sink, producer, detach_on_disconnect=detach_on_disconnect),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _attach_generator(
    sink: EventSink,
    *,
    last_event_id: int | None = None,
) -> AsyncIterator[str]:
    """Replay a running turn's transcript, then tail it live (实时重连续看, C1 · 1b).

    Used by the attach endpoint when a client re-connects to a still-running detached
    run. ``take_over`` (synchronous) hands us the replay snapshot and re-arms the SSE
    queue; we flush the snapshot, then drain new events exactly like the primary
    generator (same heartbeat, same disconnect policy). Because the run is detached,
    a disconnect here just detaches again — it never cancels the turn.

    With ``Last-Event-ID`` (P3): skip in-memory ``_history``; replay the turn's **full**
    durable journal + stream_state synthetic deltas (header value observational —
    clear-then-fold), then live tail.
    """
    if last_event_id is None:
        # Same-process fast path: ``take_over`` history + synthetic ``message_end``
        # when the turn already finished while detached (aligned with cursor replay).
        replay = sink.take_over()
    else:
        # Re-arm the live queue (discard unread backlog) without using _history.
        sink.take_over()
        from agentcore.runtime.events.attach_replay import build_cursor_replay

        turn_id = sink._message_id
        if turn_id:
            memory = sink.stream_memory_snapshot()
            agent_ids = (
                sink._checkpointer.run_agent_ids() if sink._checkpointer is not None else {}
            )
            replay = await build_cursor_replay(
                turn_id=turn_id,
                after_seq=last_event_id,
                memory_channels=memory,
                memory_agent_ids=agent_ids,
            )
        else:
            replay = []
    try:
        for event in replay:
            yield _format_sse(event)
        # Hot re-hang: after journal/history replay (DURABLE-only for cursor path)
        # and after take_over cleared the live queue (no double delivery), re-emit
        # still-open CLIENT_TOOL + answerable hot cards (approval / delegation /
        # user escalation) so a refresh cannot drop an in-process pending Future.
        conv_id = sink.conversation_id
        if conv_id:
            from agentcore.runtime.events.client_tool_reattach import (
                pending_client_tool_events,
            )
            from agentcore.runtime.events.hot_interaction_reattach import (
                pending_hot_interaction_events,
            )

            for event in pending_client_tool_events(conv_id):
                yield _format_sse(event)
            for event in pending_hot_interaction_events(conv_id):
                yield _format_sse(event)
        while True:
            try:
                event = await asyncio.wait_for(sink.get(), _HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield _format_sse(event)
    except (asyncio.CancelledError, GeneratorExit):
        sink.detach()
        raise


def sse_attach_response(
    sink: EventSink,
    *,
    last_event_id: int | None = None,
) -> StreamingResponse:
    """Stream a re-attaching client the replay-then-tail of a live detached run (1b).

    The run keeps executing independently (执行与请求解耦); this is a pure observer that
    replays what the client missed and follows along, so dropping it again is harmless
    (detach, never cancel — an explicit 停止 still goes through ``POST .../stop``).
    """
    return StreamingResponse(
        _attach_generator(sink, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _queued_turn_generator(
    *,
    conversation_id: str,
    queue_id: str,
    position: int,
    queue_depth: int,
    started: asyncio.Future[EventSink],
    degraded_from: str | None = None,
) -> AsyncIterator[str]:
    """Emit ``turn_queued``, wait for drain, then consume the live turn sink (发送即有流).

    Disconnect closes the「断连 → detached」loop at EVERY stage (the turn itself is
    never cancelled here — D9 排队断连不 cancel 回合):

    - **waiting** (``started`` pending; drop at the ``turn_queued`` yield or at the
      await) → cancel ``started`` so drain starts the turn detached;
    - **handoff landed but never consumed** (drain ``set_result`` raced the disconnect
      — GeneratorExit lands before this generator resumes with the sink) → detach the
      HANDED sink, else it strands as a primary observer nobody reads;
    - **streaming** → ``_event_generator``'s own except detaches (same as primary
      send); our except re-detaches, which is an idempotent no-op.
    """
    from agentcore.runtime.events import turn_queued

    sink: EventSink | None = None
    try:
        yield _format_sse(
            turn_queued(
                queue_id=queue_id,
                position=position,
                queue_depth=queue_depth,
                conversation_id=conversation_id,
                degraded_from=degraded_from,
            )
        )
        sink = await started
        # Primary consumer of the drained turn (mirror send_message's detach policy).
        async for frame in _event_generator(sink, None, detach_on_disconnect=True):
            yield frame
    except (asyncio.CancelledError, GeneratorExit):
        if not started.done():
            started.cancel()
        else:
            handed = sink
            if handed is None and not started.cancelled() and started.exception() is None:
                handed = started.result()
            if handed is not None:
                handed.detach()
        raise


def sse_queued_response(
    *,
    conversation_id: str,
    queue_id: str,
    position: int,
    queue_depth: int,
    started: asyncio.Future[EventSink],
    degraded_from: str | None = None,
) -> StreamingResponse:
    """SSE for an enqueued POST: ``turn_queued`` then same-connection turn stream."""
    return StreamingResponse(
        _queued_turn_generator(
            conversation_id=conversation_id,
            queue_id=queue_id,
            position=position,
            queue_depth=queue_depth,
            started=started,
            degraded_from=degraded_from,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

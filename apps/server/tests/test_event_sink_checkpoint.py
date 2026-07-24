"""Tests for EventSink stream-segment durability (P1 · StreamCheckpointer).

Replaces the retired 10s ``messages.content`` checkpoint loop — mid-stream writes
now go to ``turn_stream_state`` via ``ConversationStore.upsert_stream_segments``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.runtime.events import (
    EventSink,
    content_delta,
    run_completed,
    run_failed,
    run_started,
)
from agentcore.runtime.events.stream_checkpointer import CHANNEL_CAPTAIN_CONTENT


@pytest.fixture
def segment_store():
    store = MagicMock()
    store.upsert_stream_segments = AsyncMock()
    with patch(
        "agentcore.conversation.store.get_conversation_store",
        return_value=store,
    ):
        yield store


@pytest.mark.asyncio
async def test_flush_persists_streamed_content(segment_store):
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    sink.emit(content_delta("hello "))
    sink.emit(content_delta("world"))

    await sink.flush_stream_state()

    segment_store.upsert_stream_segments.assert_awaited_once()
    kwargs = segment_store.upsert_stream_segments.await_args.kwargs
    assert kwargs["turn_id"] == "m1"
    channels = {ch: text for ch, text, _gen in kwargs["segments"]}
    assert channels[CHANNEL_CAPTAIN_CONTENT] == "hello world"


@pytest.mark.asyncio
async def test_flush_skips_when_nothing_dirty(segment_store):
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    sink.emit(content_delta("same"))

    await sink.flush_stream_state()
    await sink.flush_stream_state()

    # Second flush finds no dirty channels.
    assert segment_store.upsert_stream_segments.await_count == 1


@pytest.mark.asyncio
async def test_worker_run_completed_triggers_segment_flush(segment_store):
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    sink.emit(content_delta("after worker"))
    sink.emit(run_started("cap-1", "CEO", kind="captain"))
    sink.emit(run_completed("w1", "worker", output_summary="done", duration_ms=1))

    await asyncio.sleep(0)
    if sink._checkpointer and sink._checkpointer._flush_inflight:
        await sink._checkpointer._flush_inflight

    segment_store.upsert_stream_segments.assert_awaited()
    kwargs = segment_store.upsert_stream_segments.await_args.kwargs
    channels = {ch: text for ch, text, _gen in kwargs["segments"]}
    assert channels[CHANNEL_CAPTAIN_CONTENT] == "after worker"


@pytest.mark.asyncio
async def test_captain_run_completed_still_boundary_flushes(segment_store):
    """P1: any run terminal is a semantic boundary (incl. captain)."""
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    sink.emit(content_delta("captain reply"))
    sink.emit(run_started("cap-1", "CEO", kind="captain"))
    sink.emit(
        run_completed(
            "cap-1",
            "CEO",
            output_summary="",
            duration_ms=1,
            role="captain",
        )
    )

    await asyncio.sleep(0)
    if sink._checkpointer and sink._checkpointer._flush_inflight:
        await sink._checkpointer._flush_inflight

    segment_store.upsert_stream_segments.assert_awaited()


@pytest.mark.asyncio
async def test_worker_run_failed_triggers_segment_flush(segment_store):
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    sink.emit(content_delta("partial"))
    sink.emit(run_started("cap-1", "CEO", kind="captain"))
    sink.emit(run_failed("w1", "worker", "boom"))

    await asyncio.sleep(0)
    if sink._checkpointer and sink._checkpointer._flush_inflight:
        await sink._checkpointer._flush_inflight

    segment_store.upsert_stream_segments.assert_awaited_once()
    kwargs = segment_store.upsert_stream_segments.await_args.kwargs
    channels = {ch: text for ch, text, _gen in kwargs["segments"]}
    assert channels[CHANNEL_CAPTAIN_CONTENT] == "partial"


@pytest.mark.asyncio
async def test_close_stops_checkpointer():
    sink = EventSink()
    sink.bind_content_checkpoint(conversation_id="c1", message_id="m1")
    assert sink._checkpointer is not None

    sink.close()

    await asyncio.sleep(0)
    assert sink._checkpointer is None
    assert sink._closed


def test_flush_noop_without_bind():
    sink = EventSink()
    sink.emit(content_delta("orphan"))
    assert sink._checkpointer is None
    assert sink.stream_memory_snapshot() == {}

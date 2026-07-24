"""Unit tests for turn_stream_state upsert merge rules (流式回复持久化 §3.1)."""

from agentcore.db.repositories.stream_state import resolve_stream_upsert


def test_same_generation_monotonic_accepts_longer():
    assert resolve_stream_upsert(
        existing_text="hello",
        existing_generation=0,
        incoming_text="hello world",
        incoming_generation=0,
    ) == ("hello world", 0)


def test_same_generation_monotonic_rejects_shorter():
    assert (
        resolve_stream_upsert(
            existing_text="hello world",
            existing_generation=0,
            incoming_text="hello",
            incoming_generation=0,
        )
        is None
    )


def test_generation_reset_allows_empty():
    assert resolve_stream_upsert(
        existing_text="old long body",
        existing_generation=0,
        incoming_text="",
        incoming_generation=1,
    ) == ("", 1)


def test_stale_generation_rejected():
    assert (
        resolve_stream_upsert(
            existing_text="kept",
            existing_generation=2,
            incoming_text="stale longer text here",
            incoming_generation=1,
        )
        is None
    )


def test_first_write_accepts():
    assert resolve_stream_upsert(
        existing_text=None,
        existing_generation=None,
        incoming_text="hi",
        incoming_generation=0,
    ) == ("hi", 0)

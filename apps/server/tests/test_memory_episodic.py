"""Episodic layer: session summaries, trigger conditions, append storage."""

from datetime import UTC, datetime, timedelta

from agentcore.memory.episodic import (
    append_episode,
    clamp_summary,
    list_undigested_episodes,
    load_scope_meta,
    mark_episodes_digested,
    should_run_semantic,
)
from agentcore.memory.store import EPISODIC_DIR, FileMemoryStore


def test_clamp_summary_truncates_with_ellipsis():
    assert clamp_summary("  hello   world  ", 20) == "hello world"
    assert clamp_summary("abcdefghij", 5) == "abcd…"
    assert clamp_summary("", 10) == ""


def test_should_run_semantic_count_trigger():
    assert should_run_semantic(
        undigested_count=3,
        last_semantic_at=datetime.now(UTC),
        min_episodes=3,
        max_age_hours=24,
    )
    assert not should_run_semantic(
        undigested_count=2,
        last_semantic_at=datetime.now(UTC),
        min_episodes=3,
        max_age_hours=24,
    )


def test_should_run_semantic_age_trigger():
    old = datetime.now(UTC) - timedelta(hours=25)
    assert should_run_semantic(
        undigested_count=1,
        last_semantic_at=old,
        min_episodes=3,
        max_age_hours=24,
    )
    assert not should_run_semantic(
        undigested_count=1,
        last_semantic_at=datetime.now(UTC) - timedelta(hours=1),
        min_episodes=3,
        max_age_hours=24,
    )


def test_should_run_semantic_cold_start_uses_oldest_episode():
    oldest = datetime.now(UTC) - timedelta(hours=25)
    assert should_run_semantic(
        undigested_count=1,
        last_semantic_at=None,
        min_episodes=3,
        max_age_hours=24,
        oldest_undigested_at=oldest,
    )
    assert not should_run_semantic(
        undigested_count=1,
        last_semantic_at=None,
        min_episodes=3,
        max_age_hours=24,
        oldest_undigested_at=datetime.now(UTC),
    )


def test_should_run_semantic_zero_undigested():
    assert not should_run_semantic(
        undigested_count=0,
        last_semantic_at=None,
        min_episodes=3,
        max_age_hours=24,
        oldest_undigested_at=datetime.now(UTC) - timedelta(days=2),
    )


async def test_append_and_list_undigested(tmp_path):
    store = FileMemoryStore(tmp_path)
    ep = await append_episode(
        store,
        user_id="u1",
        conversation_id="c1",
        summary="用户倾向用 pnpm，本场讨论了部署。",
        max_chars=200,
    )
    assert ep.summary
    assert (tmp_path / "u1" / EPISODIC_DIR / f"{ep.id}.md").is_file()
    undigested = await list_undigested_episodes(store, "u1")
    assert len(undigested) == 1
    assert undigested[0].id == ep.id
    assert undigested[0].conversation_id == "c1"


async def test_mark_digested_hides_from_undigested(tmp_path):
    store = FileMemoryStore(tmp_path)
    ep = await append_episode(
        store, user_id="u1", conversation_id="c1", summary="摘要一", max_chars=200
    )
    await mark_episodes_digested(store, "u1", [ep.id])
    assert await list_undigested_episodes(store, "u1") == []
    meta = await load_scope_meta(store, "u1")
    assert ep.id in meta.digested_ids
    assert meta.last_semantic_at is not None

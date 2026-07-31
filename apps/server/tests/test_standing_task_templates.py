"""System standing-task templates (daily conversation review)."""

from agentcore.standing_tasks.templates import (
    DAILY_CONVERSATION_REVIEW,
    build_scope_briefing,
    daily_review_goal,
    is_known_template,
    list_catalog,
    normalize_template_config,
)


def test_catalog_has_daily():
    keys = {i.key for i in list_catalog()}
    assert DAILY_CONVERSATION_REVIEW in keys


def test_normalize_defaults_global_when_empty_scope():
    cfg = normalize_template_config({"include_global": False, "folder_ids": []})
    assert cfg["include_global"] is True
    assert cfg["folder_ids"] == []
    assert cfg["lookback_hours"] == 24


def test_normalize_clamps_lookback():
    assert normalize_template_config({"lookback_hours": 999})["lookback_hours"] == 168
    assert normalize_template_config({"lookback_hours": 0})["lookback_hours"] == 1


def test_scope_briefing_mentions_reviews_dir():
    text = build_scope_briefing(
        {"include_global": True, "folder_ids": [], "lookback_hours": 24}
    )
    assert "AgentCore/文档/reviews" in text
    assert "裸聊" in text


def test_goal_forbids_silent_remember():
    g = daily_review_goal()
    assert "ask_user" in g
    assert "remember" in g
    assert is_known_template("daily_conversation_review")
    assert not is_known_template("nope")

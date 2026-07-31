"""System standing-task templates (daily conversation review)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from agentcore.api.schemas.conversations import PermissionAxesModel
from agentcore.api.schemas.standing_tasks import StandingTaskSummary
from agentcore.core.types import validate_permission_axes
from agentcore.standing_tasks.templates import (
    DAILY_CONVERSATION_REVIEW,
    DEFAULT_TEMPLATE_AXES,
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


def test_default_template_axes_are_legal():
    """ensure() stores DEFAULT_TEMPLATE_AXES then StandingTaskSummary.from_row validates them.

    Regression: file_write=ask ∧ command=auto used to 500 on install.
    """
    axes = validate_permission_axes(**DEFAULT_TEMPLATE_AXES)
    assert axes.file_write.value == "ask"
    assert axes.command.value == "ask"
    PermissionAxesModel.model_validate(DEFAULT_TEMPLATE_AXES)


def test_summary_from_row_accepts_default_template_axes():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id="00000000-0000-4000-8000-000000000001",
        name="每日对话复盘",
        goal="g",
        folder_id="00000000-0000-4000-8000-000000000002",
        trigger_kind="schedule",
        cron="0 1 * * *",
        permission_axes=dict(DEFAULT_TEMPLATE_AXES),
        enabled=False,
        next_run_at=None,
        conversation_id=None,
        last_run_at=None,
        webhook_id=None,
        template_key=DAILY_CONVERSATION_REVIEW,
        template_config={
            "include_global": True,
            "folder_ids": [],
            "lookback_hours": 24,
        },
        created_at=now,
        updated_at=now,
    )
    summary = StandingTaskSummary.from_row(row)
    assert summary.permission_axes.file_write.value == "ask"
    assert summary.permission_axes.command.value == "ask"
    assert summary.template_key == DAILY_CONVERSATION_REVIEW

"""Standing tasks L1: cron, lease claimability, run status mapping, cloud folder gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.api.routes.standing_tasks import _require_cloud_folder
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.repositories.standing_tasks import is_task_claimable
from agentcore.runtime.events import FinishReason
from agentcore.standing_tasks.runner import _finish_is_paused, _truncate_summary
from agentcore.standing_tasks.schedule import (
    CRON_PRESETS,
    CronError,
    next_run_after,
    resolve_cron,
    validate_cron,
)


class TestCronNextRun:
    def test_weekly_monday_advances_to_next_monday(self):
        # 2026-07-28 is Tuesday; next Monday 09:00 UTC.
        after = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
        nxt = next_run_after("0 9 * * 1", after)
        assert nxt == datetime(2026, 8, 3, 9, 0, tzinfo=UTC)

    def test_hourly_preset(self):
        after = datetime(2026, 7, 28, 10, 15, tzinfo=UTC)
        cron = resolve_cron(preset="hourly")
        assert cron == CRON_PRESETS["hourly"]
        nxt = next_run_after(cron, after)
        assert nxt == datetime(2026, 7, 28, 11, 0, tzinfo=UTC)

    def test_daily_same_day_if_before_fire(self):
        after = datetime(2026, 7, 28, 8, 0, tzinfo=UTC)
        nxt = next_run_after("0 9 * * *", after)
        assert nxt == datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

    def test_invalid_cron_raises(self):
        with pytest.raises(CronError):
            validate_cron("not a cron")
        with pytest.raises(CronError):
            resolve_cron(cron="0 9 * * *", preset="daily")

    def test_desktop_schedule_presets(self):
        assert resolve_cron(preset="weekly_mon") == "0 9 * * 1"
        assert resolve_cron(preset="weekly_fri") == "0 9 * * 5"
        assert resolve_cron(preset="monthly_1") == "0 9 1 * *"
        assert resolve_cron(preset="custom", cron="30 8 * * 2") == "30 8 * * 2"
        from agentcore.standing_tasks.schedule import infer_schedule_preset

        assert infer_schedule_preset("0 9 * * 1") == "weekly_mon"
        assert infer_schedule_preset("15 3 * * *") == "custom"

class TestLeaseClaimable:
    def test_due_and_unlocked_is_claimable(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert is_task_claimable(
            enabled=True,
            next_run_at=now - timedelta(minutes=1),
            lease_until=None,
            now=now,
        )

    def test_active_lease_blocks_second_claim(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert not is_task_claimable(
            enabled=True,
            next_run_at=now - timedelta(minutes=1),
            lease_until=now + timedelta(minutes=10),
            now=now,
        )

    def test_expired_lease_allows_reclaim(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert is_task_claimable(
            enabled=True,
            next_run_at=now - timedelta(minutes=1),
            lease_until=now - timedelta(seconds=1),
            now=now,
        )

    def test_disabled_skipped(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert not is_task_claimable(
            enabled=False,
            next_run_at=now - timedelta(minutes=1),
            lease_until=None,
            now=now,
        )

    def test_future_next_run_skipped(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert not is_task_claimable(
            enabled=True,
            next_run_at=now + timedelta(minutes=5),
            lease_until=None,
            now=now,
        )

    def test_webhook_trigger_never_claimable(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert not is_task_claimable(
            enabled=True,
            next_run_at=now - timedelta(minutes=1),
            lease_until=None,
            now=now,
            trigger_kind="webhook",
        )

    def test_null_next_run_not_claimable(self):
        now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
        assert not is_task_claimable(
            enabled=True,
            next_run_at=None,
            lease_until=None,
            now=now,
            trigger_kind="schedule",
        )


class TestCloudFolderGate:
    def test_missing_folder_404(self):
        with pytest.raises(NotFoundError):
            _require_cloud_folder(None)

    def test_local_folder_rejected(self):
        folder = SimpleNamespace(local_root_id="desktop-root-1", id="f1")
        with pytest.raises(ValidationError, match="云工作区"):
            _require_cloud_folder(folder)

    def test_cloud_folder_ok(self):
        folder = SimpleNamespace(local_root_id=None, id="f1")
        _require_cloud_folder(folder)  # no raise


class TestRunStatusMapping:
    def test_paused_finish_reason(self):
        assert _finish_is_paused(FinishReason.PAUSED)
        assert _finish_is_paused("paused")
        assert not _finish_is_paused(FinishReason.END_TURN)
        assert not _finish_is_paused("stop")

    def test_summary_truncate(self):
        assert _truncate_summary(None) is None
        assert _truncate_summary("short") == "short"
        long = "x" * 600
        out = _truncate_summary(long)
        assert out is not None
        assert len(out) == 500
        assert out.endswith("…")


@pytest.mark.asyncio
async def test_run_job_succeeded(monkeypatch):
    """Pipeline success → inbox status succeeded + summary."""
    from agentcore.standing_tasks import runner as runner_mod

    task = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        folder_id="folder-1",
        goal="周一简报",
        name="简报",
        permission_axes={"file_write": "session", "command": "kickoff", "team_kickoff": "rules"},
        cron="0 9 * * 1",
        enabled=True,
        conversation_id="conv-1",
        local_root_id=None,
    )
    folder = SimpleNamespace(id="folder-1", local_root_id=None)
    run_marks: dict[str, object] = {}

    class _Tasks:
        def __init__(self, session):
            pass

        async def get_by_id(self, task_id, user_id=None):
            return task

        async def clear_lease(self, *a, **k):
            return None

        async def advance_next_run(self, *a, **k):
            return None

    class _Runs:
        def __init__(self, session):
            pass

        async def mark_failed(self, run_id, *, error):
            run_marks["failed"] = error

        async def mark_succeeded(self, run_id, *, summary):
            run_marks["succeeded"] = summary

        async def mark_awaiting_user(self, run_id, *, summary=None):
            run_marks["awaiting_user"] = summary

        async def set_conversation_and_message(self, *a, **k):
            return None

    class _Folders:
        def __init__(self, session):
            pass

        async def get_by_id(self, folder_id, user_id=None):
            return folder

    class _Convs:
        def __init__(self, session):
            pass

        async def get_by_id_unscoped(self, cid):
            return SimpleNamespace(id=cid, folder_id="folder-1", title="简报")

    class _Msgs:
        def __init__(self, session):
            pass

        async def create(self, **kwargs):
            return SimpleNamespace(id="msg-u1")

        async def list_recent(self, *a, **k):
            return []

    class _Users:
        def __init__(self, session):
            pass

        async def get_by_id(self, uid):
            return SimpleNamespace(user_id=uid)

    class _Paused:
        def __init__(self, session):
            pass

        async def exists_for_conversation(self, cid):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "async_session_factory", lambda: _Session())
    monkeypatch.setattr(runner_mod, "StandingTaskRepository", _Tasks)
    monkeypatch.setattr(runner_mod, "StandingTaskRunRepository", _Runs)
    monkeypatch.setattr(runner_mod, "FolderRepository", _Folders)
    monkeypatch.setattr(runner_mod, "ConversationRepository", _Convs)
    monkeypatch.setattr(runner_mod, "MessageRepository", _Msgs)
    monkeypatch.setattr(runner_mod, "PausedTurnRepository", _Paused)
    monkeypatch.setattr(runner_mod, "UserRepository", _Users)
    monkeypatch.setattr(
        runner_mod,
        "resolve_conversation_model_selection",
        AsyncMock(return_value=SimpleNamespace(origin="byok", provider_id=None, model="m")),
    )
    monkeypatch.setattr(
        runner_mod, "preflight_llm_credentials", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        runner_mod, "resolve_profile_set", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(runner_mod, "resolve_memory_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        runner_mod, "resolve_conversation_history_access", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(runner_mod, "resolve_permission_axes", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "build_turn_backend", MagicMock())
    monkeypatch.setattr(runner_mod, "load_chat_context", AsyncMock(return_value=[]))

    class _Lock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "workspace_lock", lambda *a, **k: _Lock())
    monkeypatch.setattr(runner_mod, "workspace_storage_key", lambda **k: "k")

    async def fake_pipeline(**kwargs):
        return {"finish_reason": FinishReason.END_TURN, "content": "本周摘要 OK"}

    monkeypatch.setattr(runner_mod, "_run_pipeline", fake_pipeline)

    await runner_mod.run_standing_task_job(run_id="run-1", task_id="task-1", advance_schedule=False)
    assert "succeeded" in run_marks
    assert run_marks["succeeded"] == "本周摘要 OK"
    assert "awaiting_user" not in run_marks
    assert "failed" not in run_marks


@pytest.mark.asyncio
async def test_run_job_awaiting_user(monkeypatch):
    """Paused finish → awaiting_user."""
    from agentcore.standing_tasks import runner as runner_mod

    task = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        folder_id="folder-1",
        goal="需授权",
        name="授权任务",
        permission_axes={},
        cron="0 9 * * *",
        enabled=True,
        conversation_id="conv-1",
    )
    folder = SimpleNamespace(id="folder-1", local_root_id=None)
    run_marks: dict[str, object] = {}

    class _Tasks:
        def __init__(self, session):
            pass

        async def get_by_id(self, *a, **k):
            return task

        async def clear_lease(self, *a, **k):
            return None

        async def advance_next_run(self, *a, **k):
            return None

    class _Runs:
        def __init__(self, session):
            pass

        async def mark_failed(self, run_id, *, error):
            run_marks["failed"] = error

        async def mark_succeeded(self, run_id, *, summary):
            run_marks["succeeded"] = summary

        async def mark_awaiting_user(self, run_id, *, summary=None):
            run_marks["awaiting_user"] = summary

        async def set_conversation_and_message(self, *a, **k):
            return None

    class _Folders:
        def __init__(self, session):
            pass

        async def get_by_id(self, *a, **k):
            return folder

    class _Convs:
        def __init__(self, session):
            pass

        async def get_by_id_unscoped(self, cid):
            return SimpleNamespace(id=cid, folder_id="folder-1", title="t")

    class _Msgs:
        def __init__(self, session):
            pass

        async def create(self, **kwargs):
            return SimpleNamespace(id="msg-u1")

        async def list_recent(self, *a, **k):
            return []

    class _Users:
        def __init__(self, session):
            pass

        async def get_by_id(self, uid):
            return SimpleNamespace(user_id=uid)

    class _Paused:
        def __init__(self, session):
            pass

        async def exists_for_conversation(self, cid):
            return True

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "async_session_factory", lambda: _Session())
    monkeypatch.setattr(runner_mod, "StandingTaskRepository", _Tasks)
    monkeypatch.setattr(runner_mod, "StandingTaskRunRepository", _Runs)
    monkeypatch.setattr(runner_mod, "FolderRepository", _Folders)
    monkeypatch.setattr(runner_mod, "ConversationRepository", _Convs)
    monkeypatch.setattr(runner_mod, "MessageRepository", _Msgs)
    monkeypatch.setattr(runner_mod, "PausedTurnRepository", _Paused)
    monkeypatch.setattr(runner_mod, "UserRepository", _Users)
    monkeypatch.setattr(
        runner_mod,
        "resolve_conversation_model_selection",
        AsyncMock(return_value=SimpleNamespace(origin="byok", provider_id=None, model="m")),
    )
    monkeypatch.setattr(
        runner_mod, "preflight_llm_credentials", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(runner_mod, "resolve_profile_set", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "resolve_memory_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        runner_mod, "resolve_conversation_history_access", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(runner_mod, "resolve_permission_axes", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "build_turn_backend", MagicMock())
    monkeypatch.setattr(runner_mod, "load_chat_context", AsyncMock(return_value=[]))

    class _Lock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "workspace_lock", lambda *a, **k: _Lock())
    monkeypatch.setattr(runner_mod, "workspace_storage_key", lambda **k: "k")

    async def fake_pipeline(**kwargs):
        return {"finish_reason": FinishReason.PAUSED, "content": ""}

    monkeypatch.setattr(runner_mod, "_run_pipeline", fake_pipeline)

    await runner_mod.run_standing_task_job(run_id="run-2", task_id="task-1", advance_schedule=False)
    assert "awaiting_user" in run_marks
    assert "succeeded" not in run_marks


# ---------------------------------------------------------------------------
# L2a webhook
# ---------------------------------------------------------------------------


class TestWebhookHelpers:
    def test_extract_text_from_json_text_field(self):
        from agentcore.standing_tasks.webhook import extract_event_text

        body = '{"text": "新线索 A", "extra": 1}'.encode()
        assert extract_event_text(body, content_type="application/json") == "新线索 A"

    def test_extract_message_field(self):
        from agentcore.standing_tasks.webhook import extract_event_text

        body = b'{"message": "hello from zapier"}'
        assert extract_event_text(body, content_type="application/json") == "hello from zapier"

    def test_extract_falls_back_to_raw_body(self):
        from agentcore.standing_tasks.webhook import extract_event_text

        assert extract_event_text(b"plain event", content_type="text/plain") == "plain event"

    def test_build_fire_message_appends_event(self):
        from agentcore.standing_tasks.webhook import build_fire_message

        msg = build_fire_message(goal="分诊线索", event_text="张三报名")
        assert msg == "分诊线索\n\n本次事件：张三报名"

    def test_secret_roundtrip(self):
        from agentcore.standing_tasks.webhook import (
            generate_webhook_secret,
            verify_webhook_secret,
        )

        raw, hashed = generate_webhook_secret()
        assert verify_webhook_secret(raw, hashed)
        assert not verify_webhook_secret("wrong", hashed)
        assert not verify_webhook_secret(raw, "0" * 64)

    def test_require_secret_bearer_and_header(self):
        from agentcore.core.errors import AuthenticationError
        from agentcore.standing_tasks.webhook import (
            generate_webhook_secret,
            require_webhook_secret,
        )

        raw, hashed = generate_webhook_secret()
        require_webhook_secret(
            authorization=f"Bearer {raw}",
            x_webhook_secret=None,
            expected_hash=hashed,
        )
        require_webhook_secret(
            authorization=None,
            x_webhook_secret=raw,
            expected_hash=hashed,
        )
        with pytest.raises(AuthenticationError):
            require_webhook_secret(
                authorization="Bearer nope",
                x_webhook_secret=None,
                expected_hash=hashed,
            )

    def test_idempotency_same_key_returns_same_run(self):
        from agentcore.standing_tasks import webhook as wh

        wh.reset_webhook_state()
        assert wh.idempotency_lookup("wid-1", "k1") is None
        wh.idempotency_store("wid-1", "k1", "run-aaa")
        assert wh.idempotency_lookup("wid-1", "k1") == "run-aaa"
        assert wh.idempotency_lookup("wid-1", "k2") is None
        wh.reset_webhook_state()

    def test_rate_limit_trips(self, monkeypatch):
        from agentcore.core.errors import RateLimitedError
        from agentcore.middleware.rate_limit import SlidingWindowRateLimiter
        from agentcore.standing_tasks import webhook as wh

        wh.reset_webhook_state()
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        monkeypatch.setattr(wh, "_webhook_rate_limiter", limiter)
        monkeypatch.setattr(wh.settings, "rate_limit_enabled", True)
        monkeypatch.setattr(wh.settings, "standing_task_webhook_rate_limit_max", 2)
        wh.enforce_webhook_rate_limit("task-rl", now=1000.0)
        wh.enforce_webhook_rate_limit("task-rl", now=1001.0)
        with pytest.raises(RateLimitedError):
            wh.enforce_webhook_rate_limit("task-rl", now=1002.0)
        wh.reset_webhook_state()


class TestWebhookCreateSchema:
    def test_webhook_rejects_cron(self):
        from pydantic import ValidationError as PydValidationError

        from agentcore.api.schemas.standing_tasks import CreateStandingTaskRequest

        with pytest.raises(PydValidationError):
            CreateStandingTaskRequest(
                name="w",
                goal="g",
                folder_id="f1",
                trigger_kind="webhook",
                schedule_preset="daily",
            )

    def test_webhook_ok_without_schedule(self):
        from agentcore.api.schemas.standing_tasks import CreateStandingTaskRequest

        body = CreateStandingTaskRequest(
            name="w",
            goal="g",
            folder_id="f1",
            trigger_kind="webhook",
        )
        assert body.trigger_kind == "webhook"


@pytest.mark.asyncio
async def test_fire_webhook_auth_failure(monkeypatch):
    """Wrong secret → AuthenticationError; schedule task not found by webhook_id."""
    from agentcore.api.routes import standing_tasks as routes
    from agentcore.core.errors import AuthenticationError, NotFoundError
    from agentcore.standing_tasks.webhook import generate_webhook_secret

    raw, hashed = generate_webhook_secret()
    webhook_task = SimpleNamespace(
        id="task-w",
        user_id="user-1",
        folder_id="folder-1",
        enabled=True,
        trigger_kind="webhook",
        webhook_id="wid-1",
        webhook_secret_hash=hashed,
    )

    class _Repo:
        async def get_by_webhook_id(self, wid):
            if wid == "wid-1":
                return webhook_task
            return None

    class _Folders:
        async def get_by_id(self, *a, **k):
            return SimpleNamespace(id="folder-1", local_root_id=None)

    class _Req:
        headers = {"content-type": "application/json"}

        async def body(self):
            return b'{"text":"x"}'

    with pytest.raises(NotFoundError):
        await routes.fire_standing_webhook(
            webhook_id="missing",
            request=_Req(),
            repo=_Repo(),
            folders=_Folders(),
            authorization="Bearer anything",
            x_agentcore_webhook_secret=None,
            x_idempotency_key=None,
        )

    with pytest.raises(AuthenticationError):
        await routes.fire_standing_webhook(
            webhook_id="wid-1",
            request=_Req(),
            repo=_Repo(),
            folders=_Folders(),
            authorization="Bearer wrong-secret",
            x_agentcore_webhook_secret=None,
            x_idempotency_key=None,
        )


@pytest.mark.asyncio
async def test_fire_webhook_success_and_idempotent(monkeypatch):
    from agentcore.api.routes import standing_tasks as routes
    from agentcore.standing_tasks import webhook as wh
    from agentcore.standing_tasks.webhook import generate_webhook_secret

    wh.reset_webhook_state()
    raw, hashed = generate_webhook_secret()
    webhook_task = SimpleNamespace(
        id="task-w",
        user_id="user-1",
        folder_id="folder-1",
        enabled=True,
        trigger_kind="webhook",
        webhook_id="wid-1",
        webhook_secret_hash=hashed,
    )
    dispatches: list[dict] = []

    async def fake_dispatch(**kwargs):
        dispatches.append(kwargs)
        return f"run-{len(dispatches)}"

    monkeypatch.setattr(routes, "dispatch_standing_task", fake_dispatch)

    class _Repo:
        async def get_by_webhook_id(self, wid):
            return webhook_task if wid == "wid-1" else None

    class _Folders:
        async def get_by_id(self, *a, **k):
            return SimpleNamespace(id="folder-1", local_root_id=None)

    class _Req:
        headers = {"content-type": "application/json"}

        async def body(self):
            return '{"text":"线索一"}'.encode()

    r1 = await routes.fire_standing_webhook(
        webhook_id="wid-1",
        request=_Req(),
        repo=_Repo(),
        folders=_Folders(),
        authorization=f"Bearer {raw}",
        x_agentcore_webhook_secret=None,
        x_idempotency_key="idem-1",
    )
    r2 = await routes.fire_standing_webhook(
        webhook_id="wid-1",
        request=_Req(),
        repo=_Repo(),
        folders=_Folders(),
        authorization=None,
        x_agentcore_webhook_secret=raw,
        x_idempotency_key="idem-1",
    )
    assert r1.run_id == r2.run_id == "run-1"
    assert len(dispatches) == 1
    assert dispatches[0]["trigger_source"] == "webhook"
    assert dispatches[0]["event_text"] == "线索一"
    assert dispatches[0]["advance_schedule"] is False
    wh.reset_webhook_state()


@pytest.mark.asyncio
async def test_fire_webhook_rate_limited(monkeypatch):
    from agentcore.api.routes import standing_tasks as routes
    from agentcore.core.errors import RateLimitedError
    from agentcore.middleware.rate_limit import SlidingWindowRateLimiter
    from agentcore.standing_tasks import webhook as wh
    from agentcore.standing_tasks.webhook import generate_webhook_secret

    wh.reset_webhook_state()
    monkeypatch.setattr(
        wh, "_webhook_rate_limiter", SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    )
    monkeypatch.setattr(wh.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(wh.settings, "standing_task_webhook_rate_limit_max", 1)

    raw, hashed = generate_webhook_secret()
    webhook_task = SimpleNamespace(
        id="task-w",
        user_id="user-1",
        folder_id="folder-1",
        enabled=True,
        trigger_kind="webhook",
        webhook_id="wid-1",
        webhook_secret_hash=hashed,
    )

    async def fake_dispatch(**kwargs):
        return "run-x"

    monkeypatch.setattr(routes, "dispatch_standing_task", fake_dispatch)

    class _Repo:
        async def get_by_webhook_id(self, wid):
            return webhook_task

    class _Folders:
        async def get_by_id(self, *a, **k):
            return SimpleNamespace(id="folder-1", local_root_id=None)

    class _Req:
        headers = {"content-type": "application/json"}

        async def body(self):
            return b"{}"

    await routes.fire_standing_webhook(
        webhook_id="wid-1",
        request=_Req(),
        repo=_Repo(),
        folders=_Folders(),
        authorization=f"Bearer {raw}",
        x_agentcore_webhook_secret=None,
        x_idempotency_key=None,
    )
    with pytest.raises(RateLimitedError):
        await routes.fire_standing_webhook(
            webhook_id="wid-1",
            request=_Req(),
            repo=_Repo(),
            folders=_Folders(),
            authorization=f"Bearer {raw}",
            x_agentcore_webhook_secret=None,
            x_idempotency_key=None,
        )
    wh.reset_webhook_state()


@pytest.mark.asyncio
async def test_schedule_task_not_found_via_webhook_lookup():
    """Schedule tasks have no webhook_id → get_by_webhook_id returns None → 404."""
    from agentcore.api.routes import standing_tasks as routes
    from agentcore.core.errors import NotFoundError

    class _Repo:
        async def get_by_webhook_id(self, wid):
            # Mimic repo filter: schedule rows never match webhook_id lookup.
            return None

    class _Folders:
        async def get_by_id(self, *a, **k):
            return SimpleNamespace(id="folder-1", local_root_id=None)

    class _Req:
        headers = {"content-type": "application/json"}

        async def body(self):
            return b"{}"

    with pytest.raises(NotFoundError):
        await routes.fire_standing_webhook(
            webhook_id="any-id",
            request=_Req(),
            repo=_Repo(),
            folders=_Folders(),
            authorization="Bearer x",
            x_agentcore_webhook_secret=None,
            x_idempotency_key=None,
        )


@pytest.mark.asyncio
async def test_run_job_includes_event_text(monkeypatch):
    """Webhook fire appends 本次事件 to the user message passed to the pipeline."""
    from agentcore.standing_tasks import runner as runner_mod

    task = SimpleNamespace(
        id="task-1",
        user_id="user-1",
        folder_id="folder-1",
        goal="常驻目标",
        name="简报",
        permission_axes={},
        cron=None,
        trigger_kind="webhook",
        enabled=True,
        conversation_id="conv-1",
    )
    folder = SimpleNamespace(id="folder-1", local_root_id=None)
    captured: dict[str, object] = {}

    class _Tasks:
        def __init__(self, session):
            pass

        async def get_by_id(self, *a, **k):
            return task

        async def clear_lease(self, *a, **k):
            return None

        async def advance_next_run(self, *a, **k):
            captured["advanced"] = True

    class _Runs:
        def __init__(self, session):
            pass

        async def mark_failed(self, run_id, *, error):
            captured["failed"] = error

        async def mark_succeeded(self, run_id, *, summary):
            captured["succeeded"] = summary

        async def mark_awaiting_user(self, run_id, *, summary=None):
            captured["awaiting_user"] = summary

        async def set_conversation_and_message(self, *a, **k):
            return None

    class _Folders:
        def __init__(self, session):
            pass

        async def get_by_id(self, *a, **k):
            return folder

    class _Convs:
        def __init__(self, session):
            pass

        async def get_by_id_unscoped(self, cid):
            return SimpleNamespace(id=cid, folder_id="folder-1", title="t")

    class _Msgs:
        def __init__(self, session):
            pass

        async def create(self, **kwargs):
            captured["msg_content"] = kwargs.get("content")
            return SimpleNamespace(id="msg-u1")

        async def list_recent(self, *a, **k):
            return []

    class _Users:
        def __init__(self, session):
            pass

        async def get_by_id(self, uid):
            return SimpleNamespace(user_id=uid)

    class _Paused:
        def __init__(self, session):
            pass

        async def exists_for_conversation(self, cid):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "async_session_factory", lambda: _Session())
    monkeypatch.setattr(runner_mod, "StandingTaskRepository", _Tasks)
    monkeypatch.setattr(runner_mod, "StandingTaskRunRepository", _Runs)
    monkeypatch.setattr(runner_mod, "FolderRepository", _Folders)
    monkeypatch.setattr(runner_mod, "ConversationRepository", _Convs)
    monkeypatch.setattr(runner_mod, "MessageRepository", _Msgs)
    monkeypatch.setattr(runner_mod, "PausedTurnRepository", _Paused)
    monkeypatch.setattr(runner_mod, "UserRepository", _Users)
    monkeypatch.setattr(
        runner_mod,
        "resolve_conversation_model_selection",
        AsyncMock(return_value=SimpleNamespace(origin="byok", provider_id=None, model="m")),
    )
    monkeypatch.setattr(runner_mod, "preflight_llm_credentials", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "resolve_profile_set", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "resolve_memory_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        runner_mod, "resolve_conversation_history_access", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(runner_mod, "resolve_permission_axes", AsyncMock(return_value=None))
    monkeypatch.setattr(runner_mod, "build_turn_backend", MagicMock())
    monkeypatch.setattr(runner_mod, "load_chat_context", AsyncMock(return_value=[]))

    class _Lock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(runner_mod, "workspace_lock", lambda *a, **k: _Lock())
    monkeypatch.setattr(runner_mod, "workspace_storage_key", lambda **k: "k")

    async def fake_pipeline(**kwargs):
        captured["pipeline_msg"] = kwargs.get("user_message")
        return {"finish_reason": FinishReason.END_TURN, "content": "ok"}

    monkeypatch.setattr(runner_mod, "_run_pipeline", fake_pipeline)

    await runner_mod.run_standing_task_job(
        run_id="run-w",
        task_id="task-1",
        advance_schedule=True,  # even if True, webhook has no cron → must not advance
        event_text="外部事件",
    )
    assert captured["msg_content"] == "常驻目标\n\n本次事件：外部事件"
    assert captured["pipeline_msg"] == "常驻目标\n\n本次事件：外部事件"
    assert "advanced" not in captured
    assert "succeeded" in captured

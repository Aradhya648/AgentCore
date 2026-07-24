"""Unit tests for the local→云 handoff cloud run (双模式工作区 P2e / e2).

Two seams are exercised without a DB, desktop, object store, or LLM:

* ``restore_into_workspace`` — the seeding step: a source conversation's snapshot
  must be restored into the *destination* (hidden job) conversation's workspace
  root (under the source's storage key), so the cloud team runs on the user's
  real files.
* ``run_handoff_job`` — the detached orchestration: restore → run the team
  **un-gated** on the job conversation → persist the result turn → snapshot the
  result → mark the job succeeded; and on any failure, mark it failed. All heavy
  collaborators (DB repos, pipeline, storage, server workspace) are faked so the
  control flow is asserted in isolation.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from agentcore.config import settings
from agentcore.conversation import handoff_jobs as handoff_jobs_mod
from agentcore.conversation.service import run_handoff_job
from agentcore.storage import SnapshotRef
from agentcore.workspace.locate import workspace_root_path, workspace_storage_key
from agentcore.workspace.snapshots import restore_into_workspace

pytestmark = pytest.mark.anyio


async def test_restore_into_workspace_uses_source_key_and_dest_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    captured: dict = {}

    class _FakeProvider:
        async def restore(self, key, snapshot_id, root):
            captured.update(key=key, snapshot_id=snapshot_id, root=root)

    monkeypatch.setattr(
        "agentcore.workspace.snapshots.build_storage_provider", lambda: _FakeProvider()
    )

    await restore_into_workspace(
        source_user_id="u1",
        source_folder_id=None,
        source_conversation_id="src",
        snapshot_id="snap-1",
        dest_user_id="u1",
        dest_folder_id=None,
        dest_conversation_id="job",
    )

    assert captured["snapshot_id"] == "snap-1"
    # Read from the *source* conversation's storage key …
    assert captured["key"] == workspace_storage_key(
        user_id="u1", folder_id=None, conversation_id="src"
    )
    # … and extracted into the *job* conversation's workspace root.
    assert captured["root"] == workspace_root_path(
        user_id="u1", folder_id=None, conversation_id="job"
    )


class _FakeSession:
    async def rollback(self) -> None:  # used by the cost-ledger guard
        pass


class _FakeSessionCM:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *_exc) -> bool:
        return False


def _patch_job_runner(monkeypatch, events: list, *, pipeline):
    """Fake out run_handoff_job's collaborators, recording calls into ``events``."""

    class _FakeJobRepo:
        def __init__(self, _session):
            pass

        async def mark_running(self, job_id):
            events.append(("running", job_id))

        async def mark_succeeded(self, job_id, *, result_snapshot_id):
            events.append(("succeeded", job_id, result_snapshot_id))

        async def mark_failed(self, job_id, *, error):
            events.append(("failed", job_id, error))

    class _FakeMsgRepo:
        def __init__(self, _session):
            pass

        async def create(self, **kw):
            events.append(("msg", kw.get("role"), kw.get("conversation_id")))

    async def _fake_restore(**kw):
        events.append(("restore", kw.get("source_conversation_id"), kw.get("dest_conversation_id")))

    async def _fake_create_snapshot(**kw):
        events.append(("snapshot", kw.get("conversation_id"), kw.get("label")))
        return SnapshotRef(
            snapshot_id="result-snap",
            label=kw.get("label"),
            created_at=datetime.now(UTC),
            size_bytes=10,
        )

    monkeypatch.setattr(handoff_jobs_mod, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(handoff_jobs_mod, "HandoffJobRepository", _FakeJobRepo)
    monkeypatch.setattr(handoff_jobs_mod, "MessageRepository", _FakeMsgRepo)
    monkeypatch.setattr(
        "agentcore.billing.turn_ledger.reconcile_turn_cost_ledger",
        AsyncMock(return_value=[{"run_id": "r1"}]),
    )
    monkeypatch.setattr(
        handoff_jobs_mod,
        "log_cost_recorded",
        lambda conversation_id, _message_id, _rows: events.append(("cost", conversation_id)),
    )
    monkeypatch.setattr(handoff_jobs_mod, "restore_into_workspace", _fake_restore)
    monkeypatch.setattr(handoff_jobs_mod, "build_server_workspace", lambda **kw: object())
    monkeypatch.setattr(handoff_jobs_mod, "create_snapshot", _fake_create_snapshot)
    monkeypatch.setattr(handoff_jobs_mod, "run_chat_pipeline", pipeline)


async def test_run_handoff_job_success(monkeypatch):
    events: list = []
    captured_pipeline: dict = {}

    async def _pipeline(**kw):
        captured_pipeline.update(kw)
        return {
            "content": "team output",
            "message_id": "m1",
            "reasoning_content": None,
            "citations": None,
            "runs": None,
            "cost_runs": [{"run_id": "r1"}],
            "input_tokens": 1,
            "output_tokens": 2,
            "rounds": 1,
        }

    _patch_job_runner(monkeypatch, events, pipeline=_pipeline)

    await run_handoff_job(
        job_id="j1",
        user_id="u1",
        source_folder_id=None,
        source_conversation_id="src",
        job_conversation_id="job",
        base_snapshot_id="base",
        task="refactor module X",
    )

    # Lifecycle: running → succeeded with the result snapshot id captured.
    assert ("running", "j1") in events
    assert ("succeeded", "j1", "result-snap") in events
    assert not any(e[0] == "failed" for e in events)

    # The team ran un-gated (autonomous, sandboxed) on the hidden job conversation,
    # seeded from the source's base snapshot.
    assert captured_pipeline["approvals_enabled"] is False
    assert captured_pipeline["conversation_id"] == "job"
    assert captured_pipeline["user_message"] == "refactor module X"
    assert ("restore", "src", "job") in events

    # The run's task + reply + cost ledger persist under the job conversation, and
    # the result is snapshotted (a kept "result:" version).
    assert ("msg", "user", "job") in events
    assert ("msg", "assistant", "job") in events
    assert ("cost", "job") in events
    snap = next(e for e in events if e[0] == "snapshot")
    assert snap[1] == "job" and snap[2].startswith("result:")


async def test_run_handoff_job_failure_marks_failed(monkeypatch):
    events: list = []

    async def _boom(**_kw):
        raise RuntimeError("kaboom")

    _patch_job_runner(monkeypatch, events, pipeline=_boom)

    # A failure inside the run is fully contained: the job is marked failed with the
    # error, and nothing escapes onto the event loop.
    await run_handoff_job(
        job_id="j2",
        user_id="u1",
        source_folder_id=None,
        source_conversation_id="src",
        job_conversation_id="job",
        base_snapshot_id="base",
        task="do work",
    )

    assert ("running", "j2") in events
    assert ("failed", "j2", "kaboom") in events
    assert not any(e[0] == "succeeded" for e in events)

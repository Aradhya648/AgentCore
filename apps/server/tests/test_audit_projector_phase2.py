"""Unit tests for Phase 2 audit projection."""

from agentcore.runtime.audit.projector import (
    project_journal_entry,
    project_run_deterministic_failure,
    project_run_redirect_ignored,
    project_run_retry,
)
from agentcore.runtime.audit.recorder import AuditRecorder


def test_checkpoint_journal_projection():
    recorder = AuditRecorder(
        user_id="u1",
        conversation_id="c1",
        turn_id="t1",
        trace_id="trace1",
        captain_run_id="captain-1",
        delegated=True,
    )
    paused = project_journal_entry(
        recorder,
        {"kind": "checkpoint_required", "payload": {"checkpoint_id": "ck1", "question": "?"}}
    )
    resumed = project_journal_entry(
        recorder,
        {"kind": "checkpoint_resolved", "payload": {"checkpoint_id": "ck1", "decision": "continue"}},
    )
    assert paused is not None
    assert paused.action == "checkpoint.paused"
    assert paused.category == "state"
    assert resumed is not None
    assert resumed.action == "checkpoint.resumed"


def test_run_retry_projection():
    recorder = AuditRecorder(
        user_id="u1",
        conversation_id="c1",
        turn_id="t1",
        trace_id="trace1",
        captain_run_id="captain-1",
        delegated=True,
    )
    draft = project_run_retry(
        recorder,
        run_id="w1",
        attempt=2,
        source="on_failure",
        error="timeout",
    )
    assert draft.action == "run.retry"
    assert draft.detail["attempt"] == 2
    assert draft.detail["source"] == "on_failure"


def test_run_deterministic_failure_projection():
    # 确定性失败区分 + 后端补记 (BL-6): a deterministic failure accepted-not-retried records a
    # ``state`` handling row (NOT a second ``failure`` row → no double-count), so the
    # delegated-turn audit trail shows the「未盲目重试确定性失败」decision.
    recorder = AuditRecorder(
        user_id="u1",
        conversation_id="c1",
        turn_id="t1",
        trace_id="trace1",
        captain_run_id="captain-1",
        delegated=True,
    )
    draft = project_run_deterministic_failure(
        recorder,
        run_id="w1",
        error="prompt too long",
    )
    assert draft.action == "run.deterministic_failure"
    assert draft.category == "state"
    # ``skipped`` (the blind retry was skipped) — the only valid audit outcome here: the DB
    # CheckConstraint + REST AuditOutcome contract are both ('ok','denied','failed','skipped'),
    # so an earlier ``not_retried`` violated the constraint and the row was silently dropped.
    assert draft.outcome == "skipped"
    assert draft.actor_kind == "member"
    assert draft.detail["reason"] == "deterministic"
    assert draft.detail["error"] == "prompt too long"


def test_run_redirect_ignored_projection():
    # 跑一半改方向 · 忽略路径 (run_redirect Step 4): a redirect that could not be applied mid-run
    # records a ``state`` / ``skipped`` handling row so the run detail can offer an explicit accept.
    recorder = AuditRecorder(
        user_id="u1",
        conversation_id="c1",
        turn_id="t1",
        trace_id="trace1",
        captain_run_id="captain-1",
        delegated=True,
    )
    draft = project_run_redirect_ignored(
        recorder,
        run_id="w1",
        feedback="改成B方向重做",
        execution_id="exec1",
    )
    assert draft.action == "run.redirect_ignored"
    assert draft.category == "state"
    assert draft.outcome == "skipped"
    assert draft.actor_kind == "member"
    assert draft.run_id == "w1"
    assert draft.execution_id == "exec1"
    assert draft.detail["reason"] == "not_applied"
    assert draft.detail["feedback"] == "改成B方向重做"


def test_run_context_inject_extracts_dependency_source_run_ids():
    recorder = AuditRecorder(
        user_id="u1",
        conversation_id="c1",
        turn_id="t1",
        trace_id="trace1",
        captain_run_id="captain-1",
        delegated=True,
    )
    draft = project_journal_entry(
        recorder,
        {
            "kind": "run_context",
            "payload": {
                "run_id": "w2",
                "agent_id": "a2",
                "blocks": [
                    {
                        "channel": "request",
                        "heading": "原始请求",
                        "body": "goal",
                        "chars": 4,
                        "truncated": False,
                    },
                    {
                        "channel": "dependency",
                        "heading": "前置结果",
                        "body": "from w1",
                        "chars": 7,
                        "truncated": False,
                        "source_role": "研究员",
                        "source_run_id": "w1",
                        "fidelity": "pass_through",
                        "files": [],
                    },
                ],
            },
        },
    )
    assert draft is not None
    assert draft.action == "context.inject"
    assert draft.detail["source_run_ids"] == ["w1"]

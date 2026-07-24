"""Tests for the user run-redirect queue (中间可见性 Phase 2a)."""

from agentcore.runtime.runs.redirect_queue import (
    enqueue_redirect,
    peek_redirect_count,
    take_redirects,
)


def test_enqueue_and_drain_fifo():
    enqueue_redirect(
        execution_id="exec1",
        run_id="r1",
        feedback="方向偏了",
        conversation_id="c1",
    )
    enqueue_redirect(
        execution_id="exec1",
        run_id="r2",
        feedback="第二条",
        conversation_id="c1",
    )
    assert peek_redirect_count("exec1") == 2
    drained = take_redirects("exec1")
    assert [r.run_id for r in drained] == ["r1", "r2"]
    assert drained[0].feedback == "方向偏了"
    assert peek_redirect_count("exec1") == 0
    assert take_redirects("exec1") == []

"""Unit tests for ambient debate steer queue (非阻塞 drain)."""

from agentcore.runtime.debate.steer_queue import (
    enqueue_steer,
    fold_steers,
    peek_steer_count,
    take_steers,
)
from agentcore.runtime.debate.types import RoundDecision


def test_enqueue_take_fifo_and_empty():
    take_steers("exec-clean")  # reset
    enqueue_steer(
        execution_id="exec-a",
        conversation_id="c1",
        decision="continue",
        focus="角度A",
    )
    enqueue_steer(
        execution_id="exec-a",
        conversation_id="c1",
        decision="continue",
        ask="谁兜底？",
        ask_target="pro",
    )
    assert peek_steer_count("exec-a") == 2
    drained = take_steers("exec-a")
    assert len(drained) == 2
    assert drained[0].focus == "角度A"
    assert drained[1].ask == "谁兜底？"
    assert take_steers("exec-a") == []
    assert peek_steer_count("exec-a") == 0


def test_fold_empty_is_none():
    assert fold_steers([]) is None


def test_fold_continue_last_wins():
    take_steers("exec-b")
    enqueue_steer(execution_id="exec-b", conversation_id="c", decision="continue", focus="旧")
    enqueue_steer(
        execution_id="exec-b",
        conversation_id="c",
        decision="continue",
        focus="新角度",
        ask="问一句",
        ask_target="con",
    )
    boundary = fold_steers(take_steers("exec-b"))
    assert boundary is not None
    assert boundary.decision is RoundDecision.CONTINUE
    assert boundary.focus == "新角度"
    assert boundary.ask == "问一句"
    assert boundary.ask_target == "con"


def test_fold_conclude_wins_over_continue():
    take_steers("exec-c")
    enqueue_steer(execution_id="exec-c", conversation_id="c", decision="continue", focus="还想辩")
    enqueue_steer(
        execution_id="exec-c",
        conversation_id="c",
        decision="conclude",
        ask="那合规呢？",
    )
    boundary = fold_steers(take_steers("exec-c"))
    assert boundary is not None
    assert boundary.decision is RoundDecision.CONCLUDE
    assert boundary.ask == "那合规呢？"
    assert boundary.focus == ""  # conclude ignores focus

"""turn_worker_stats: delegated/workers口径 for close-line logs + turn_metrics."""

from agentcore.conversation.turn_stats import turn_worker_stats
from agentcore.runtime.costing import ROLE_CAPTAIN, ROLE_MEMBER, ROLE_VISION
from agentcore.runtime.facts import FactKind
from agentcore.runtime.runs.types import RunPhase


def test_workers_from_member_ledger_not_len_minus_one():
    # Vision rows must not count as workers; captain is ignored.
    result = {
        "cost_runs": [
            {"run_id": "ceo", "role": ROLE_CAPTAIN},
            {"run_id": "w1", "role": ROLE_MEMBER},
            {"run_id": "vis_1", "role": ROLE_VISION},
        ]
    }
    assert turn_worker_stats(result) == (True, 1)


def test_workers_zero_when_no_members():
    assert turn_worker_stats({"cost_runs": [{"run_id": "ceo", "role": ROLE_CAPTAIN}]}) == (
        False,
        0,
    )
    assert turn_worker_stats({}) == (False, 0)


def test_journal_completed_workers_when_ledger_not_folded():
    # Checkpoint pause defers member ledger fold — cost_runs is captain-only, but
    # journal already has the finished worker's message_final (e80c6f99 case).
    result = {
        "cost_runs": [{"run_id": "ceo", "role": ROLE_CAPTAIN}],
        "journal_entries": [
            {
                "kind": FactKind.MESSAGE_FINAL.value,
                "payload": {"run_id": "del_x_architect", "phase": RunPhase.COMPLETED.value},
            },
            {
                # Captain bubble: no phase → not a worker.
                "kind": FactKind.MESSAGE_FINAL.value,
                "payload": {"run_id": "ceo", "content": "hi"},
            },
            {
                "kind": FactKind.MESSAGE_FINAL.value,
                "payload": {"run_id": "del_x_failed", "phase": RunPhase.FAILED.value},
            },
        ],
    }
    assert turn_worker_stats(result) == (True, 1)


def test_union_ledger_and_journal_dedupes():
    result = {
        "cost_runs": [{"run_id": "w1", "role": ROLE_MEMBER}],
        "journal_entries": [
            {
                "kind": FactKind.MESSAGE_FINAL.value,
                "payload": {"run_id": "w1", "phase": RunPhase.COMPLETED.value},
            },
            {
                "kind": FactKind.MESSAGE_FINAL.value,
                "payload": {"run_id": "w2", "phase": RunPhase.COMPLETED.value},
            },
        ],
    }
    assert turn_worker_stats(result) == (True, 2)

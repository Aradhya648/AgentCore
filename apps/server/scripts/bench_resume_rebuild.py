"""Measure the resume 'rebuild tax' the ② 挂起即收口 proposal would impose per resolution.

WHY THIS EXISTS (取舍分析 ②, 先量再定):
    Today an in-session checkpoint resolution continues on the SAME warm process (≈0
    rebuild). ② would finalize the run at the pause, so EVERY resolution — even one in
    the same live session — goes through the cold durable resume path, which rebuilds the
    CEO's LLM window by FOLDING the §8.3 turn journal (``window_from_journal``).

    Of all the cold path does, the toolset/backend/profile/history setup is the SAME work
    a normal fresh send already does (an already-accepted latency). The one genuinely NEW
    cost ② adds over the warm path is: load+parse the journal from DB + fold it into the
    window (+ ~2 extra DB round-trips to claim the frame & read the journal). The fold is
    the only part that SCALES with turn size and is environment-independent — so it is the
    decisive number for choosing ②-full vs ②-lite vs none.

WHAT IT MEASURES (no DB, no LLM — deterministic, synthetic journals built from the REAL
    fact dataclasses so the fold sees exactly what the engine produces):
    - ``fold``      : window_from_journal(entries)              — entries already in memory
    - ``parse+fold``: json.loads(journal_blob) + fold           — realistic cold path from
                      the bytes turn_journal stores (claim re-hydrates JSON → dicts → fold)

RUN:  uv run python scripts/bench_resume_rebuild.py
      uv run python scripts/bench_resume_rebuild.py --iters 500
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from agentcore.runtime.facts import (
    LlmCallFact,
    MessageFinalFact,
    RoundBoundaryFact,
    ToolCallFact,
    TurnStartedFact,
)
from agentcore.runtime.journal.fold import window_from_journal

_CAPTAIN = "cap-run"


def _entry(fact) -> dict:
    return fact.to_fact().entry()


def build_journal(
    *,
    captain_rounds: int,
    workers: int,
    tool_calls_per_round: int,
    content_chars: int,
    reasoning_chars: int,
    tool_result_chars: int,
) -> list[dict]:
    """A faithful §8.3 execution journal for a turn paused at a checkpoint.

    Shape mirrors a real delegate turn: a head fact, a fan of finished workers (each a
    round_boundary + llm_call + message_final), then the captain's ReAct rounds (each a
    round_boundary + an llm_call carrying tool_calls + the matching tool_call results).
    The final captain round's suspended call is left WITHOUT a matching tool_call fact —
    exactly how a pause looks (the window ends at the assistant, result pending).
    """
    content = "C" * content_chars
    reasoning = "R" * reasoning_chars
    result = "T" * tool_result_chars
    entries: list[dict] = [
        _entry(
            TurnStartedFact(
                system_prompt="S" * 4000,
                user_message="请基于需求产出方案" * 8,
                model_profile="chat",
                history_len=0,
            )
        )
    ]
    for w in range(workers):
        wid = f"w{w}"
        entries.append(_entry(RoundBoundaryFact(round_idx=0, run_id=wid, role="worker")))
        entries.append(
            _entry(
                LlmCallFact(
                    run_id=wid,
                    round_idx=0,
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=[],
                )
            )
        )
        entries.append(_entry(MessageFinalFact(run_id=wid, content=result, reasoning="")))
    for r in range(captain_rounds):
        entries.append(_entry(RoundBoundaryFact(round_idx=r, run_id=_CAPTAIN, role="captain")))
        suspended = r == captain_rounds - 1
        tcs = [
            {
                "id": f"tc-{r}-{t}",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"a.ts"}'},
            }
            for t in range(tool_calls_per_round)
        ]
        entries.append(
            _entry(
                LlmCallFact(
                    run_id=_CAPTAIN,
                    round_idx=r,
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=tcs,
                )
            )
        )
        # A suspended final round records NO tool_call fact (the pause is inside the call).
        if not suspended:
            for t in range(tool_calls_per_round):
                entries.append(
                    _entry(
                        ToolCallFact(
                            run_id=_CAPTAIN,
                            tool_call_id=f"tc-{r}-{t}",
                            name="read_file",
                            arguments='{"path":"a.ts"}',
                            result=result,
                        )
                    )
                )
    return entries


@dataclass
class Scenario:
    name: str
    captain_rounds: int
    workers: int
    tool_calls_per_round: int
    content_chars: int
    reasoning_chars: int
    tool_result_chars: int


SCENARIOS: list[Scenario] = [
    # name            rounds workers tc/round content reasoning toolres
    Scenario("tiny (pure chat)", 1, 0, 0, 300, 0, 0),
    Scenario("small (few tools)", 3, 0, 1, 600, 400, 800),
    Scenario("medium (delegate ×4)", 6, 4, 2, 1200, 800, 3000),
    Scenario("large (delegate ×8)", 15, 8, 3, 2000, 1500, 6000),
    Scenario("huge (stress, ×16)", 40, 16, 4, 3000, 2500, 12000),
]


def _pctl(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def _time(fn: Callable[[], object], iters: int) -> list[float]:
    out: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=300)
    args = ap.parse_args()

    print(f"resume rebuild-tax bench — {args.iters} iters/scenario (fold = window_from_journal)\n")
    header = (
        f"{'scenario':<22}{'entries':>8}{'win.msgs':>9}{'journal':>9}"
        f"{'fold p50':>10}{'fold p95':>10}{'parse+fold p50':>16}{'parse+fold p95':>16}"
    )
    print(header)
    print("-" * len(header))
    for sc in SCENARIOS:
        entries = build_journal(
            captain_rounds=sc.captain_rounds,
            workers=sc.workers,
            tool_calls_per_round=sc.tool_calls_per_round,
            content_chars=sc.content_chars,
            reasoning_chars=sc.reasoning_chars,
            tool_result_chars=sc.tool_result_chars,
        )
        blob = json.dumps(entries, ensure_ascii=False)
        win = window_from_journal(entries) or []

        fold = _time(lambda e=entries: window_from_journal(e), args.iters)
        parse_fold = _time(lambda b=blob: window_from_journal(json.loads(b)), args.iters)

        kb = f"{len(blob.encode('utf-8')) / 1024:.0f}KB"
        print(
            f"{sc.name:<22}{len(entries):>8}{len(win):>9}{kb:>9}"
            f"{_pctl(fold, 0.5):>9.3f}m{_pctl(fold, 0.95):>9.3f}m"
            f"{_pctl(parse_fold, 0.5):>15.3f}m{_pctl(parse_fold, 0.95):>15.3f}m"
        )

    print(
        "\nm = milliseconds. 'fold' = entries already in memory; 'parse+fold' = the cold path"
        "\nfrom DB bytes (json.loads + fold). The warm in-session path pays ≈0 of this.\n"
        "Cold also adds ~2 DB round-trips (claim frame + read journal) the warm path skips;"
        "\neverything else (toolset/backend/profile/history) == a normal send's startup."
    )


if __name__ == "__main__":
    main()

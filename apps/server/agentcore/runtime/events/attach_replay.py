"""Cursor replay for ``GET …/stream`` with ``Last-Event-ID`` (流式回复持久化 §3.6 · P3).

Builds a clear-then-fold replay segment: **full** durable journal facts from the
turn start (header value is observational only — clients clear-then-fold, so a
``> cursor`` tail would drop pre-cursor tool/team structure) + process-lane
synthetic deltas interleaved in journal order + single-block deltas for any
still-open stream channels not already covered by ``process_*`` /
``run_process_*``. No ``id:`` on synthetic deltas — they attach after the
nearest durable seq.
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.events.disposition import DURABLE_EVENT_TYPES
from agentcore.runtime.events.stream_checkpointer import (
    CHANNEL_CAPTAIN_CONTENT,
    CHANNEL_CAPTAIN_REASONING,
    parse_run_channel,
)
from agentcore.runtime.events.types import EventType, FinishReason, SSEEvent
from agentcore.runtime.facts import EXECUTION_ONLY_KINDS, FactKind
from agentcore.runtime.journal.entries import _PROCESS_PREFIX, _RUN_PROCESS_PREFIX, KIND_TURN_END
from agentcore.runtime.runs.types import RunKind

_DURABLE_KIND_VALUES = frozenset(t.value for t in DURABLE_EVENT_TYPES)
_RUN_TERMINAL = frozenset({EventType.RUN_COMPLETED.value, EventType.RUN_FAILED.value})

# process_* / run_process_* kinds that mirror DURABLE tool / marker events — attach
# skips them and lets the DURABLE event rebuild the step via client fold.
_PROCESS_STRUCTURAL_SUFFIXES = frozenset(
    {
        "tool",
        "team",
        "checkpoint",
        "ask",
        "plan_review",
        "team_preview",
        "escalation",
        "approval",
        "delegation_authorization",
    }
)


def _process_step_to_sse(
    kind: str,
    payload: dict[str, Any],
    *,
    seq: int | None,
    ts: str,
) -> SSEEvent | None:
    """Translate a journaled process / run_process text step into a foldable delta."""
    if kind.startswith(_RUN_PROCESS_PREFIX):
        suffix = kind[len(_RUN_PROCESS_PREFIX) :]
        if suffix in _PROCESS_STRUCTURAL_SUFFIXES:
            return None
        run_id = payload.get("run_id") or ""
        agent_id = payload.get("agent_id") or ""
        if suffix == "reasoning":
            text = payload.get("text") or ""
            if not run_id or not text:
                return None
            return SSEEvent(
                type=EventType.RUN_REASONING_DELTA,
                payload={"run_id": run_id, "agent_id": agent_id, "delta": text},
                timestamp=ts,
                seq=seq,
            )
        if suffix == "content":
            text = payload.get("text") or ""
            if not run_id or not text:
                return None
            return SSEEvent(
                type=EventType.RUN_OUTPUT_DELTA,
                payload={"run_id": run_id, "agent_id": agent_id, "delta": text},
                timestamp=ts,
                seq=seq,
            )
        if suffix == "rework":
            if not run_id:
                return None
            # Journaled rework steps exist ONLY for 交付前核验回炉 (sink persists the
            # trace solely on reason=finish_guard), so the replayed reset says so.
            return SSEEvent(
                type=EventType.RUN_OUTPUT_RESET,
                payload={"run_id": run_id, "agent_id": agent_id, "reason": "finish_guard"},
                timestamp=ts,
                seq=seq,
            )
        return None

    if kind.startswith(_PROCESS_PREFIX):
        suffix = kind[len(_PROCESS_PREFIX) :]
        if suffix in _PROCESS_STRUCTURAL_SUFFIXES:
            return None
        if suffix == "reasoning":
            text = payload.get("text") or ""
            if not text:
                return None
            return SSEEvent(
                type=EventType.REASONING_DELTA,
                payload={"delta": text},
                timestamp=ts,
                seq=seq,
            )
        if suffix == "content":
            text = payload.get("text") or ""
            if not text:
                return None
            return SSEEvent(
                type=EventType.CONTENT_DELTA,
                payload={"delta": text},
                timestamp=ts,
                seq=seq,
            )
        if suffix == "rework":
            return SSEEvent(
                type=EventType.CONTENT_RESET,
                payload={"reason": "finish_guard"},
                timestamp=ts,
                seq=seq,
            )
        return None

    return None


def journal_rows_to_sse(rows: list[dict[str, Any]]) -> list[SSEEvent]:
    """Convert ``load_after`` rows into live-shaped SSE events (with ``seq`` on DURABLE).

    Process-lane facts are emitted as synthetic deltas **in journal order**, interleaved
    with tool/team DURABLE events so clear-then-fold rebuilds the CEO / worker timelines
    with correct interleaving (process progressive persistence invariant).
    """
    final_outputs: dict[str, dict[str, str]] = {}
    agent_run_ids: dict[str, str] = {}
    for row in rows:
        kind = str(row.get("kind") or "")
        payload = dict(row.get("payload") or {})
        if kind == FactKind.MESSAGE_FINAL.value:
            run_id = payload.get("run_id")
            if run_id:
                final_outputs[str(run_id)] = {
                    "content": payload.get("content") or "",
                    "reasoning": payload.get("reasoning") or "",
                }
        elif kind == EventType.RUN_STARTED.value and payload.get("kind") == RunKind.AGENT.value:
            run_id = payload.get("run_id")
            if run_id:
                agent_run_ids[str(run_id)] = payload.get("agent_id") or ""

    out: list[SSEEvent] = []
    for row in rows:
        kind = str(row.get("kind") or "")
        payload = dict(row.get("payload") or {})
        ts = row.get("ts") or ""
        seq_raw = row.get("seq")
        seq_i = int(seq_raw) if seq_raw is not None else None

        if kind == FactKind.MESSAGE_FINAL.value:
            continue
        if kind in EXECUTION_ONLY_KINDS:
            continue

        # Progressive process lane — fold as deltas in order (skip structural mirrors).
        if kind.startswith(_PROCESS_PREFIX) or kind.startswith(_RUN_PROCESS_PREFIX):
            # Fill agent_id on run_process text steps when the payload omitted it.
            if kind.startswith(_RUN_PROCESS_PREFIX) and not payload.get("agent_id"):
                rid = payload.get("run_id")
                if rid and str(rid) in agent_run_ids:
                    payload = {**payload, "agent_id": agent_run_ids[str(rid)]}
            synthetic = _process_step_to_sse(kind, payload, seq=seq_i, ts=ts)
            if synthetic is not None:
                out.append(synthetic)
            continue

        if kind not in _DURABLE_KIND_VALUES:
            continue

        if kind in _RUN_TERMINAL:
            run_id = payload.get("run_id")
            final = final_outputs.get(str(run_id)) if run_id else None
            agent_id = None
            if run_id:
                agent_id = agent_run_ids.get(str(run_id)) or payload.get("agent_id") or None
            if final is not None and agent_id is not None and run_id:
                if final["reasoning"]:
                    out.append(
                        SSEEvent(
                            type=EventType.RUN_REASONING_DELTA,
                            payload={
                                "run_id": run_id,
                                "agent_id": agent_id,
                                "delta": final["reasoning"],
                            },
                            timestamp=ts,
                        )
                    )
                if final["content"]:
                    out.append(
                        SSEEvent(
                            type=EventType.RUN_OUTPUT_DELTA,
                            payload={
                                "run_id": run_id,
                                "agent_id": agent_id,
                                "delta": final["content"],
                            },
                            timestamp=ts,
                        )
                    )

        out.append(
            SSEEvent(
                type=EventType(kind),
                payload=payload,
                timestamp=ts,
                seq=seq_i,
            )
        )
    return out


def _journal_covers_captain_channels(rows: list[dict[str, Any]]) -> tuple[bool, bool]:
    """Whether journal process_* already carries captain content / reasoning text."""
    has_content = False
    has_reasoning = False
    for row in rows:
        kind = str(row.get("kind") or "")
        if kind == f"{_PROCESS_PREFIX}content":
            has_content = True
        elif kind == f"{_PROCESS_PREFIX}reasoning":
            has_reasoning = True
    return has_content, has_reasoning


def journal_is_structured(rows: list[dict[str, Any]]) -> bool:
    """True when the turn has (or will have) a process lane — not prose-only.

    Structured turns must not stitch CEO 旁白 from flat ``captain:content`` segments
    (journal ``process_*`` is the sole narration source). Prose-only turns keep the
    segment accelerate path.
    """
    for row in rows:
        kind = str(row.get("kind") or "")
        if kind.startswith(_PROCESS_PREFIX) or kind.startswith(_RUN_PROCESS_PREFIX):
            return True
        if kind in (
            EventType.TOOL_USE_START.value,
            EventType.TOOL_USE_END.value,
            EventType.RUN_PLAN.value,
            EventType.RUN_STARTED.value,
            EventType.CHECKPOINT_REQUIRED.value,
            EventType.QUESTION_POSTED.value,
            EventType.PLAN_REVIEW_REQUIRED.value,
            EventType.TEAM_PREVIEW_REQUIRED.value,
        ):
            return True
    return False


def _journal_covered_run_ids(rows: list[dict[str, Any]]) -> set[str]:
    """Run ids that already have run_process_* text steps in the journal."""
    covered: set[str] = set()
    for row in rows:
        kind = str(row.get("kind") or "")
        if not kind.startswith(_RUN_PROCESS_PREFIX):
            continue
        suffix = kind[len(_RUN_PROCESS_PREFIX) :]
        if suffix not in ("content", "reasoning"):
            continue
        rid = (row.get("payload") or {}).get("run_id")
        if rid:
            covered.add(str(rid))
    return covered


def synthesize_segment_deltas(
    *,
    by_channel: dict[str, str],
    agent_run_ids: dict[str, str],
    covered_run_ids: set[str],
    skip_captain_content: bool = False,
    skip_captain_reasoning: bool = False,
) -> list[SSEEvent]:
    """Single-block deltas from stream_state / memory (P1 overlay isomorphic).

    When journal already has ``process_*`` / ``run_process_*`` text, skip the matching
    flat channels so mid-run refresh does not duplicate or reorder narration.
    """
    extra: list[SSEEvent] = []
    cap_reasoning = by_channel.get(CHANNEL_CAPTAIN_REASONING) or ""
    cap_content = by_channel.get(CHANNEL_CAPTAIN_CONTENT) or ""
    if cap_reasoning and not skip_captain_reasoning:
        extra.append(SSEEvent(type=EventType.REASONING_DELTA, payload={"delta": cap_reasoning}))
    if cap_content and not skip_captain_content:
        extra.append(SSEEvent(type=EventType.CONTENT_DELTA, payload={"delta": cap_content}))

    partial: dict[str, dict[str, str]] = {}
    for channel, text in by_channel.items():
        parsed = parse_run_channel(channel)
        if parsed is None or not text:
            continue
        run_id, kind = parsed
        slot = partial.setdefault(run_id, {"content": "", "reasoning": ""})
        if kind == "output":
            slot["content"] = text
        else:
            slot["reasoning"] = text

    for run_id, texts in partial.items():
        if run_id in covered_run_ids or run_id not in agent_run_ids:
            continue
        agent_id = agent_run_ids.get(run_id) or ""
        if texts.get("reasoning"):
            extra.append(
                SSEEvent(
                    type=EventType.RUN_REASONING_DELTA,
                    payload={
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "delta": texts["reasoning"],
                    },
                )
            )
        if texts.get("content"):
            extra.append(
                SSEEvent(
                    type=EventType.RUN_OUTPUT_DELTA,
                    payload={
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "delta": texts["content"],
                    },
                )
            )
    return extra


def _turn_end_close_event(rows: list[dict[str, Any]]) -> SSEEvent | None:
    """Synthesize the stream-close ``message_end`` the attach replay otherwise lacks.

    ``message_end`` is DERIVED (never journaled, so :func:`journal_rows_to_sse` drops it)
    and a *detached* turn emits it while the sink is detached — it lands in neither
    ``_history`` nor the re-armed live queue. A client that attaches inside the turn's
    post-completion persist window (``task`` not yet done → the endpoint does not 204)
    therefore replays the durable journal, then the live tail closes immediately
    (sink already closed) with **no** close frame, and the client can only finalize via
    the reconnect-banner error salvage (spurious「重连中」+ bubble stuck streaming).

    When the journal carries ``turn_end`` (the turn is finished) replay a synthetic
    ``message_end`` carrying only ``finish_reason`` so the client finalizes the bubble +
    turn phase normally — ``paused`` still routes to the durable resume card, other
    reasons complete the turn. Usage/cost are omitted (journal ``turn_end`` has neither;
    they live on the Message columns a reload rehydrates) so the frontend's
    undefined-guarded meta merge leaves any hydrated values intact. Returns ``None`` when
    the turn is still running (no ``turn_end`` yet) so the live tail delivers the real
    ``message_end`` unchanged.
    """
    for row in reversed(rows):
        if str(row.get("kind") or "") != KIND_TURN_END:
            continue
        finish_raw = (row.get("payload") or {}).get("finish_reason")
        try:
            finish = FinishReason(finish_raw)
        except ValueError:
            finish = FinishReason.END_TURN
        return SSEEvent(type=EventType.MESSAGE_END, payload={"finish_reason": finish.value})
    return None


async def build_cursor_replay(
    *,
    turn_id: str,
    after_seq: int,
    memory_channels: dict[str, str],
    memory_agent_ids: dict[str, str],
) -> list[SSEEvent]:
    """Full-turn durable journal + in-flight segment synthesis (clear-then-fold).

    ``after_seq`` is the client's ``Last-Event-ID`` — kept for observability /
    future cross-process cursors, but **not** used to filter rows. Clients reset
    local process/execution before folding, so the replay must include
    pre-cursor structure (tools / team graph / process narration), not only
    ``seq > after_seq``.
    """
    from agentcore.conversation.store import get_conversation_store
    from agentcore.core.logging import get_logger
    from agentcore.db.base import telemetry_session_factory
    from agentcore.db.repositories.runs import TurnJournalRepository

    get_logger(__name__).debug(
        "attach.cursor_replay",
        turn_id=turn_id,
        last_event_id=after_seq,
    )

    async with telemetry_session_factory() as db:
        # Full turn from seq 0 (``seq > -1``); header value is observational only.
        rows = await TurnJournalRepository(db).load_after(turn_id, -1)

    events = journal_rows_to_sse(rows)
    skip_cap_content, skip_cap_reasoning = _journal_covers_captain_channels(rows)
    # Structured turns: never stitch 旁白 from flat segments (process_* is the source).
    # Prose-only keeps segment accelerate for captain content / reasoning.
    if journal_is_structured(rows):
        skip_cap_content = True
    process_covered_runs = _journal_covered_run_ids(rows)

    agent_ids = dict(memory_agent_ids)
    covered: set[str] = set(process_covered_runs)
    for ev in events:
        if ev.type == EventType.RUN_STARTED and ev.payload.get("kind") == RunKind.AGENT.value:
            rid = ev.payload.get("run_id")
            if rid:
                agent_ids.setdefault(str(rid), ev.payload.get("agent_id") or "")
        if ev.type in (EventType.RUN_OUTPUT_DELTA, EventType.RUN_REASONING_DELTA):
            rid = ev.payload.get("run_id")
            if rid:
                covered.add(str(rid))

    by_channel = dict(memory_channels)
    if not by_channel:
        store = get_conversation_store()
        segments = await store.list_stream_segments(turn_id=turn_id)
        by_channel = {
            str(s["channel"]): str(s.get("text") or "")
            for s in segments
            if s.get("channel") and s.get("text")
        }

    events.extend(
        synthesize_segment_deltas(
            by_channel=by_channel,
            agent_run_ids=agent_ids,
            covered_run_ids=covered,
            skip_captain_content=skip_cap_content,
            skip_captain_reasoning=skip_cap_reasoning,
        )
    )
    # Close a finished detached turn so a client attaching in the persist window
    # finalizes normally instead of via the reconnect-banner salvage (收口事实回放).
    close = _turn_end_close_event(rows)
    if close is not None:
        events.append(close)
    return events

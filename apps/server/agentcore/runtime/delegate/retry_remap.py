"""retry-failed seed remap：上一回合完成态 seed → 本回合新计划的同 raw 节点。

``retry_failed_chat`` 把上一回合已完成 worker 的 :class:`RunState` 放进
``runtime/retry.py::retry_seed`` contextvar，key 是**旧回合**铸的 run_id
（``del_<旧uuid>_<raw>``）。本回合 CEO 重新 ``delegate``，``DelegateTool`` 无条件铸
**新**前缀 ``del_<新uuid>``，同一逻辑节点的 run_id 变了。``WaveScheduler`` 只按 run_id
精确匹配 ``seed_completed`` —— 旧 key 永不命中 → 已成功 worker 全量重跑（与设计宣称的
「已成功节点跳过」漂移）。

本模块在 ``DelegateTool`` 消费 seed 处把 seed 按 **raw 尾缀**重映射到新计划的同 raw
节点，让 seed 命中、成功节点被调度器跳过。

- builder 铸 id 规则（见 ``runtime/runs/builder.py``）：DAG 计划 ``{prefix}_{raw}``（raw 为
  声明的 ``id``，语义稳定），flat 无依赖批 ``{prefix}_{n}``（数字位置号）。
- **纯数字 raw 是位置号、语义不可靠，不做映射**（跨回合位置会漂）——这些节点照常重跑。
- 不命中（旧 seed 的 raw 在新计划里没有同 raw 节点）的条目丢弃。
- 命中 / 跳过（数字）/ 丢弃（不命中·歧义）均记结构化日志。

命中节点会被 ``WaveScheduler`` 跳过、**不发** ``run_started`` / ``run_completed``。而
retry-failed 已 ``delete_after`` 删掉旧回合 journal、本回合是全新 assistant 消息 →
若不补发，前端图投影会让这些节点永远卡「pending」。resume / 跨回合 append 都不撞这个坑
（两者都保留原 journal，seeded 节点的终态事件已在其中）。故 :func:`replay_seeded_completed`
在本回合如实补发一个已完成 worker 的完整呈现（run_started → 合成 delta → run_completed +
``message_final`` fact），payload 形状与执行器（``executor_node.py``）逐字一致，使 seeded
节点与正常跑过的 worker 无从区分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger

if TYPE_CHECKING:
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunState

logger = get_logger(__name__)


def _raw_suffix(run_id: str) -> str | None:
    """Extract the raw id from a builder-minted run_id ``del_<uuid>_<raw>`` / ``add_<uuid>_<raw>``.

    ``new_id()`` is a uuid4 (hyphen-delimited, never ``_``), so a ``maxsplit=2`` split on
    ``_`` cleanly separates the ``del``/``add`` tag, the uuid, and the raw — and the raw
    itself may carry underscores (``writer_final``) without being clipped. Returns ``None``
    for an id that does not match the minted shape (a captain / hand-built id), which the
    caller drops as unmappable.
    """
    parts = run_id.split("_", 2)
    if len(parts) < 3 or parts[0] not in ("del", "add"):
        return None
    return parts[2] or None


@dataclass
class RetryRemapResult:
    """Outcome of :func:`remap_retry_seed`: the remapped seed + per-bucket audit lists."""

    seed: dict[str, RunState] = field(default_factory=dict)
    # (old_run_id, new_run_id) pairs the remap matched by raw suffix.
    hits: list[tuple[str, str]] = field(default_factory=list)
    # Old seed keys whose raw is a bare position number (flat batch) — not remapped.
    dropped_numeric: list[str] = field(default_factory=list)
    # Old seed keys with no same-raw node in the new plan (or an unmappable id shape).
    dropped_no_match: list[str] = field(default_factory=list)
    # Old seed keys that collide onto an already-claimed new node (multi-batch old turn).
    dropped_ambiguous: list[str] = field(default_factory=list)


def remap_retry_seed(
    seed: dict[str, RunState],
    plan: RunPlan,
    *,
    prefix: str,
) -> RetryRemapResult:
    """Remap an old-turn ``seed`` (run_id → RunState) onto ``plan``'s same-raw nodes.

    ``prefix`` is THIS delegate call's freshly minted id prefix (``del_<uuid>``), used to
    strip the raw suffix off the new plan's node ids precisely. Numeric raws (flat-batch
    position numbers) are skipped on BOTH sides — a position号 can name a different worker
    across turns, so seeding by it would be wrong. A seed whose raw matches no new node is
    dropped; two old seeds mapping to one new node (a multi-batch old turn re-using a raw)
    keep the first and drop the rest as ambiguous. Never raises; a caller with an empty
    result should treat the batch as un-seeded (fresh run).
    """
    result = RetryRemapResult()
    if not seed:
        return result

    # New plan nodes indexed by raw suffix. Strip via the known fresh prefix (precise);
    # fall back to the structural extractor for any node not carrying it (defensive).
    # Skip numeric raws — a flat-batch node's position号 is not a stable identity.
    new_by_raw: dict[str, str] = {}
    pfx = prefix + "_"
    for node in plan.nodes:
        rid = node.run_id
        raw = rid[len(pfx):] if rid.startswith(pfx) else _raw_suffix(rid)
        if not raw or raw.isdigit():
            continue
        # A DAG plan dedups raw ids at build; flat numeric raws are skipped above, so a
        # collision here is not expected — last-write is a harmless defensive default.
        new_by_raw[raw] = rid

    for old_run_id, state in seed.items():
        raw = _raw_suffix(old_run_id)
        if raw is None:
            result.dropped_no_match.append(old_run_id)
            continue
        if raw.isdigit():
            result.dropped_numeric.append(old_run_id)
            continue
        target = new_by_raw.get(raw)
        if target is None:
            result.dropped_no_match.append(old_run_id)
            continue
        if target in result.seed:
            # Two old seeds share a raw (old turn ran multiple batches re-using an id):
            # seeding the new node with either is a guess — drop the later one so the
            # node re-runs rather than inherit a possibly-wrong state.
            result.dropped_ambiguous.append(old_run_id)
            continue
        result.seed[target] = state
        result.hits.append((old_run_id, target))

    logger.info(
        "delegate.retry_seed_remap",
        prefix=prefix,
        hits=[f"{old}->{new}" for old, new in result.hits],
        dropped_numeric=result.dropped_numeric,
        dropped_no_match=result.dropped_no_match,
        dropped_ambiguous=result.dropped_ambiguous,
    )
    return result


def replay_seeded_completed(
    sink: EventSink,
    plan: RunPlan,
    seed: dict[str, RunState],
) -> None:
    """Re-present remapped seed nodes as completed in THIS turn's event stream + journal.

    A ``WaveScheduler``-skipped seed node emits nothing, and retry-failed deleted the old
    turn's journal, so without this the node would sit forever「pending」in the graph
    projection. Emits, per seeded COMPLETED node, the SAME sequence a live worker + a
    cold reload produce — ``run_started`` → synthetic reasoning/output delta → ``run_completed``
    (payload shapes byte-for-byte the executor's) — plus the ``message_final`` fact so a
    reload rebuilds the body via ``_splice_synthetic_deltas``. The deltas are transport-only
    (DERIVED, not journaled), the fact is the durable body source — so live and reload render
    identically. Iterates ``plan.nodes`` (stable order); a seed key not on the plan or a
    non-COMPLETED state is skipped.
    """
    from agentcore.runtime.events import (
        run_completed,
        run_output_delta,
        run_reasoning_delta,
        run_started,
    )
    from agentcore.runtime.facts import record_turn_fact
    from agentcore.runtime.runs.serialize import run_final_fact
    from agentcore.runtime.runs.types import RunPhase

    replayed = 0
    for node in plan.nodes:
        state = seed.get(node.run_id)
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        agent_id = node.agent_id or node.run_id
        sink.emit(
            run_started(
                node.run_id,
                agent_id,
                parent_run_id=node.parent_run_id,
                kind=node.kind,
            )
        )
        if state.reasoning:
            sink.emit(run_reasoning_delta(node.run_id, agent_id, state.reasoning))
        if state.content:
            sink.emit(run_output_delta(node.run_id, agent_id, state.content))
        debrief: dict[str, Any] | None = state.debrief
        sink.emit(
            run_completed(
                node.run_id,
                agent_id,
                output_summary=(debrief or {}).get("summary", ""),
                duration_ms=state.duration_ms,
                role="member",
                model=state.model,
                usage=state.usage,
                cost=state.cost,
                debrief=debrief,
                output_files=state.files_touched or None,
            )
        )
        # message_final fact: reload rebuilds this node's body from it (synthetic deltas)
        # AND completed_from_journal re-seeds it on a later resume of the retry turn.
        record_turn_fact(run_final_fact(node.run_id, state))
        replayed += 1

    if replayed:
        logger.info("delegate.retry_seed_replayed", nodes=replayed)

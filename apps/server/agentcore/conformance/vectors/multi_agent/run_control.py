"""Multi-agent run skip / redirect / stop vectors."""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    message_end,
    message_start,
    run_cancelled,
    run_completed,
    run_context,
    run_failed,
    run_output_delta,
    run_plan,
    run_progress,
    run_skipped,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE, _ctx_block


def _multi_agent_run_skipped_cascade() -> list[SSEEvent]:
    """多 Agent · 级联跳过：上游 r1 失败后下游 r2 从未开跑，wave 收口 emit
    ``run_skipped(reason=cascade)`` —— 图节点折为 skipped「未执行」，而非永久「排队中」。
    同时覆盖 abort 形态：并行未派发的 r3 经 graceful abort 收口为
    ``run_skipped(reason=abort)``（与 cascade 同终态、不同 reason）。"""
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
        {
            "id": "w3",
            "role": "校对员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": ["r1"]},
        {"id": "r3", "agent_id": "w3", "task": "校对", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队。"),
        tool_use_start(
            "dc1",
            "delegate",
            {
                "tasks": [{"role": "研究员"}, {"role": "撰写员"}, {"role": "校对员"}],
                "coordinate": False,
            },
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="调研 → 撰写；并行校对",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_output_delta("r1", "w1", "调研中断"),
        run_failed("r1", "w1", "上游失败：资料源不可用", failure_kind="call"),
        # Cascade: r2 depends on r1 (on_failure=skip) — never dispatched.
        run_skipped("r2", "w2", reason="cascade"),
        # Graceful abort tail: independent r3 never launched before scheduling ended.
        run_skipped("r3", "w3", reason="abort"),
        run_progress(0, 3),
        tool_use_end("dc1", "delegate", success=True, output="团队部分未执行。"),
        content_delta(" 调研失败，下游未执行。"),
        message_end(FinishReason.END_TURN, input_tokens=1500, output_tokens=200, cost=_COST),
    ]


def _multi_agent_run_redirect_ignored() -> list[SSEEvent]:
    """多 Agent · 跑一半改方向 · 忽略路径 (run_redirect Step 4): a user「立即改此人」steer on a
    parallel worker could NOT be applied mid-run — r1 had already reached a terminal (确定性失败)
    state, so the WaveScheduler never cancelled + cold-re-ran it. The ignore AND the user's later
    accept are recorded OUT-OF-BAND (audit 行 ``run.redirect_ignored`` / ``run.outcome_accepted`` +
    the accept-outcome REST endpoint) — NEVER on the SSE stream, so there is NO new event and NO
    ``run_cancelled``. This vector pins that a not-applied redirect leaves the wire projection clean:
    r1 folds as failed, its parallel sibling r2 completes untouched, the turn ends normally
    (progress 1/2 — failed run not counted), and NO phantom cold-re-run node or stuck-running node
    leaks in. (The Step 3B *applied* cold re-run is a separate wire concern, not this path.)"""
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排两位并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        run_output_delta("r1", "w1", "开始调研，但提示过长"),
        run_output_delta("r2", "w2", "开始撰写"),
        # r1 hits a deterministic (non-retryable) failure; the user's mid-flight redirect on r1
        # arrives too late to steer a run that is already terminal — nothing lands on the wire.
        run_failed(
            "r1",
            "w1",
            "上游 400：提示过长（确定性失败，重试无益）",
            failure_kind="call",
        ),
        run_progress(0, 2),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=1200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_progress(1, 2),
        tool_use_end("dc1", "delegate", success=True, output="团队完成（含 1 项失败）。"),
        content_delta(" 撰写已完成；调研步骤失败，可在其详情里接受此结果。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]


def _multi_agent_run_stop_cancels_workers() -> list[SSEEvent]:
    """多 Agent · 整轮 stop：user「停止整轮」aborts the turn while workers are in flight.

    Each running worker emits ``run_cancelled(reason=stop)`` (not redirect). No hot
    ``continue_run`` revision and no cold ``_redir`` handoff — whole-turn abort has no
    per-worker follow-up. Pins: r1+r2 cancelled with reason=stop, no ``_rev*`` / ``_redir``
    nodes, turn ends ``cancelled``."""
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排两位并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        run_output_delta("r1", "w1", "调研进行中……"),
        run_output_delta("r2", "w2", "撰写进行中……"),
        # Whole-turn abort: every in-flight worker gets reason=stop (not redirect).
        run_cancelled("r1", "w1", reason="stop"),
        run_cancelled("r2", "w2", reason="stop"),
        tool_use_end("dc1", "delegate", success=False, output="已停止。"),
        message_end(FinishReason.CANCELLED, input_tokens=800, output_tokens=100, cost=_COST),
    ]


def _multi_agent_run_redirect_hot() -> list[SSEEvent]:
    """多 Agent · 跑一半改方向 · 热续写 (run_redirect Step 3A): user「立即改此人」on a worker
    that already streamed partial output → cancel (reason=redirect) + salvage → hot
    ``continue_run`` revision chain (``r1_rev1``, revision=2, parent_run_id=r1). No cold
    ``_redir`` handoff node. Sibling r2 completes untouched. Pins: r1 cancelled, r1_rev1
    completed as revision child, r2 completed, no ``_redir`` node."""
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排两位并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        # Partial draft already on the wire → salvageable → hot continue_run path.
        run_output_delta("r1", "w1", "初稿：竞品定价区间偏高，建议……"),
        run_cancelled("r1", "w1", reason="redirect"),
        # Hot revision child (not in plan) — synthesized from run_started like multi_agent_revision.
        run_started("r1_rev1", "r1_rev1", parent_run_id=None, continues_run_id="r1"),
        run_context(
            "r1_rev1",
            "r1_rev1",
            [
                _ctx_block(
                    "continuation",
                    "本次改方向（用户立即改此人）",
                    "别写定价区间，改成只比功能差异。",
                )
            ],
        ),
        run_output_delta("r1_rev1", "r1_rev1", "修订稿：按功能差异横评 A/B/C……"),
        run_completed(
            "r1_rev1",
            "r1_rev1",
            output_summary="按新方向完成调研",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=1200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_progress(2, 3),
        tool_use_end("dc1", "delegate", success=True, output="团队完成 2 项任务（含 1 次热改方向）。"),
        content_delta(" 团队已完成；调研按你的新方向热续写过。"),
        message_end(FinishReason.END_TURN, input_tokens=2400, output_tokens=500, cost=_COST),
    ]


def _multi_agent_run_redirect_cold_fallback() -> list[SSEEvent]:
    """多 Agent · 跑一半改方向 · 冷诚实回落 (run_redirect Step 3B): empty/almost-empty worker
    → cancel (reason=redirect) → cold ``{run_id}_redir`` handoff with ``replaces_run_id``.
    No meaningful ``run_output_delta`` before cancel (not salvageable → cold). ``r1_redir`` is
    declared in the initial plan with ``replaces_run_id=r1`` (plan_events shape) so projection
    has the node before ``run_started`` (non-revision starts do not synthesize). Pins: r1
    cancelled, r1_redir completed with replacesRunId=r1, r2 completed."""
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
        {
            "id": "r1_redir",
            "role": "研究员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": []},
        # Cold handoff node (production: plan.add mid-flight). Declared up-front so the
        # oracle has the run before run_started; replaces_run_id marks「接手」.
        {
            "id": "r1_redir",
            "agent_id": "r1_redir",
            "task": "调研",
            "depends_on": [],
            "replaces_run_id": "r1",
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排两位并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}], "coordinate": False},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        # No meaningful output before cancel → empty transcript → cold _redir fallback.
        run_cancelled("r1", "w1", reason="redirect"),
        run_started("r1_redir", "r1_redir", replaces_run_id="r1"),
        run_output_delta("r1_redir", "r1_redir", "接手稿：按新方向重做调研……"),
        run_completed(
            "r1_redir",
            "r1_redir",
            output_summary="接手完成调研",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=1200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_progress(2, 3),
        tool_use_end("dc1", "delegate", success=True, output="团队完成 2 项任务（含 1 次冷接手）。"),
        content_delta(" 团队已完成；调研由接手节点按新方向重跑。"),
        message_end(FinishReason.END_TURN, input_tokens=2200, output_tokens=450, cost=_COST),
    ]

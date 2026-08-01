"""Multi-agent worker activity phase (``run_phase``) vectors."""

from __future__ import annotations

from agentcore.runtime.events import (
    SSEEvent,
    content_delta,
    message_start,
    run_phase,
    run_plan,
    run_skipped,
    run_started,
    run_tool_progress,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV


def _multi_agent_run_phase() -> list[SSEEvent]:
    """Worker 活动相位：thinking → tool → waiting_children → winding_down；
    并行节点 pending（queued）+ run_skipped（skipped 走 status）。

    无 ``message_end``：保留 mid-flight 快照，golden 上 r1.phase=winding_down、
    r2.status=pending、r3.status=skipped。
    """
    agents = [
        {"id": "w1", "role": "小组长", "thinking": True},
        {"id": "w2", "role": "排队队员", "thinking": True},
        {"id": "w3", "role": "未执行队员", "thinking": True},
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "带队改码", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "等槽位", "depends_on": []},
        {"id": "r3", "agent_id": "w3", "task": "级联未跑", "depends_on": ["r1"]},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("组队中。"),
        run_plan(
            execution_id="exec-phase",
            plan_type="multi_agent",
            task_summary="相位可区分",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_phase("r1", "w1", "thinking"),
        run_tool_progress("r1", "w1", "file_read", 40),
        run_phase("r1", "w1", "tool", tool_name="file_read"),
        tool_use_start("tc1", "file_read", {"path": "a.ts"}, run_id="r1"),
        tool_use_end("tc1", "file_read", success=True, output="ok", run_id="r1"),
        run_phase("r1", "w1", "thinking"),
        run_phase("r1", "w1", "waiting_children"),
        # Nested wall ends → back to thinking, then token/timeout soft-top.
        run_phase("r1", "w1", "thinking"),
        run_phase("r1", "w1", "winding_down"),
        # thinking/tool must not override winding_down sticky.
        run_phase("r1", "w1", "thinking"),
        run_phase("r1", "w1", "tool", tool_name="handoff"),
        # r2 stays pending (= queued). r3 never ran → skipped.
        run_skipped("r3", "w3", reason="cascade"),
    ]

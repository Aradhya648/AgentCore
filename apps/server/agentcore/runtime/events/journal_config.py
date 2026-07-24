"""Journal / history / process constants shared by EventSink."""

from __future__ import annotations

from agentcore.runtime.events.disposition import DURABLE_EVENT_TYPES
from agentcore.runtime.events.types import EventType

# 落 journal 的事件 = 处置表里所有 DURABLE（单一源见 events/disposition.py）。历史上这里手
# 维护第二份清单，与处置表两处易漂移、新增事件易静默遗漏；现直接复用派生集——新增 DURABLE
# 只在 disposition.py 声明一处，穷尽门禁（tests/test_event_disposition.py）保证不漏。
# 各 DURABLE 事件的落库理由见 disposition.py 的 EVENT_DISPOSITION 注释。
_JOURNAL_EVENT_TYPES = DURABLE_EVENT_TYPES

# Surface = 「客户端可见 journal 非空」的门槛事件。无 surface → execution_journal /
# runs_from_entries 对外清空 events（DURABLE 仍落 fact log）。对齐 question_posted
# 先例：单聊仅有热审批 / 委派授权 / 升级时也必须能过 gate，否则 reload 丢痕迹（D5）。
_JOURNAL_SURFACE_TYPES = frozenset(
    {
        EventType.RUN_PLAN.value,
        EventType.GRAPH_APPEND.value,
        EventType.CHECKPOINT_REQUIRED.value,
        EventType.QUESTION_POSTED.value,
        EventType.PLAN_REVIEW_REQUIRED.value,
        EventType.TEAM_PREVIEW_REQUIRED.value,
        EventType.APPROVAL_REQUIRED.value,
        EventType.DELEGATION_AUTHORIZATION_REQUIRED.value,
        EventType.ESCALATION_REQUIRED.value,
        EventType.RUN_ESCALATION.value,
    }
)

_PROCESS_RESULT_CAP = 8000


def cap_process_result(result: object) -> object:
    """Cap a tool result string for process projection / history replay.

    Shared by ``EventSink._accumulate_process`` and the conformance oracle so live,
    reload, and golden agree on oversized tool outputs."""
    if isinstance(result, str) and len(result) > _PROCESS_RESULT_CAP:
        return result[:_PROCESS_RESULT_CAP] + "…"
    return result

_HISTORY_SKIP_TYPES = frozenset(
    {
        EventType.TOOL_PROGRESS,
        # 工具执行阶段进度 (transport-only liveliness): like TOOL_PROGRESS, a running-tool
        # phase ping is live-stream only — not replayed on reload (the tool is already done)
        # and never journaled / accumulated into the process timeline.
        EventType.TOOL_USE_PROGRESS,
        EventType.RUN_TOOL_PROGRESS,
        EventType.MESSAGE_END,
        EventType.ERROR,
        EventType.WORKSPACE_OP_REQUIRED,
        EventType.HANDOFF_SNAPSHOT_DONE,
        EventType.HANDOFF_JOB_STARTED,
        EventType.HANDOFF_APPLY_DONE,
    }
)

_HISTORY_COALESCE_TURN = frozenset({EventType.CONTENT_DELTA, EventType.REASONING_DELTA})

_HISTORY_COALESCE_RUN = frozenset({EventType.RUN_OUTPUT_DELTA, EventType.RUN_REASONING_DELTA})

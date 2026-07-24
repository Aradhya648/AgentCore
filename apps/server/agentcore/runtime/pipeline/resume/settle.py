"""Resume settle helpers — transcript splice + façade over ``recover_turn``.

``SettledSuspension`` lives in :mod:`agentcore.runtime.recover` (avoids a
pipeline↔recover import cycle); re-exported here for historical imports.
"""

from __future__ import annotations

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.events import EventSink, tool_use_end
from agentcore.runtime.facts import ToolCallFact, record_turn_fact
from agentcore.runtime.recover import SettledSuspension
from agentcore.runtime.suspension import TurnSuspension
from agentcore.runtime.turn_state import TurnState
from agentcore.tools.builtin.debate import DebateTool
from agentcore.tools.builtin.delegate import DelegateTool

__all__ = [
    "SettledSuspension",
    "append_resumed_tool_results",
    "persist_resumed_tool_results",
    "settle_resumed_suspension",
]

_SIBLING_SKIPPED = "（该并行工具调用在本回合暂停时未保留结果，已跳过。）"


def append_resumed_tool_results(
    messages: list[LLMMessage], tool_call_id: str, output: str
) -> None:
    """Close the suspended tool-call in the rebuilt CEO transcript (结构化挂起 2b).

    The transcript ends with the assistant message that issued the suspended call
    (``delegate`` / ``debate`` for kickoff, ``ask_user`` for ask_user — the pause
    happened inside it). Append the settled result as that call's tool result so the
    loop continues from a valid assistant-tool_call → tool-result pair. Any SIBLING
    tool_calls in the same assistant turn (a rare concurrent call) get a placeholder
    result, since every tool_call MUST have a matching result or the next request
    400s — their work wasn't captured (the pause unwound only the suspended call).
    """
    last = messages[-1] if messages else None
    if last is None or last.role != "assistant" or not last.tool_calls:
        messages.append(LLMMessage(role="tool", content=output, tool_call_id=tool_call_id))
        return
    target = tool_call_id or (last.tool_calls[0].id if last.tool_calls else "")
    for tc in last.tool_calls:
        if tc.id == target:
            messages.append(LLMMessage(role="tool", content=output, tool_call_id=tc.id))
        else:
            messages.append(
                LLMMessage(
                    role="tool",
                    content=_SIBLING_SKIPPED,
                    tool_call_id=tc.id,
                )
            )


def persist_resumed_tool_results(
    transcript: list[LLMMessage],
    *,
    tool_call_id: str,
    output: str,
    run_id: str,
    sink: EventSink,
    tool_name: str = "",
) -> None:
    """Persist settled tool results into the turn journal after resume settle.

    Pause deliberately skips ``ToolCallFact`` / ``tool_use_end`` (no phantom result).
    Once the user answers, the result is real — record it so a later same-turn re-pause
    folds a closed assistant→tool pair via ``window_from_journal``.
    """
    last = transcript[-1] if transcript else None
    if last is None or last.role != "assistant" or not last.tool_calls:
        name = tool_name or "tool"
        tcid = tool_call_id or ""
        if not tcid:
            return
        record_turn_fact(
            ToolCallFact(
                run_id=run_id,
                tool_call_id=tcid,
                name=name,
                arguments="",
                result=output,
                success=True,
            ).to_fact()
        )
        sink.emit(tool_use_end(tcid, name, success=True, output=output, run_id=run_id))
        return

    target = tool_call_id or (last.tool_calls[0].id if last.tool_calls else "")
    for tc in last.tool_calls:
        name = tc.function.name or tool_name or "tool"
        args = tc.function.arguments or ""
        result = output if tc.id == target else _SIBLING_SKIPPED
        record_turn_fact(
            ToolCallFact(
                run_id=run_id,
                tool_call_id=tc.id,
                name=name,
                arguments=args,
                result=result,
                success=True,
            ).to_fact()
        )
        sink.emit(tool_use_end(tc.id, name, success=True, output=result, run_id=run_id))


async def settle_resumed_suspension(
    suspension: TurnSuspension,
    *,
    decision: CheckpointDecision,
    note: str,
    selected: list[str],
    sink: EventSink,
    delegate_tool: DelegateTool,
    execution_id: str,
    debate_tool: DebateTool | None = None,
    style_id: str | None = None,
) -> SettledSuspension:
    """Façade: project via ``TurnState.from_journal``, then ``recover_turn``."""
    from agentcore.runtime.recover import recover_turn

    state = TurnState.from_journal(
        suspension.journal_entries,
        display_journal=suspension.journal,
    )
    return await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=delegate_tool,
        debate_tool=debate_tool,
        execution_id=execution_id,
        suspension=suspension,
        decision=decision,
        note=note,
        selected=selected,
        style_id=style_id,
    )

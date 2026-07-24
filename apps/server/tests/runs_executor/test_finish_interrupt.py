"""Worker LLM stream abort at finish must not silently look like a clean COMPLETED.

Accident shape: file_write lands, then the next (handoff) round is post-commit
disconnected → react_loop returns ERROR/DEGRADED via finish_override_sink. Contract
still passes on files_written>0; we keep COMPLETED but warn + synth degraded debrief
so CEO collect_worker_gaps surfaces the gap.
"""

from agentcore.llm.provider.protocol import LLMChunk, ToolCallDelta
from agentcore.runtime.delegate.completion import (
    collect_worker_gaps,
    format_worker_gaps_block,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.executor import build_agent_executor
from agentcore.runtime.runs.executor_shared import FINISH_INTERRUPT_WARNING
from agentcore.runtime.runs.types import RunPhase
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.tools.builtin.handoff import HandoffTool
from agentcore.tools.registry import ToolRegistry
from tests.runs_executor.conftest import _ContentProvider, _ctx, _FileWriteTool, _ScriptedRounds


def _file_write_then_abort(*, with_partial: bool) -> list[list[LLMChunk]]:
    write = [
        LLMChunk(
            delta_tool_calls=[
                ToolCallDelta(
                    index=0,
                    id="w1",
                    function_name="file_write",
                    arguments_delta='{"path": "out.txt", "content": "hi"}',
                )
            ]
        )
    ]
    if with_partial:
        finish = [LLMChunk(delta_content="半成品收尾"), LLMChunk(aborted=True)]
    else:
        finish = [LLMChunk(aborted=True)]
    return [write, finish]


async def _run_abort_worker(*, with_partial: bool):
    plan, _ = build_run_plan([{"role": "实现", "task": "写文件并交接"}], id_prefix="t")
    reg = ToolRegistry()
    reg.register(_FileWriteTool())
    reg.register(HandoffTool())
    provider = _ScriptedRounds(_file_write_then_abort(with_partial=with_partial))
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="req",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    return plan, res["t_1"]


async def test_abort_after_file_write_completes_with_warning_and_degraded_debrief():
    """ERROR finish (no partial prose) + files_written>0 → COMPLETED + gap signals."""
    plan, state = await _run_abort_worker(with_partial=False)
    assert state.phase is RunPhase.COMPLETED
    assert state.files_touched == ["out.txt"]
    assert FINISH_INTERRUPT_WARNING in state.warnings
    assert state.debrief is not None
    assert state.debrief.get("degraded") is True

    gaps = collect_worker_gaps(plan, {"t_1": state})
    assert gaps
    block = format_worker_gaps_block(gaps)
    assert "契约缺口" in block
    assert "实现" in block
    assert "收尾时中断" in block
    assert "降级合成" in block


async def test_abort_with_partial_content_also_flags_finish_interrupt():
    """DEGRADED finish (partial prose kept) is the same soft-interrupt class."""
    _, state = await _run_abort_worker(with_partial=True)
    assert state.phase is RunPhase.COMPLETED
    assert FINISH_INTERRUPT_WARNING in state.warnings
    assert state.debrief is not None and state.debrief.get("degraded") is True


async def test_clean_success_has_no_finish_interrupt_warning():
    """Regression: a normal content answer must not pick up the interrupt warning."""
    plan, _ = build_run_plan([{"role": "分析", "task": "出结论"}], id_prefix="t")
    provider = _ContentProvider(["完整交付正文"])
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="req",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    state = res["t_1"]
    assert state.phase is RunPhase.COMPLETED
    assert state.warnings == []
    assert FINISH_INTERRUPT_WARNING not in (state.warnings or [])
    assert not collect_worker_gaps(plan, res)

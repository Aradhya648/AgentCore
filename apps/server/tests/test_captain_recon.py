"""B2: captain recon harvest → worker opening inject."""

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.delegate.captain_recon import (
    captain_recon_heading,
    harvest_captain_recon,
    resolve_captain_recon_for_delegate,
)
from agentcore.runtime.runs.executor_context import _build_messages
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec


def _tc(name: str, args: str, call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        type="function",
        function=ToolCallFunction(name=name, arguments=args),
    )


def test_harvest_captain_recon_from_transcript():
    messages = [
        LLMMessage(role="user", content="帮我启动"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                _tc("file_list", '{"directory":"."}', "c1"),
                _tc("file_read", '{"path":"package.json"}', "c2"),
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="c1",
            content="package.json\nsrc/\nREADME.md",
        ),
        LLMMessage(
            role="tool",
            tool_call_id="c2",
            content='{"name":"whiteboard","scripts":{"dev":"vite"}}',
        ),
    ]
    brief = harvest_captain_recon(messages)
    assert "file_list" in brief
    assert "package.json" in brief
    assert "whiteboard" in brief
    assert "vite" in brief


def test_harvest_skips_failed_tools_and_empty():
    messages = [
        LLMMessage(
            role="assistant",
            tool_calls=[_tc("file_read", '{"path":"x.ts"}', "f1")],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="f1",
            content="错误：文件不存在<!--agentcore:tool_failed-->",
        ),
    ]
    assert harvest_captain_recon(messages) == ""


def test_harvest_keeps_most_recent_entries():
    calls = []
    results = []
    for i in range(8):
        cid = f"c{i}"
        calls.append(_tc("file_read", f'{{"path":"f{i}.ts"}}', cid))
        results.append(LLMMessage(role="tool", tool_call_id=cid, content=f"body-{i}"))
    messages = [
        LLMMessage(role="assistant", tool_calls=calls),
        *results,
    ]
    brief = harvest_captain_recon(messages, max_entries=3)
    assert "f5.ts" in brief
    assert "f7.ts" in brief
    assert "f0.ts" not in brief


def test_resolve_skips_nested_depth():
    assert resolve_captain_recon_for_delegate(depth=1) == ""
    assert resolve_captain_recon_for_delegate(depth=2) == ""


def test_build_messages_includes_captain_recon_block():
    plan = RunPlan()
    plan.add(RunSpec(run_id="w0", role="运维", task="启动", agent_id="w0"))
    msgs = _build_messages(
        plan,
        plan.by_id("w0"),
        {},
        "SYS",
        "帮我启动",
        captain_recon="- `file_list` `.` →\npackage.json\nsrc/",
    )
    user = msgs[1].content or ""
    assert captain_recon_heading() in user
    assert "package.json" in user
    assert "勿再无增量" in user

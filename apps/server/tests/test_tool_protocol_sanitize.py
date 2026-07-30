"""供应商工具协议标签清洗（LongCat 等残留 → 合法工具名 / 干净正文）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.core.types import ToolCategory
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.runtime.engine.tool_protocol_sanitize import (
    sanitize_protocol_text,
    sanitize_tool_args,
    sanitize_tool_name,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.serialize import debrief_from_transcript
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_sanitize_tool_name_strips_longcat_arg_key():
    assert sanitize_tool_name("web_query</longcat_arg_key>") == "web_query"
    assert sanitize_tool_name("<longcat_tool_call>web_search") == "web_search"
    assert sanitize_tool_name("web_search") == "web_search"


def test_sanitize_protocol_text_strips_tool_call_tags():
    raw = "结论如下<longcat_tool_call>勿泄漏</longcat_tool_call>完。"
    cleaned = sanitize_protocol_text(raw)
    assert "<longcat" not in cleaned
    assert "结论如下" in cleaned
    assert "完。" in cleaned


def test_sanitize_tool_args_recursive():
    args = {
        "summary": "要点</longcat_arg_key>",
        "key_points": ["a<longcat_tool_call>", "b"],
        "nested": {"q": "x</longcat_arg_value>"},
    }
    out = sanitize_tool_args(args)
    assert out["summary"] == "要点"
    assert out["key_points"][0] == "a"
    assert out["nested"]["q"] == "x"


def test_sanitize_raw_tool_arguments_strips_xml_hybrid():
    from agentcore.runtime.engine.tool_protocol_sanitize import (
        sanitize_raw_tool_arguments,
    )

    raw = (
        '{"tasks"><parameter name="list"><object>'
        '<parameter name="role": "导师审稿人", "task": "审阅全文"}'
    )
    cleaned = sanitize_raw_tool_arguments(raw)
    assert "<parameter" not in cleaned
    assert "<object>" not in cleaned
    assert '"tasks":' in cleaned
    assert '"role":' in cleaned
    # Salvageable enough to parse as JSON object with tasks key shape attempt.
    # Full array brackets may still be missing — parse honesty preserved if invalid.
    assert cleaned.startswith('{"tasks":')


def test_sanitize_raw_tool_arguments_noop_on_clean_json():
    from agentcore.runtime.engine.tool_protocol_sanitize import (
        sanitize_raw_tool_arguments,
    )

    raw = '{"tasks": [{"role": "研究员", "task": "调研"}]}'
    assert sanitize_raw_tool_arguments(raw) == raw


@pytest.mark.asyncio
async def test_execute_tools_sanitizes_name_and_runs():
    class _Echo:
        def __init__(self) -> None:
            self.seen: dict | None = None

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="web_search",
                description="stub",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                category=ToolCategory.SEARCH,
            )

        async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
            self.seen = arguments
            return ToolResult(tool_call_id="", success=True, output="ok")

    echo = _Echo()
    reg = ToolRegistry()
    reg.register(echo)
    tc = ToolCall(
        id="c1",
        function=ToolCallFunction(
            name="web_search</longcat_arg_key>",
            arguments=json.dumps({"query": "茉莉奶白 LV</longcat_arg_value>"}, ensure_ascii=False),
        ),
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )
    msgs, terminal, attempts = await execute_tools([tc], reg, ctx, EventSink())
    assert terminal is None
    assert attempts[0].success is True
    assert tc.function.name == "web_search"
    assert echo.seen is not None
    assert echo.seen["query"] == "茉莉奶白 LV"
    assert msgs[0].content == "ok"


@pytest.mark.asyncio
async def test_execute_tools_not_found_mentions_protocol_strip():
    reg = ToolRegistry()
    tc = ToolCall(
        id="c1",
        function=ToolCallFunction(name="web_query</longcat_arg_key>", arguments="{}"),
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )
    msgs, _, attempts = await execute_tools([tc], reg, ctx, EventSink())
    assert attempts[0].success is False
    assert "not found" in msgs[0].content
    assert "协议标签" in msgs[0].content


@pytest.mark.asyncio
async def test_execute_tools_worker_only_miss_is_actionable_policy():
    """CEO-style empty registry calling code_execute must not look like a typo."""
    reg = ToolRegistry()
    tc = ToolCall(
        id="c1",
        function=ToolCallFunction(name="code_execute", arguments="{}"),
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="ceo",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )
    msgs, _, attempts = await execute_tools([tc], reg, ctx, EventSink())
    assert attempts[0].success is False
    assert attempts[0].policy_failure is True
    assert "delegate" in msgs[0].content
    assert "not found" not in msgs[0].content.lower()


@pytest.mark.asyncio
async def test_execute_tools_file_write_miss_points_to_delegate():
    reg = ToolRegistry()
    tc = ToolCall(
        id="c1",
        function=ToolCallFunction(name="file_write", arguments="{}"),
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="ceo",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )
    msgs, _, attempts = await execute_tools([tc], reg, ctx, EventSink())
    assert attempts[0].policy_failure is True
    assert "delegate" in msgs[0].content
    assert "worker" in msgs[0].content.lower() or "委派" in msgs[0].content


def test_debrief_strips_protocol_tags_from_handoff_fields():
    transcript = [
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="h1",
                    function=ToolCallFunction(
                        name="handoff",
                        arguments=json.dumps(
                            {
                                "summary": "交叉验证完成<longcat_tool_call>",
                                "key_points": ["共识</longcat_arg_key>"],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            ],
        )
    ]
    debrief = debrief_from_transcript(transcript)
    assert debrief is not None
    assert debrief["summary"] == "交叉验证完成"
    assert debrief["key_points"] == ["共识"]

"""Unit tests for forced-finalize coordination-tool filtering."""

import pytest

from agentcore.core.types import ToolCategory
from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCallDelta
from agentcore.runtime.engine.constants import (
    FINALIZE_COORDINATION_TOOLS,
    FINALIZE_INSTRUCTION_FILES,
    FINALIZE_PERSIST_TOOLS,
)
from agentcore.runtime.engine.finalize import force_finalize, run_finalize_round
from agentcore.runtime.engine.governance import (
    finalize_allows_persist,
    resolve_finalize_coordination_tools,
)
from agentcore.tools.protocol import ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from tests.llm_helpers import make_profile_params


def _tool_chunk(name: str, args: str = "{}", *, call_id: str = "c1") -> LLMChunk:
    return LLMChunk(
        delta_tool_calls=[
            ToolCallDelta(index=0, id=call_id, function_name=name, arguments_delta=args)
        ]
    )


def _content_chunk(text: str) -> LLMChunk:
    return LLMChunk(delta_content=text)


class _ScriptedProvider:
    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0
        self.last_tool_choice: str | None = None
        self.last_tool_names: list[str] | None = None

    async def stream(self, request):  # noqa: ANN001
        self.last_tool_choice = request.tool_choice
        self.last_tool_names = [t["function"]["name"] for t in (request.tools or [])]
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _StubTool:
    def __init__(self, name: str, *, category: ToolCategory = ToolCategory.SEARCH) -> None:
        self._name = name
        self._category = category

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=self._category,
        )

    async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001
        return ToolResult(tool_call_id="", success=True, output="ok")


def _registry(*, with_persist: bool = False) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_StubTool("file_read", category=ToolCategory.FILESYSTEM))
    reg.register(_StubTool("delegate", category=ToolCategory.ORCHESTRATION))
    reg.register(_StubTool("consult_skill", category=ToolCategory.ORCHESTRATION))
    reg.register(_StubTool("ask_user", category=ToolCategory.INTERACTION))
    if with_persist:
        reg.register(_StubTool("file_write", category=ToolCategory.FILESYSTEM))
        reg.register(_StubTool("handoff", category=ToolCategory.ORCHESTRATION))
    return reg


def test_resolve_finalize_coordination_tools_filters_to_allowlist():
    reg = _registry()
    defs = resolve_finalize_coordination_tools(reg, None, set())
    names = {d["function"]["name"] for d in (defs or [])}
    assert names == FINALIZE_COORDINATION_TOOLS
    assert "file_read" not in names


def test_files_form_force_finalize_surface_keeps_file_write_and_handoff():
    """requires_files / form=files：force_finalize 工具面含 file_write+handoff。"""
    reg = _registry(with_persist=True)
    assert finalize_allows_persist(reg, None) is True
    defs = resolve_finalize_coordination_tools(reg, None, set())
    names = {d["function"]["name"] for d in (defs or [])}
    assert names >= FINALIZE_PERSIST_TOOLS
    assert "file_write" in names
    assert "handoff" in names
    assert "file_read" not in names
    # prose path: file_write withheld from allow-list → coordination only
    prose_allowed = ["delegate", "consult_skill", "ask_user", "file_read"]
    assert finalize_allows_persist(reg, prose_allowed) is False
    prose_defs = resolve_finalize_coordination_tools(reg, prose_allowed, set())
    prose_names = {d["function"]["name"] for d in (prose_defs or [])}
    assert prose_names == FINALIZE_COORDINATION_TOOLS
    assert "file_write" not in prose_names


@pytest.mark.asyncio
async def test_files_form_finalize_round_offers_persist_tools_and_instruction():
    provider = _ScriptedProvider([[_content_chunk("已落盘")]])
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry(with_persist=True)
    result = await run_finalize_round(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=["file_write", "handoff", "web_search", "delegate"],
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
    )
    assert result.kind == "answer"
    assert "file_write" in (provider.last_tool_names or [])
    assert "handoff" in (provider.last_tool_names or [])
    assert "web_search" not in (provider.last_tool_names or [])
    assert any(
        FINALIZE_INSTRUCTION_FILES in (m.content or "") for m in messages
    )


@pytest.mark.asyncio
async def test_soft_finalize_uses_coordination_tools_not_none():
    provider = _ScriptedProvider([[_content_chunk("收尾答案")]])
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry()
    result = await run_finalize_round(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=None,
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
    )
    assert result.kind == "answer"
    assert provider.last_tool_choice == "auto"
    assert set(provider.last_tool_names or []) == FINALIZE_COORDINATION_TOOLS


@pytest.mark.asyncio
async def test_soft_finalize_returns_coordination_tool_calls():
    provider = _ScriptedProvider([[_tool_chunk("delegate", '{"tasks":[]}')]])
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry()
    result = await run_finalize_round(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=None,
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
    )
    assert result.kind == "coordination_tools"
    assert result.tool_calls is not None
    assert result.tool_calls[0].function.name == "delegate"


@pytest.mark.asyncio
async def test_force_finalize_wall_timeout_salvages_prior(monkeypatch):
    """Absolute wall on finalize stream → prior deliverable (no zombie wait)."""
    import asyncio

    from agentcore.config import settings
    from agentcore.llm.provider.protocol import TokenUsage

    monkeypatch.setattr(settings, "engine_force_finalize_wall_seconds", 0.05)

    class _HangProvider:
        calls = 0

        async def stream(self, request):  # noqa: ANN001
            self.calls += 1
            await asyncio.sleep(10)
            yield _content_chunk("should-not-appear")

    provider = _HangProvider()
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry()
    content, _r, _u, _rounds, coordination = await force_finalize(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=None,
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
        final_content="prior draft",
        final_reasoning="",
        total_usage=TokenUsage(),
        rounds=3,
        reason="token_budget",
        run_id="w1",
    )
    assert coordination is None
    assert content == "prior draft"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_force_finalize_skips_empty_inventory():
    """零正文 ∧ 零落盘 ∧ 无 brief → 跳过无意义 LLM salvage。"""
    from agentcore.llm.provider.protocol import TokenUsage

    provider = _ScriptedProvider([[_content_chunk("should-not-run")]])
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry()
    content, _r, _u, _rounds, coordination = await force_finalize(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=None,
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
        final_content="",
        final_reasoning="",
        total_usage=TokenUsage(),
        rounds=3,
        reason="max_rounds",
        run_id="w1",
    )
    assert coordination is None
    assert content == ""
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_empty_soft_finalize_with_prior_falls_back_to_tool_free():
    """有 prior 半成品时：empty soft → hard tool-free salvage 仍可用。"""
    provider = _ScriptedProvider([[], [_content_chunk("hard answer")]])
    messages = [LLMMessage(role="user", content="go")]
    reg = _registry()
    content, _r, _u, _rounds, coordination = await force_finalize(
        messages=messages,
        llm=provider,
        profile=make_profile_params(),
        active_model="m",
        tools=reg,
        allowed_tool_names=None,
        disabled_tools=set(),
        emit_content=lambda _d: None,
        emit_reasoning=lambda _d: None,
        final_content="prior draft",
        final_reasoning="",
        total_usage=__import__(
            "agentcore.llm.provider.protocol", fromlist=["TokenUsage"]
        ).TokenUsage(),
        rounds=3,
        reason="convergence",
    )
    assert coordination is None
    assert "hard answer" in content
    assert provider.calls == 2
    assert provider.last_tool_choice == "none"

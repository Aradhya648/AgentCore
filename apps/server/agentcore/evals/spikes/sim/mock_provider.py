"""Scripted LLM provider for zero-cost spike runs."""

from __future__ import annotations

from agentcore.llm.provider.protocol import LLMChunk, LLMResponse, TokenUsage, ToolCallDelta


def content_chunk(text: str, *, usage: TokenUsage | None = None) -> LLMChunk:
    return LLMChunk(delta_content=text, usage=usage)


def tool_chunk(name: str, args: str, *, call_id: str = "c1") -> LLMChunk:
    return LLMChunk(
        delta_tool_calls=[
            ToolCallDelta(index=0, id=call_id, function_name=name, arguments_delta=args)
        ]
    )


class ScriptedProvider:
    """Yields pre-scripted chunk lists per ``stream`` call (one list = one ReAct round)."""

    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0

    async def stream(self, request):  # noqa: ANN001
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk

    async def complete(self, request):  # noqa: ANN001
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        text = "".join(c.delta_content or "" for c in chunks)
        return LLMResponse(content=text, model=request.model)


def mock_move_then_summarize() -> ScriptedProvider:
    """One tick: tool move_to → short summary."""
    return ScriptedProvider(
        [
            [tool_chunk("move_to", '{"destination":"市场","reason":"去进面粉"}')],
            [content_chunk("我去市场进面粉，得赶在早市前。")],
        ]
    )

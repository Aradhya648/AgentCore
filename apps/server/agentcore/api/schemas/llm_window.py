"""Diagnostic LLM window projection schemas (§8.3 window_from_journal wire shape)."""

from typing import Literal

from pydantic import BaseModel, Field


class LlmWindowToolCallFunction(BaseModel):
    name: str
    arguments: str


class LlmWindowToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: LlmWindowToolCallFunction


class LlmWindowMessageLine(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[LlmWindowToolCall] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    # Diagnostic merge tag: ``context_blocks`` = opening user was rendered from the
    # structured ``run_context`` ContextBlock list (UI substitutes those segments and
    # offers「查看原始拼接」for this full ``content``). Absent / null for other messages.
    origin: str | None = None


class RunLlmWindowResponse(BaseModel):
    """One run's folded LLM input window for a turn (diagnostic replay)."""

    run_id: str
    available: bool = Field(
        description="False when the journal lacks execution facts to fold a window."
    )
    messages: list[LlmWindowMessageLine] = Field(default_factory=list)

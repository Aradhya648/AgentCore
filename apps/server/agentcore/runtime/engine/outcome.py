"""RoundOutcome: the single typed fact object one ReAct round produces."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentcore.llm.provider.protocol import LLMMessage, TokenUsage, ToolCall
from agentcore.runtime.loop_controller import ToolAttempt


@dataclass(frozen=True)
class RoundOutcome:
    """What one ReAct round produced — the single fact object governance reads.

    One shape for every round flavor (a clean answer, a tool round, an empty
    response, an LLM failure), so the loop body is a single outcome → directive
    decision instead of a branch-specific tangle of return shapes. ``content`` /
    ``reasoning`` are THIS round's increments (already streamed + accumulated by the
    caller); the tool fields are empty on a no-tool round; ``terminal_handoff`` is a
    terminal tool's final text (a tool that already produced the turn's answer);
    ``llm_failed`` marks a round whose LLM call errored on the non-raising path,
    carrying the ``error_code`` / ``error_message`` the loop surfaces as an SSE
    ``error`` ONLY when the loop surfaces it via a terminal ``Return`` directive.
    """

    content: str
    reasoning: str
    usage: TokenUsage | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[LLMMessage] = field(default_factory=list)
    attempts: list[ToolAttempt] = field(default_factory=list)
    terminal_handoff: str | None = None
    llm_failed: bool = False
    error_code: str | None = None
    error_message: str | None = None
    error_context: dict | None = None
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_empty(self) -> bool:
        """No content and no tool call — the empty-response degraded ladder's trigger."""
        return not self.content and not self.tool_calls

    @property
    def all_tools_failed(self) -> bool:
        """Every tool call this round failed (drives the unproductive early-stop)."""
        return bool(self.attempts) and all(not a.success for a in self.attempts)

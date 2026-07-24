"""ReAct engine: turn control, LLM calls, tool execution.

Single-agent ReAct loop for MVP:
  1. Build messages (system + history + user)
  2. Call LLM (streaming)
  3. If tool_calls → execute tools → append results → loop
  4. If text response → done

All intermediate events are emitted to an EventSink for SSE delivery.
"""

from .loop import react_loop
from .segments import deliverable_continuity_instruction, join_segments
from .timeout import resolve_tool_timeout

__all__ = [
    "deliverable_continuity_instruction",
    "join_segments",
    "react_loop",
    "resolve_tool_timeout",
]

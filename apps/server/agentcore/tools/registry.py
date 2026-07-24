"""ToolRegistry: registration and query of available tools.

Manages all registered tools and provides lookup by name or category.
Also converts tool schemas to LLM function calling format.
"""

from __future__ import annotations

import difflib

from agentcore.core.errors import ToolNotFoundError
from agentcore.core.types import ToolCategory
from agentcore.tools.protocol import Tool, ToolSchema, tool_schema_to_openai_format

# Common model hallucinations → canonical tool name. Only surface when the target
# is actually registered (did-you-mean message only — never auto-rewrite / execute).
_KNOWN_TOOL_ALIASES: dict[str, str] = {
    "web_read": "read_url",
    "web_fetch": "read_url",
    "fetch_url": "read_url",
    "fetch": "read_url",
    "browse": "read_url",
    "write": "file_write",
    "read": "file_read",
    "search": "web_search",
    "websearch": "web_search",
    "google": "web_search",
    "content": "file_read",
    "edit": "str_replace",
    "replace": "str_replace",
    "fill_slot": "write_section",
    "fill_section": "write_section",
    "inject_section": "write_section",
    "bash": "terminal",
    "shell": "terminal",
    "ls": "file_list",
    "list_dir": "file_list",
    "delete": "file_delete",
    "rm": "file_delete",
    "mv": "file_move",
    "cp": "file_copy",
}


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ValueError if name already registered."""
        name = tool.schema.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name. No-op when not registered."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        """Get a tool by name. Raises ToolNotFoundError if not found."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"工具 '{name}' 不存在")
        return tool

    def get_optional(self, name: str) -> Tool | None:
        """Get a tool by name, returning None if not found."""
        return self._tools.get(name)

    def suggest_names(self, name: str, *, n: int = 3, cutoff: float = 0.5) -> list[str]:
        """Did-you-mean candidates for a missing tool name (alias map + close matches).

        Returns at most ``n`` registered names. Empty when nothing is close enough.
        Never rewrites or executes — callers only embed these in error feedback.
        """
        if not name or n < 1:
            return []
        key = name.strip().lower().replace("-", "_")
        out: list[str] = []
        alias = _KNOWN_TOOL_ALIASES.get(key)
        if alias and alias in self._tools:
            # Exact known hallucination → surface only the canonical name (avoid
            # noisy near-misses like web_read also matching web_search).
            return [alias]
        for match in difflib.get_close_matches(name, self.names, n=n, cutoff=cutoff):
            if match not in out:
                out.append(match)
            if len(out) >= n:
                break
        return out[:n]

    def list_all(self) -> list[ToolSchema]:
        """Return schemas of all registered tools."""
        return [tool.schema for tool in self._tools.values()]

    def list_by_category(self, category: ToolCategory) -> list[ToolSchema]:
        """Return schemas of tools in a given category."""
        return [tool.schema for tool in self._tools.values() if tool.schema.category == category]

    def get_openai_definitions(self, tool_names: list[str] | None = None) -> list[dict]:
        """Return tool definitions in OpenAI function calling format.

        If tool_names is None, returns all tools.
        If tool_names is provided, returns only those tools.
        """
        if tool_names is None:
            tools = list(self._tools.values())
        else:
            tools = [self._tools[name] for name in tool_names if name in self._tools]

        return [tool_schema_to_openai_format(tool.schema) for tool in tools]

    @property
    def count(self) -> int:
        return len(self._tools)

    @property
    def names(self) -> list[str]:
        """Registered tool names (registration order)."""
        return list(self._tools.keys())

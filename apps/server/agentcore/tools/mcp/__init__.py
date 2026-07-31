"""本机 MCP Client — dynamic worker tools over DesktopClientChannel (stdio on desktop)."""

from agentcore.tools.mcp.wire import (
    McpDiscoverResult,
    McpToolSpec,
    discover_and_register_mcp_tools,
    discover_mcp_tools,
    mcp_capability_label,
    register_mcp_tools,
)

__all__ = [
    "McpDiscoverResult",
    "McpToolSpec",
    "discover_and_register_mcp_tools",
    "discover_mcp_tools",
    "mcp_capability_label",
    "register_mcp_tools",
]

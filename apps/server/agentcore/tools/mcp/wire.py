"""Discover local MCP tools via desktop backfill and register on the worker registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.desktop.channel import DesktopClientChannel, McpOp, McpOpError
from agentcore.tools.mcp.dynamic import McpDynamicTool, sanitize_mcp_tool_name
from agentcore.tools.registry import ToolRegistry

logger = get_logger(__name__)

# Prepare-time list budget — spawn+handshake; failure ⇒ degrade (no MCP tools).
_MCP_LIST_TIMEOUT_SECONDS = 45.0
_TOOL_NAME_MAX = 64


@dataclass(frozen=True)
class McpToolSpec:
    """One MCP tool ready to register on the worker toolset."""

    server_id: str
    server_name: str
    mcp_tool_name: str
    description: str
    input_schema: dict[str, Any] | None


@dataclass(frozen=True)
class McpDiscoverResult:
    """Outcome of one prepare/resume MCP discovery pass."""

    ready_servers: int = 0
    failed_servers: int = 0
    tool_count: int = 0
    server_labels: tuple[str, ...] = field(default_factory=tuple)
    specs: tuple[McpToolSpec, ...] = field(default_factory=tuple)
    degraded: bool = False
    detail: str = ""


def mcp_capability_label(result: McpDiscoverResult | None, *, desktop_online: bool) -> str:
    """Capability-line token for ``mcp=…``."""
    if not desktop_online:
        return "未装配"
    if result is None:
        return "未装配"
    if result.tool_count > 0:
        return "已装配"
    if result.degraded or result.failed_servers > 0:
        return "降级（无可用工具）"
    return "未装配"


async def discover_mcp_tools(
    channel: DesktopClientChannel | None,
) -> McpDiscoverResult:
    """List enabled MCP Servers on the desktop (no registry mutation).

    On channel absence / timeout / error → empty result (turn continues).
    Per-server handshake failures are skipped (degrade that batch only).
    """
    if channel is None:
        return McpDiscoverResult(detail="no_desktop_channel")

    try:
        value = await channel.request_mcp(
            McpOp.LIST_TOOLS,
            {},
            timeout=_MCP_LIST_TIMEOUT_SECONDS,
        )
    except McpOpError as e:
        logger.info("desktop.mcp_list_degraded", detail=str(e))
        return McpDiscoverResult(degraded=True, detail=str(e))
    except Exception as e:  # noqa: BLE001 — never block a chat turn on MCP
        logger.info("desktop.mcp_list_degraded", detail=str(e))
        return McpDiscoverResult(degraded=True, detail=str(e))

    servers = value.get("servers") if isinstance(value, dict) else None
    if not isinstance(servers, list):
        return McpDiscoverResult(degraded=True, detail="invalid_list_payload")

    ready = 0
    failed = 0
    labels: list[str] = []
    specs: list[McpToolSpec] = []

    for entry in servers:
        if not isinstance(entry, dict):
            continue
        server_id = str(entry.get("id") or "").strip()
        server_name = str(entry.get("name") or server_id or "MCP").strip() or "MCP"
        status = str(entry.get("status") or "").strip().lower()
        if status != "ready":
            failed += 1
            err = str(entry.get("error") or "handshake_failed")
            logger.info(
                "desktop.mcp_server_failed",
                server_id=server_id,
                detail=err,
            )
            continue
        ready += 1
        labels.append(server_name)
        tools = entry.get("tools")
        if not isinstance(tools, list):
            continue
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            mcp_name = str(tool.get("name") or "").strip()
            if not mcp_name:
                continue
            input_schema = tool.get("inputSchema") or tool.get("input_schema")
            if not isinstance(input_schema, dict):
                input_schema = None
            specs.append(
                McpToolSpec(
                    server_id=server_id or server_name,
                    server_name=server_name,
                    mcp_tool_name=mcp_name,
                    description=str(tool.get("description") or ""),
                    input_schema=input_schema,
                )
            )

    return McpDiscoverResult(
        ready_servers=ready,
        failed_servers=failed,
        tool_count=len(specs),
        server_labels=tuple(labels),
        specs=tuple(specs),
        degraded=failed > 0 and len(specs) == 0,
        detail="",
    )


def register_mcp_tools(registry: ToolRegistry, result: McpDiscoverResult) -> int:
    """Register discovered MCP tools onto ``registry``. Returns count registered."""
    used_names: set[str] = set(registry.names)
    count = 0
    for spec in result.specs:
        fc_name = sanitize_mcp_tool_name(spec.server_id, spec.mcp_tool_name)
        base = fc_name
        n = 2
        while fc_name in used_names:
            suffix = f"_{n}"
            fc_name = (base[: _TOOL_NAME_MAX - len(suffix)] + suffix)[:_TOOL_NAME_MAX]
            n += 1
        used_names.add(fc_name)
        registry.register(
            McpDynamicTool(
                fc_name=fc_name,
                server_id=spec.server_id,
                server_name=spec.server_name,
                mcp_tool_name=spec.mcp_tool_name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
        )
        count += 1
    return count


async def discover_and_register_mcp_tools(
    registry: ToolRegistry,
    channel: DesktopClientChannel | None,
) -> McpDiscoverResult:
    """Discover then register (convenience for resume / tests)."""
    result = await discover_mcp_tools(channel)
    register_mcp_tools(registry, result)
    return result

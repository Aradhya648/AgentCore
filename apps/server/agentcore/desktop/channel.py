"""DesktopClientChannel — route desktop Client Tools to the bound Electron app.

Counterpart of :class:`agentcore.board.channel.BoardChannel` for OS-level desktop
affordances that only exist in the Electron shell (native notifications + Host ops).

Wired whenever the desktop client is online (local workspace **or** cloud +
``desktop_online``) — never by pinging ``127.0.0.1`` from the cloud API process.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.events import (
    EventSink,
    desktop_notify_required,
    host_op_required,
    mcp_op_required,
)
from agentcore.runtime.events.client_tool_reattach import (
    CHANNEL_HOST,
    CHANNEL_MCP,
    CHANNEL_NOTIFY,
    client_tool_payload,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.interaction import InteractionKind
from agentcore.runtime.ports import ClientRequestBridge

logger = get_logger(__name__)


class DesktopNotifyError(Exception):
    """A desktop notify request failed (desktop error, drop, or timeout)."""


class HostOpError(Exception):
    """A Host op failed (desktop error, drop, timeout, or unsupported op)."""


class McpOpError(Exception):
    """An MCP Client op failed (desktop error, drop, timeout, or server crash)."""


class HostOp(StrEnum):
    """Closed Host op set exchanged over the desktop backfill channel (P0–P3)."""

    PING = "host_ping"
    INFO = "host_info"
    AUDIO_DEVICES = "host_audio_devices"
    STORAGE = "host_storage"
    POWER = "host_power"
    NETWORK_SUMMARY = "host_network_summary"
    APPS = "host_apps"
    # P3 general host shell (CEO+worker · GRANTABLE · host_class · 禁 kickoff)
    SHELL = "host_shell"
    OPEN_SETTINGS = "host_open_settings"
    # L3 controlled whitelist (worker · GRANTABLE · host_class only)
    AUDIO_SET_DEFAULT = "host_audio_set_default"
    SERVICE_RESTART = "host_service_restart"


class McpOp(StrEnum):
    """Closed MCP Client op set over the desktop backfill channel (stdio only)."""

    LIST_TOOLS = "list_tools"
    CALL_TOOL = "call_tool"


@dataclass
class DesktopClientChannel:
    """Suspends until the bound desktop fulfils a Client Tool request."""

    sink: EventSink
    conversation_id: str
    registry: ClientRequestBridge
    timeout_seconds: float

    async def notify(
        self,
        *,
        title: str,
        body: str = "",
    ) -> dict[str, Any]:
        """Emit a notify request, await the desktop, return its ``value`` envelope."""
        request_id = new_id()
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_NOTIFY,
                    EventType.DESKTOP_NOTIFY_REQUIRED.value,
                    params={"title": title, "body": body},
                ),
                timeout=self.timeout_seconds,
                on_suspended=lambda: self.sink.emit(
                    desktop_notify_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        title=title,
                        body=body,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info(
                "desktop.notify_timeout",
                conversation_id=self.conversation_id,
                request_id=request_id,
            )
            raise DesktopNotifyError("桌面通知超时（客户端未响应）") from e

        if not isinstance(result, dict) or not result.get("ok"):
            detail = ""
            if isinstance(result, dict):
                err = result.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("detail", "") or "")
                elif err:
                    detail = str(err)
            raise DesktopNotifyError(detail or "桌面通知失败")
        value = result.get("value")
        return value if isinstance(value, dict) else {"shown": True}

    async def request_host(
        self,
        op: HostOp | str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Emit a Host op, await the desktop, return its ``value`` dict."""
        op_name = str(op)
        request_id = new_id()
        payload_args = dict(args or {})
        deadline = self.timeout_seconds if timeout is None else timeout
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_HOST,
                    EventType.HOST_OP_REQUIRED.value,
                    params={"op": op_name, "args": payload_args},
                ),
                timeout=deadline,
                on_suspended=lambda: self.sink.emit(
                    host_op_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        op=op_name,
                        args=payload_args,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info(
                "desktop.host_op_timeout",
                conversation_id=self.conversation_id,
                request_id=request_id,
                op=op_name,
            )
            raise HostOpError(f"本机 Host 操作超时（{op_name}：客户端未响应）") from e

        if not isinstance(result, dict) or not result.get("ok"):
            detail = ""
            if isinstance(result, dict):
                err = result.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("detail", "") or "")
                elif err:
                    detail = str(err)
            raise HostOpError(detail or f"本机 Host 操作失败（{op_name}）")
        value = result.get("value")
        return value if isinstance(value, dict) else {}

    async def request_mcp(
        self,
        op: McpOp | str,
        args: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Emit an MCP Client op, await the desktop, return its ``value`` dict."""
        op_name = str(op)
        request_id = new_id()
        payload_args = dict(args or {})
        deadline = self.timeout_seconds if timeout is None else timeout
        try:
            result = await self.registry.suspend(
                request_id,
                self.conversation_id,
                kind=InteractionKind.CLIENT_TOOL,
                payload=client_tool_payload(
                    CHANNEL_MCP,
                    EventType.MCP_OP_REQUIRED.value,
                    params={"op": op_name, "args": payload_args},
                ),
                timeout=deadline,
                on_suspended=lambda: self.sink.emit(
                    mcp_op_required(
                        request_id=request_id,
                        conversation_id=self.conversation_id,
                        op=op_name,
                        args=payload_args,
                    )
                ),
            )
        except TimeoutError as e:
            logger.info(
                "desktop.mcp_op_timeout",
                conversation_id=self.conversation_id,
                request_id=request_id,
                op=op_name,
            )
            raise McpOpError(f"本机 MCP 操作超时（{op_name}：客户端未响应）") from e

        if not isinstance(result, dict) or not result.get("ok"):
            detail = ""
            if isinstance(result, dict):
                err = result.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("detail", "") or "")
                elif err:
                    detail = str(err)
            raise McpOpError(detail or f"本机 MCP 操作失败（{op_name}）")
        value = result.get("value")
        return value if isinstance(value, dict) else {}

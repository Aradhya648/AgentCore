"""DesktopClientChannel — route desktop Client Tools to the bound Electron app.

Counterpart of :class:`agentcore.board.channel.BoardChannel` for OS-level desktop
affordances that only exist in the Electron shell (native notifications today).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.events import EventSink, desktop_notify_required
from agentcore.runtime.interaction import InteractionKind
from agentcore.runtime.ports import ClientRequestBridge

logger = get_logger(__name__)


class DesktopNotifyError(Exception):
    """A desktop notify request failed (desktop error, drop, or timeout)."""


@dataclass
class DesktopClientChannel:
    """Suspends until the bound desktop shows an OS notification."""

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
                payload={
                    "title": title,
                    "body": body,
                },
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

"""Desktop client channel — route desktop-only ops to the bound Electron app."""

from agentcore.desktop.channel import (
    DesktopClientChannel,
    DesktopNotifyError,
    HostOp,
    HostOpError,
)

__all__ = [
    "DesktopClientChannel",
    "DesktopNotifyError",
    "HostOp",
    "HostOpError",
]

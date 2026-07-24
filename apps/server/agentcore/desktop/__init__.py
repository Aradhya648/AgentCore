"""Desktop client channel — route desktop-only ops to the bound Electron app."""

from agentcore.desktop.channel import DesktopClientChannel, DesktopNotifyError

__all__ = ["DesktopClientChannel", "DesktopNotifyError"]

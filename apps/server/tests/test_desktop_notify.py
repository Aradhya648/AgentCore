"""Unit tests for desktop_notify tool and channel."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.desktop.channel import DesktopClientChannel, DesktopNotifyError
from agentcore.tools.builtin.desktop_notify import DesktopNotifyTool
from agentcore.tools.protocol import ToolContext


@pytest.mark.asyncio
async def test_desktop_notify_requires_local_channel():
    tool = DesktopNotifyTool()
    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=MagicMock(location="server"),
        user_id="u1",
        desktop_channel=None,
    )
    result = await tool.execute({"title": "完成"}, ctx)
    assert not result.success
    assert "桌面" in (result.error or "")


@pytest.mark.asyncio
async def test_desktop_notify_shows_via_channel():
    channel = MagicMock()
    channel.notify = AsyncMock(return_value={"shown": True})
    tool = DesktopNotifyTool()
    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=MagicMock(location="local"),
        user_id="u1",
        desktop_channel=channel,
    )
    result = await tool.execute(
        {"title": "MiniClaw 已启动", "body": "请回到电脑查看"},
        ctx,
    )
    assert result.success
    channel.notify.assert_awaited_once_with(
        title="MiniClaw 已启动",
        body="请回到电脑查看",
    )
    assert "系统通知" in result.output


@pytest.mark.asyncio
async def test_channel_maps_desktop_failure():
    registry = MagicMock()
    registry.suspend = AsyncMock(return_value={"ok": False, "error": {"detail": "nope"}})
    sink = MagicMock()
    channel = DesktopClientChannel(
        sink=sink,
        conversation_id="c1",
        registry=registry,
        timeout_seconds=1.0,
    )
    with pytest.raises(DesktopNotifyError, match="nope"):
        await channel.notify(title="t", body="b")

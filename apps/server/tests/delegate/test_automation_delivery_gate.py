"""Delegate Agent/自动化：ledger 后果闸（可运行禁 toolshed、仅方案禁硬锁）；无文案意图拒整批。"""

from __future__ import annotations

import pytest

from agentcore.core.types import (
    AutonomyPolicy,
    CommandAxis,
    FileWriteAxis,
    HostAxis,
    PermissionAxes,
    TeamKickoffAxis,
    recipe_to_axes,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.automation_delivery import (
    automation_toolshed_rejected_message,
    automation_website_rejected_message,
    clear_delivery_confirmation,
    record_delivery_confirmation,
)
from agentcore.runtime.runs.website_style import (
    build_website_missing_style_error,
    clear_style_confirmation,
)
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import Provider, local_ctx

# Explicit kickoff axes: style/delivery gates must still hang (not full_auto default).
_KICKOFF_RULES = PermissionAxes(
    FileWriteAxis.SESSION,
    CommandAxis.KICKOFF,
    TeamKickoffAxis.RULES,
    HostAxis.ASK,
)


def _delegate(
    *,
    user_message: str,
    conversation_id: str,
    base_ctx,
    autonomy: AutonomyPolicy | None = None,
    permission_axes: PermissionAxes | None = None,
) -> DelegateTool:
    axes = permission_axes or (
        recipe_to_axes(autonomy) if autonomy is not None else _KICKOFF_RULES
    )
    return DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message=user_message,
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base_ctx,
        permission_axes=axes,
        conversation_id=conversation_id,
    )


@pytest.mark.asyncio
async def test_execute_allows_automation_text_without_delivery_ledger():
    """无自动化账时不因用户原文像自动化而拒整个 delegate（自由组队放行）。"""
    cid = "auto-gate-missing"
    clear_delivery_confirmation(cid)
    t = _delegate(
        user_message="做短视频自动化 Agent",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "搭自动发帖流水线"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_rejects_build_toolshed_without_style_ledger():
    """无风格账 + build_toolshed 仍拒（结构化 playbook 闸，非文案意图）。"""
    cid = "auto-gate-toolshed-no-style"
    clear_delivery_confirmation(cid)
    clear_style_confirmation(cid)
    t = _delegate(
        user_message="随便聊聊",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "playbook": "build_toolshed",
            "playbook_args": {"site": "Ops", "sections": ["应用外壳", "数据表格"]},
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is False
    assert build_website_missing_style_error() in (result.error or "")
    clear_delivery_confirmation(cid)
    clear_style_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_runnable_rejects_build_toolshed():
    cid = "auto-gate-runnable-toolshed"
    clear_delivery_confirmation(cid)
    record_delivery_confirmation(
        cid, format_id="f0", label="可运行自动化", source="ask_user"
    )
    t = _delegate(
        user_message="做短视频自动化 Agent",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "playbook": "build_toolshed",
            "playbook_args": {"site": "Ops", "sections": ["应用外壳", "数据表格"]},
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is False
    assert automation_toolshed_rejected_message() in (result.error or "")
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_runnable_allows_free_teaming():
    cid = "auto-gate-runnable-free"
    clear_delivery_confirmation(cid)
    record_delivery_confirmation(
        cid, format_id="f0", label="可运行自动化", source="ask_user"
    )
    t = _delegate(
        user_message="做短视频自动化 Agent",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "实现可调度发帖 Agent"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_console_allows_build_toolshed():
    cid = "auto-gate-console-toolshed"
    clear_delivery_confirmation(cid)
    record_delivery_confirmation(
        cid, format_id="f1", label="控制台原型", source="ask_user"
    )
    t = _delegate(
        user_message="做短视频自动化 Agent",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    from agentcore.runtime.runs.website_style import (
        clear_style_confirmation,
        record_style_confirmation,
    )

    clear_style_confirmation(cid)
    record_style_confirmation(
        cid, style_id="s0", label="深色科技", source="ask_user"
    )
    try:
        result = await t.execute(
            {
                "playbook": "build_toolshed",
                "playbook_args": {"site": "短视频运营台", "sections": ["应用外壳", "数据表格"]},
                "coordinate": False,
            },
            local_ctx(),
        )
        assert result.success is True
    finally:
        clear_style_confirmation(cid)
        clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_plan_rejects_toolshed_and_website():
    cid = "auto-gate-plan-only"
    clear_delivery_confirmation(cid)
    record_delivery_confirmation(
        cid, format_id="f2", label="仅方案", source="ask_user"
    )
    t = _delegate(
        user_message="打造内容分发工作流",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    r1 = await t.execute(
        {
            "playbook": "build_toolshed",
            "playbook_args": {"site": "X", "sections": ["应用外壳"]},
            "coordinate": False,
        },
        local_ctx(),
    )
    assert r1.success is False
    assert automation_toolshed_rejected_message() in (r1.error or "")

    r2 = await t.execute(
        {
            "playbook": "build_website",
            "playbook_args": {"site": "X", "sections": ["首页"]},
            "coordinate": False,
        },
        local_ctx(),
    )
    assert r2.success is False
    assert automation_website_rejected_message() in (r2.error or "")
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_plan_allows_free_teaming():
    cid = "auto-gate-plan-free"
    clear_delivery_confirmation(cid)
    record_delivery_confirmation(
        cid, format_id="f2", label="仅方案", source="ask_user"
    )
    t = _delegate(
        user_message="打造内容分发工作流",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "架构师", "task": "写自动化方案文档"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_non_automation_delegate_unaffected():
    t = _delegate(
        user_message="写一份调研报告",
        conversation_id="auto-gate-non-auto",
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "研究员", "task": "整理竞品对比"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True

"""Delegate Agent/自动化开工形态硬闸：无记账拒、可运行禁 toolshed、控制台可过、仅方案禁硬锁。"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy, recipe_to_axes
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.automation_delivery import (
    automation_missing_delivery_error,
    automation_toolshed_rejected_message,
    automation_website_rejected_message,
    clear_delivery_confirmation,
    record_delivery_confirmation,
)
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import Provider, local_ctx


def _delegate(
    *,
    user_message: str,
    conversation_id: str,
    base_ctx,
    autonomy: AutonomyPolicy = AutonomyPolicy.WRITE_CODE,
) -> DelegateTool:
    return DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message=user_message,
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base_ctx,
        permission_axes=recipe_to_axes(autonomy),
        conversation_id=conversation_id,
    )


@pytest.mark.asyncio
async def test_execute_rejects_automation_without_delivery_ledger():
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
    assert result.success is False
    assert automation_missing_delivery_error() in (result.error or "")
    clear_delivery_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_full_auto_defaults_delivery_then_accepts_free_teaming():
    cid = "auto-gate-full-auto"
    clear_delivery_confirmation(cid)
    t = _delegate(
        user_message="帮我做内容分发自动化工作流",
        conversation_id=cid,
        base_ctx=local_ctx(),
        autonomy=AutonomyPolicy.MANAGED,
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "设计并可运行的分发流水线"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_delivery_confirmation(cid)


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
        # Style gate will still reject without style ledger — use free args path that
        # expands playbook only after style check. Record a style so toolshed can pass.
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


@pytest.mark.asyncio
async def test_research_false_positive_unaffected():
    t = _delegate(
        user_message="用团队做竞品调研",
        conversation_id="auto-gate-research-fp",
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "研究员", "task": "摸底三家竞品"}],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True

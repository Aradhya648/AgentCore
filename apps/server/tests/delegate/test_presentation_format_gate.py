"""Delegate 演讲/PPT 交付形态硬闸：无记账拒、pptx+执行+仅 md 拒、无执行+marp 放行。"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.presentation_format import (
    clear_format_confirmation,
    is_pptx_format_confirmation,
    presentation_missing_format_error,
    presentation_pptx_silent_md_error,
    record_format_confirmation,
    tasks_silently_downgrade_pptx_to_md,
)
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import Provider, ctx, local_ctx


def _delegate(
    *,
    user_message: str,
    conversation_id: str,
    base_ctx,
    autonomy: AutonomyPolicy = AutonomyPolicy.FIRST_GRANT,
) -> DelegateTool:
    return DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message=user_message,
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base_ctx,
        autonomy_policy=autonomy,
        conversation_id=conversation_id,
    )


# ── helpers ──────────────────────────────────────────────────────────────────


def test_is_pptx_format_confirmation_by_label():
    from agentcore.runtime.runs.presentation_format import FormatConfirmation

    assert is_pptx_format_confirmation(
        FormatConfirmation(format_id="f0", label="PowerPoint（.pptx）", source="ask_user")
    )
    assert not is_pptx_format_confirmation(
        FormatConfirmation(format_id="f1", label="Marp Markdown 幻灯片", source="ask_user")
    )
    assert not is_pptx_format_confirmation(
        FormatConfirmation(format_id="f2", label="仅讲稿大纲", source="ask_user")
    )


def test_tasks_silently_downgrade_pptx_to_md():
    assert tasks_silently_downgrade_pptx_to_md(
        [
            {
                "role": "课件工程师",
                "task": "写 Markdown（Slidev/Marp）幻灯片",
                "deliverable": {"form": "files", "artifacts": ["deck/multi-agent-ppt.md"]},
            }
        ]
    )
    assert not tasks_silently_downgrade_pptx_to_md(
        [
            {
                "role": "课件工程师",
                "task": "用 python-pptx 生成 course.pptx",
                "deliverable": {"form": "files", "artifacts": ["course.pptx"]},
            }
        ]
    )
    assert not tasks_silently_downgrade_pptx_to_md(
        [{"role": "写手", "task": "整理讲稿要点"}]
    )


# ── execute 级：无记账拒 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_rejects_presentation_without_format_ledger():
    cid = "pres-gate-missing-format"
    clear_format_confirmation(cid)
    t = _delegate(
        user_message="写一个多Agent的演讲PPT文件",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "用 python-pptx 生成 course.pptx",
                    "deliverable": {"form": "files", "artifacts": ["course.pptx"]},
                }
            ],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is False
    assert presentation_missing_format_error() in (result.error or "")
    clear_format_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_full_auto_defaults_format_then_accepts_pptx():
    cid = "pres-gate-full-auto-default"
    clear_format_confirmation(cid)
    t = _delegate(
        user_message="帮我做一份产品发布 PPT",
        conversation_id=cid,
        base_ctx=local_ctx(),
        autonomy=AutonomyPolicy.FULL_AUTO,
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "用 python-pptx 生成 launch.pptx",
                    "deliverable": {"form": "files", "artifacts": ["launch.pptx"]},
                }
            ],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_format_confirmation(cid)


# ── execute 级：pptx + 有执行 + 仅 md → 硬拒 ──────────────────────────────────


@pytest.mark.asyncio
async def test_execute_rejects_pptx_confirmed_silent_md_when_exec_on():
    cid = "pres-gate-pptx-md-local"
    clear_format_confirmation(cid)
    record_format_confirmation(
        cid,
        format_id="f0",
        label="PowerPoint（.pptx）",
        source="ask_user",
    )
    t = _delegate(
        user_message="写一个多Agent的演讲PPT文件",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "输出可导入 Slidev/Marp 的 Markdown 幻灯片",
                    "deliverable": {
                        "form": "files",
                        "artifacts": ["docs/multi-agent-ppt.md"],
                    },
                }
            ],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is False
    assert presentation_pptx_silent_md_error() in (result.error or "")
    clear_format_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_accepts_pptx_confirmed_with_pptx_artifact():
    cid = "pres-gate-pptx-ok"
    clear_format_confirmation(cid)
    record_format_confirmation(
        cid,
        format_id="f0",
        label="PowerPoint（.pptx）",
        source="ask_user",
    )
    t = _delegate(
        user_message="做一份课件幻灯片",
        conversation_id=cid,
        base_ctx=local_ctx(),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "用 python-pptx 生成 course.pptx",
                    "deliverable": {"form": "files", "artifacts": ["course.pptx"]},
                }
            ],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    clear_format_confirmation(cid)


# ── execute 级：无执行 + marp 放行 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_allows_marp_when_no_exec_and_marp_confirmed():
    cid = "pres-gate-marp-cloud"
    clear_format_confirmation(cid)
    record_format_confirmation(
        cid,
        format_id="f1",
        label="Marp Markdown 幻灯片",
        source="ask_user",
    )
    cloud = ctx()
    t = _delegate(
        user_message="写一份演示文稿课件",
        conversation_id=cid,
        base_ctx=cloud,
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "写 Marp Markdown 幻灯片",
                    "deliverable": {"form": "files", "artifacts": ["deck/slides.md"]},
                }
            ],
            "coordinate": False,
        },
        cloud,
    )
    assert result.success is True
    clear_format_confirmation(cid)


@pytest.mark.asyncio
async def test_execute_pptx_confirmed_no_exec_allows_marp_with_soft_tip():
    """已选 pptx 但无执行：不拦 Marp.md，注入软提示。"""
    cid = "pres-gate-pptx-no-exec-marp"
    clear_format_confirmation(cid)
    record_format_confirmation(
        cid,
        format_id="f0",
        label="PowerPoint（.pptx）",
        source="ask_user",
    )
    cloud = ctx()
    t = _delegate(
        user_message="做一份产品发布 PPT",
        conversation_id=cid,
        base_ctx=cloud,
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "课件工程师",
                    "task": "用 Marp 写 slides.md 并注明非真 pptx",
                    "deliverable": {"form": "files", "artifacts": ["slides.md"]},
                }
            ],
            "coordinate": False,
        },
        cloud,
    )
    assert result.success is True
    assert "[能力提示]" in result.output
    assert "pptx" in result.output.lower() or "PowerPoint" in result.output
    clear_format_confirmation(cid)


@pytest.mark.asyncio
async def test_non_presentation_delegate_unaffected():
    """非演讲意图不读 format 闸（能力闸既有测不回归的旁证）。"""
    t = _delegate(
        user_message="写一份调研报告",
        conversation_id="pres-gate-non-pres",
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

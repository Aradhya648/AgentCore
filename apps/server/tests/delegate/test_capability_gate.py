"""委派前能力闸（能力闸门与交付诚实性）：resolved code_verified × 无执行环境 硬拒——
显式声明与结构化 form/artifacts 共用 ``resolve_completion_criteria`` 同一谓词（闸门与收尾
验收对齐；B1 后文案不再绑定 code_verified）。运行 / 二进制文案启发只软警告不拦截。

能力判定复用 ``code_execution_enabled_for`` 单一真相源（与 worker registry 同一谓词）：
云端 location=server 且未开 gVisor / 云执行逃生口 ⇒ 执行类不可用；local ⇒ 可用。
"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.runtime.delegate.completion import (
    execution_capability_warning,
    plan_mentions_binary_artifact,
    validate_execution_capability,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs import build_run_plan
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import LocalBackend, Provider, ctx, local_ctx, tool


def _plan(task: str = "写一份分析"):
    plan, errors = build_run_plan(
        [{"role": "专家", "task": task}],
        valid_tools=set(),
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    return plan


# ── 函数级：硬闸 ─────────────────────────────────────────────────────────────


def test_hard_gate_rejects_explicit_code_verified_on_cloud():
    # 云端（ServerWorkspace location=server，默认无 gVisor）+ 显式 code_verified → 硬拒。
    backend = ctx().backend
    msg = validate_execution_capability("code_verified", _plan(), backend)
    assert msg is not None
    assert "code_execute" in msg
    assert "bind_local_folder" in msg  # 出路①：先绑定本地文件夹
    assert "立即发 ask_user" in msg
    assert "勿用纯文本" in msg
    assert "files_written" in msg  # 出路②：改交付形态
    assert "ask_user" in msg  # 出路③：先对齐


def test_hard_gate_accepts_dict_form_code_verified():
    backend = ctx().backend
    msg = validate_execution_capability({"type": "code_verified"}, _plan(), backend)
    assert msg is not None


def test_hard_gate_passes_on_local():
    # 本机 location=local → 执行类可用，code_verified 放行。
    msg = validate_execution_capability("code_verified", _plan(), LocalBackend())
    assert msg is None


def test_hard_gate_no_longer_binds_run_text_without_explicit_criteria():
    # B1：任务文案像「要运行」但未显式声明 → resolve 不绑定 code_verified，硬闸静默。
    backend = ctx().backend
    plan = _plan("运行 python 脚本生成 course.pptx 并跑通")
    assert validate_execution_capability(None, plan, backend) is None


def test_hard_gate_run_text_passes_on_local():
    plan = _plan("运行 python 脚本生成 course.pptx 并跑通")
    assert validate_execution_capability(None, plan, LocalBackend()) is None


def test_hard_gate_explicit_other_criteria_beats_inference():
    # 显式 files_written → 硬闸不触发，走软警告。
    backend = ctx().backend
    plan = _plan("运行 python 脚本生成 course.pptx 并跑通")
    assert validate_execution_capability("files_written", plan, backend) is None


def test_hard_gate_form_files_beats_run_open_text_on_cloud():
    # form=files 结构化信号 → resolve=files_written，硬闸不触发。
    from agentcore.runtime.runs import build_run_plan

    backend = ctx().backend
    plan, errors = build_run_plan(
        [
            {
                "role": "前端",
                "task": "写静态宣传官网，完成后打开页面看效果",
                "deliverable": {"form": "files"},
            }
        ],
        valid_tools=set(),
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    assert validate_execution_capability(None, plan, backend) is None


def test_hard_gate_passes_other_criteria_on_cloud():
    backend = ctx().backend
    assert validate_execution_capability("files_written", _plan(), backend) is None
    assert validate_execution_capability("custom", _plan(), backend) is None
    # 无显式契约 → resolve 不出 code_verified，闸门静默。
    assert validate_execution_capability(None, _plan(), backend) is None


# ── 函数级：软警告 ───────────────────────────────────────────────────────────


def test_soft_warning_on_cloud_binary_artifact_task():
    backend = ctx().backend
    plan = _plan("用 python-pptx 生成一份可直接播放的 course.pptx 课件")
    assert plan_mentions_binary_artifact(plan)
    warn = execution_capability_warning(None, plan, backend)
    assert warn is not None
    assert warn.startswith("[能力提示]")
    assert "bind_local_folder" in warn
    assert "立即发 ask_user" in warn
    assert "勿用纯文本" in warn


def test_soft_warning_on_run_text_without_explicit_criteria():
    # B1：运行类文案 + 无显式契约 → 不再硬闸，改走软警告。
    backend = ctx().backend
    plan = _plan("启动开发服务器并跑通冒烟测试")
    warn = execution_capability_warning(None, plan, backend)
    assert warn is not None
    assert warn.startswith("[能力提示]")


def test_soft_warning_on_explicit_files_written_with_run_text():
    # 显式 files_written（硬闸不触发），运行文案仍值得提醒交付诚实 → 软警告。
    backend = ctx().backend
    plan = _plan("启动开发服务器并跑通冒烟测试")
    warn = execution_capability_warning("files_written", plan, backend)
    assert warn is not None
    assert warn.startswith("[能力提示]")


def test_soft_warning_silent_on_local():
    plan = _plan("用 python-pptx 生成 course.pptx")
    assert execution_capability_warning(None, plan, LocalBackend()) is None


def test_soft_warning_silent_without_hints():
    backend = ctx().backend
    assert execution_capability_warning(None, _plan("写一份市场分析报告"), backend) is None


def test_soft_warning_defers_to_hard_gate_on_explicit_criteria():
    # 显式 code_verified 归硬闸管，软警告不重复发。
    backend = ctx().backend
    plan = _plan("运行脚本生成 course.pptx")
    assert execution_capability_warning("code_verified", plan, backend) is None


# ── execute 级接线：三类验收用例 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_rejects_code_verified_on_cloud():
    # 「云端 + code_verified」→ delegate 校验硬拒绝，错误信息给出明确出路。
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "生成 pptx 课件"}],
            "completion_criteria": "code_verified",
        },
        ctx(),
    )
    assert result.success is False
    assert "bind_local_folder" in (result.error or "")
    assert "files_written" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_soft_warns_inferred_run_text_on_cloud():
    # B1：云端派「运行 demo.py」且未显式声明 → 放行 + 软警告 + 验收回显「未启用」。
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [{"role": "Python 运行员", "task": "运行工作区的 demo.py 并贴出输出"}],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert "[能力提示]" in result.output
    assert "本批验收：未启用" in result.output


@pytest.mark.asyncio
async def test_execute_echoes_explicit_acceptance():
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=local_ctx(),
        autonomy_policy=AutonomyPolicy.FULL_AUTO,
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建脚本"}],
            "completion_criteria": "code_verified",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert "本批验收：code_verified（显式声明）" in result.output


@pytest.mark.asyncio
async def test_execute_passes_code_verified_on_local():
    # 「本地 + code_verified」→ 闸门放行，委派照常运行（验收缺口走既有软路径，不在闸门拦）。
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=local_ctx(),
        autonomy_policy=AutonomyPolicy.FULL_AUTO,
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建脚本"}],
            "completion_criteria": "code_verified",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert "无法按 code_verified 验收" not in (result.error or "")


@pytest.mark.asyncio
async def test_execute_soft_warns_on_cloud_binary_artifact_task():
    # 启发命中（生成可播放 pptx）而非显式 code_verified → 工具结果注入软警告、不拦截。
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [
                {"role": "课件工程师", "task": "用 python-pptx 生成可直接播放的 course.pptx"}
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert "[能力提示]" in result.output
    assert "本批验收：" in result.output


@pytest.mark.asyncio
async def test_execute_hoists_task_nested_completion_criteria():
    # task 内层 files_written 提升后按显式 files_written 放行（软警告可有）。
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写 index.html，打开浏览器验收",
                    "completion_criteria": "files_written",
                }
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert "无法按 code_verified 验收" not in (result.error or "")
    assert "本批验收：files_written（显式声明）" in result.output


@pytest.mark.asyncio
async def test_execute_rejects_conflicting_task_completion_criteria():
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [
                {"role": "A", "task": "写文件", "completion_criteria": "files_written"},
                {"role": "B", "task": "跑测试", "completion_criteria": "code_verified"},
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is False
    assert "冲突" in (result.error or "")

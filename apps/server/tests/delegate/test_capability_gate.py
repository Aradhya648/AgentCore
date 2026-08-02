"""委派前能力闸（能力闸门与交付诚实性）：resolved code_verified × 无执行环境 硬拒——
显式声明与结构化 form/artifacts 共用 ``resolve_completion_criteria`` 同一谓词（闸门与收尾
验收对齐；B1 后文案不再绑定 code_verified）。运行 / 二进制文案启发只软警告不拦截。

能力判定复用 ``code_execution_enabled_for`` 单一真相源（与 worker registry 同一谓词）：
云端 location=server 且未开 gVisor / 云执行逃生口 ⇒ 执行类不可用；local ⇒ 可用。
"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy, recipe_to_axes
from agentcore.runtime.delegate.completion import (
    execution_capability_warning,
    node_holds_write_tools,
    plan_mentions_binary_artifact,
    validate_code_verified_worker_tools,
    validate_execution_capability,
    validate_files_worker_tools,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs import build_run_plan
from agentcore.runtime.runs.types import RunSpec
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.protocol import ToolCategory, ToolResult, ToolSchema
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


def _plan_with_tools(tools: list[str] | None, *, task: str = "写一份分析"):
    plan, errors = build_run_plan(
        [{"role": "专家", "task": task, **({"tools": tools} if tools is not None else {})}],
        valid_tools=set(tools or []) | {"file_read", "grep", "test_run", "code_execute", "terminal"},
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    return plan


class _NamedStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.schema = ToolSchema(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments, context):  # noqa: ARG002
        return ToolResult(tool_call_id="", success=True, output="ok")


def _registry(*names: str) -> ToolRegistry:
    reg = ToolRegistry()
    for n in names:
        reg.register(_NamedStub(n))
    return reg


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
    # E1：须带「怎么算修好」，否则先被修码收口契约拒（本测覆盖能力闸，故带 verify_command）。
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "生成 pptx 课件"}],
            "completion_criteria": {
                "type": "code_verified",
                "verify_command": "python -c 'assert True'",
            },
            "complexity_hint": "standard",
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
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建脚本"}],
            "completion_criteria": {
                "type": "code_verified",
                "verify_command": "pnpm test",
            },
            "complexity_hint": "standard",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert "本批验收：code_verified（显式声明）" in result.output
    assert "怎么算修好：pnpm test" in result.output


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
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建脚本"}],
            "completion_criteria": {
                "type": "code_verified",
                "verify_command": "pytest -q",
            },
            "complexity_hint": "standard",
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


# ── 冷启动探索：验收绑定按意图 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_allows_form_files_while_explore_pending():
    """form=files 在 explore-pending 下可过校验；仍抑制 files_written 推断。"""
    base = local_ctx()
    base.cold_start_explore_pending = True
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "调研A",
                    "task": "摸清项目目录与入口",
                    "deliverable": {"form": "files"},
                },
                {
                    "role": "调研B",
                    "task": "读设计与约定文档",
                    "deliverable": {"form": "prose"},
                },
            ],
            "coordinate": False,
        },
        base,
    )
    assert result.success is True
    assert "本批验收：未启用" in result.output


@pytest.mark.asyncio
async def test_execute_rejects_single_worker_while_explore_pending():
    base = local_ctx()
    base.cold_start_explore_pending = True
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "调研",
                    "task": "摸清项目结构",
                    "deliverable": {"form": "prose"},
                }
            ],
            "coordinate": False,
        },
        base,
    )
    assert result.success is False
    assert "≥2" in (result.error or "") or "至少两" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_prose_explore_batch_does_not_auto_files_written():
    base = local_ctx()
    base.cold_start_explore_pending = True
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "调研A",
                    "task": "摸清项目目录与入口",
                    "deliverable": {"form": "prose"},
                },
                {
                    "role": "调研B",
                    "task": "读设计与约定文档",
                    "deliverable": {"form": "prose"},
                },
            ],
            "coordinate": False,
        },
        base,
    )
    assert result.success is True
    assert "本批验收：未启用" in result.output


@pytest.mark.asyncio
async def test_execute_form_files_infers_after_explore_cleared():
    """画像写入后同回合交付批恢复结构化推断（建站回归）。"""
    base = local_ctx()
    base.cold_start_explore_pending = False
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写静态宣传站",
                    "deliverable": {"form": "files"},
                }
            ],
            "coordinate": False,
        },
        base,
    )
    assert result.success is True
    assert "本批验收：files_written（结构化交付声明）" in result.output


@pytest.mark.asyncio
async def test_execute_explicit_criteria_still_binds_during_explore():
    """显式 files_written 在探索未完成时仍可强制，并放行配套 form=files。"""
    base = local_ctx()
    base.cold_start_explore_pending = True
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=base,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "调研A",
                    "task": "摸清项目目录并落盘 brief",
                    "deliverable": {"form": "files"},
                },
                {
                    "role": "调研B",
                    "task": "读设计文档回报",
                    "deliverable": {"form": "prose"},
                },
            ],
            "completion_criteria": "files_written",
            "coordinate": False,
        },
        base,
    )
    assert result.success is True
    assert "本批验收：files_written（显式声明）" in result.output


def test_hard_gate_rejects_runtime_ready_on_cloud():
    backend = ctx().backend
    msg = validate_execution_capability("runtime_ready", _plan("启动开发服务器"), backend)
    assert msg is not None
    assert "runtime_ready" in msg
    assert "terminal" in msg
    assert "bind_local_folder" in msg


def test_hard_gate_passes_runtime_ready_on_local():
    msg = validate_execution_capability(
        "runtime_ready", _plan("启动开发服务器"), LocalBackend()
    )
    assert msg is None


# ── E1 修码收口：怎么算修好契约（execute 级）────────────────────────────────


@pytest.mark.asyncio
async def test_execute_rejects_bare_code_verified_without_how_fixed():
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建"}],
            "completion_criteria": "code_verified",
            "complexity_hint": "standard",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "怎么算修好" in (result.error or "")
    assert "verify_command" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_rejects_repair_code_without_verify_slot():
    t = tool(Provider(["X"]))
    result = await t.execute(
        {
            "playbook": "repair_code",
            "playbook_args": {"problem": "missing export foo"},
        },
        local_ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "verify" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_repair_code_forces_code_verified_acceptance():
    """E1/E2：repair_code 带 verify → 强制 code_verified，不可降到 files_written。"""
    t = DelegateTool(
        llm=Provider(["诊断完成。", "已修补。", "验证通过。"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="修这个 bug",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=local_ctx(),
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "playbook": "repair_code",
            "playbook_args": {
                "problem": "missing export foo",
                "verify": "pytest tests/test_app.py -q",
                "target": "app.py",
            },
            # 试图降级：应被强制覆盖为 code_verified
            "completion_criteria": "files_written",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert "本批验收：code_verified" in result.output
    assert "怎么算修好：pytest tests/test_app.py -q" in result.output
    # 无真实 verify 工具成功 → 验收缺口（不能靠 prose 过门）
    assert "完成条件未满足" in result.output or "验证" in result.output


# ── D1：code_verified × 无执行类 tools 硬拒 ───────────────────────────────────


def test_worker_tools_gate_retired_for_code_verified_without_execution_tools():
    plan = _plan_with_tools(["file_read", "grep", "web_search"])
    assert (
        validate_code_verified_worker_tools(
            {"type": "code_verified", "verify_command": "pytest -q"},
            plan,
        )
        is None
    )


def test_worker_tools_gate_passes_when_one_holds_test_run():
    plan = _plan_with_tools(["file_read", "test_run"])
    assert (
        validate_code_verified_worker_tools(
            {"type": "code_verified", "verify_command": "pytest -q"},
            plan,
        )
        is None
    )


def test_worker_tools_gate_passes_unrestricted_tools():
    # tools=None → 无限制，视为持有执行类
    plan = _plan()
    assert validate_code_verified_worker_tools("code_verified", plan) is None


def test_worker_tools_gate_silent_when_not_code_verified():
    plan = _plan_with_tools(["file_read"])
    assert validate_code_verified_worker_tools("files_written", plan) is None
    assert validate_code_verified_worker_tools(None, plan) is None


@pytest.mark.asyncio
async def test_execute_allows_code_verified_when_tools_declaration_lacks_execution():
    """真纯丙：手写 code_verified + 声明无执行类 tools → 不再因白名单入闸拒绝。"""
    reg = _registry("file_read", "grep", "web_search", "test_run", "file_write")
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="验一下",
        history=[],
        tools=reg,
        base_tool_context=local_ctx(),
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "调研员",
                    "task": "只读调查",
                    "tools": ["file_read", "grep", "web_search"],
                }
            ],
            "completion_criteria": {
                "type": "code_verified",
                "verify_command": "pytest -q",
            },
            "complexity_hint": "standard",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert result.contract_failure is not True


# ── 落盘 × 无写盘白名单硬拒（真纯丙已退役）───────────────────────────────────


def _plan_files_with_tools(tools: list[str] | None, *, role: str = "前端"):
    plan, errors = build_run_plan(
        [
            {
                "role": role,
                "task": "写 index.html",
                "deliverable": {"form": "files"},
                **({"tools": tools} if tools is not None else {}),
            }
        ],
        valid_tools=set(tools or [])
        | {
            "file_read",
            "grep",
            "web_search",
            "file_write",
            "str_replace",
            "test_run",
        },
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    return plan


def test_write_tools_gate_retired_for_files_form_with_search_only_whitelist():
    plan = _plan_files_with_tools(["file_read", "grep", "web_search"])
    assert validate_files_worker_tools(None, plan) is None


def test_write_tools_gate_passes_prose_with_search_whitelist():
    plan, errors = build_run_plan(
        [
            {
                "role": "调研",
                "task": "只读调研",
                "deliverable": {"form": "prose"},
                "tools": ["file_read", "grep", "web_search"],
            }
        ],
        valid_tools={"file_read", "grep", "web_search"},
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    assert validate_files_worker_tools(None, plan) is None


def test_write_tools_gate_passes_files_with_unrestricted_tools():
    plan = _plan_files_with_tools(None)
    assert validate_files_worker_tools(None, plan) is None
    assert validate_files_worker_tools("files_written", plan) is None


def test_write_tools_gate_passes_files_with_file_write():
    plan = _plan_files_with_tools(["file_read", "file_write"])
    assert node_holds_write_tools(plan.nodes[0]) is True
    assert validate_files_worker_tools(None, plan) is None


def test_write_tools_gate_batch_retired_for_files_written_without_write_tools():
    plan = _plan_with_tools(["file_read", "grep"])
    assert validate_files_worker_tools("files_written", plan) is None


def test_write_tools_gate_batch_passes_when_one_non_prose_holds_write():
    plan, errors = build_run_plan(
        [
            {
                "role": "调研",
                "task": "只读",
                "deliverable": {"form": "prose"},
                "tools": ["file_read", "grep"],
            },
            {
                "role": "实现",
                "task": "落盘",
                "deliverable": {"form": "files"},
                "tools": ["file_read", "file_write"],
            },
        ],
        valid_tools={"file_read", "grep", "file_write"},
        id_prefix="cap",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    assert validate_files_worker_tools("files_written", plan) is None


def test_write_tools_gate_node_holds_write_tools_always_true():
    """真纯丙：不再用白名单判断；窄名单亦视为具备写盘。"""
    assert node_holds_write_tools(RunSpec(run_id="a", role="x", task="t", tools=None))
    assert node_holds_write_tools(
        RunSpec(run_id="a", role="x", task="t", tools=["str_replace", "file_read"])
    )
    assert node_holds_write_tools(
        RunSpec(run_id="a", role="x", task="t", tools=["file_read", "grep"])
    )


@pytest.mark.asyncio
async def test_execute_allows_files_form_with_search_only_tools_declaration():
    """真纯丙：form=files + 声明检索 tools → 不再 no_write_tools 拒派。"""
    reg = _registry("file_read", "grep", "web_search", "file_write")
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="写站",
        history=[],
        tools=reg,
        base_tool_context=local_ctx(),
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写 index.html",
                    "deliverable": {"form": "files"},
                    "tools": ["file_read", "grep", "web_search"],
                }
            ],
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert result.contract_failure is not True
    assert "no_write_tools" not in (result.error or "")
    assert "写盘" not in (result.error or "")

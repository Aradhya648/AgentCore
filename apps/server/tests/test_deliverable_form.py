"""Unit tests for deliverable.form (prose | files) on the delegate contract path."""

from __future__ import annotations

from agentcore.runtime.delegate.completion import (
    plan_all_workers_prose,
    plan_declares_files_form,
    resolve_completion_criteria,
    validate_completion_against_forms,
)
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.contract import describe_deliverable
from agentcore.runtime.runs.executor_identities import (
    PROSE_WITHHELD_WRITE_TOOLS,
    build_worker_identity,
)
from agentcore.runtime.runs.types import Deliverable
from agentcore.tools.builtin.delegate.schema import (
    DELEGATE_DESCRIPTION,
    DELEGATE_PARAMETERS,
    TASK_DELIVERABLE_SCHEMA,
)


def test_form_parsed_onto_deliverable():
    plan, errs = build_run_plan(
        [{"role": "A", "task": "打招呼", "deliverable": {"form": "prose"}}],
        id_prefix="t",
    )
    assert errs == []
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.form == "prose"
    assert d.requires_files is False


def test_form_files_implies_requires_files():
    plan, errs = build_run_plan(
        [{"role": "A", "task": "建站", "deliverable": {"form": "files"}}],
        id_prefix="t",
    )
    assert errs == []
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.form == "files"
    assert d.requires_files is True


def test_form_alone_is_enough_content():
    plan, errs = build_run_plan(
        [{"role": "A", "task": "a", "deliverable": {"form": "prose"}}],
        id_prefix="t",
    )
    assert errs == []
    assert plan.nodes[0].deliverable is not None


def test_form_prose_clears_requires_files_and_artifacts():
    plan, _ = build_run_plan(
        [
            {
                "role": "A",
                "task": "a",
                "deliverable": {
                    "form": "prose",
                    "requires_files": True,
                    "artifacts": ["hello.md"],
                },
            }
        ],
        id_prefix="t",
    )
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.form == "prose"
    assert d.requires_files is False
    assert d.artifacts == []


def test_invalid_form_dropped():
    plan, _ = build_run_plan(
        [{"role": "A", "task": "a", "deliverable": {"form": "slides", "name": "x"}}],
        id_prefix="t",
    )
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.form is None
    assert d.name == "x"


def test_identity_form_prose_has_no_file_write_guidance():
    prose = build_worker_identity(has_dependents=False, form="prose")
    files = build_worker_identity(has_dependents=False, form="files")
    omitted = build_worker_identity(has_dependents=False, form=None)

    assert "form=prose" in prose
    assert "file_write" not in prose
    assert "纯文字" in prose

    assert "form=files" in files
    assert "file_write" in files
    assert "必须" in files
    # 落盘纪律落在 worker 会读到的 identity（不只 CEO skill）。
    assert "str_replace" in files
    assert "骨架 file_write" in files and "分段 file_append" in files
    assert "中间省略" in files or "落盘与修订" in files

    # omit = legacy two-way
    assert "可独立阅读的文字" in omitted
    assert "file_write" in omitted
    assert "落盘与修订" in omitted
    assert "骨架 file_write" in omitted and "分段 file_append" in omitted

def test_requires_files_injects_files_form_identity_block():
    """requires_files（或 artifacts）且 form 省略 ⇒ 强制 files 形态提示，非 legacy。"""
    by_flag = build_worker_identity(has_dependents=False, requires_files=True)
    assert "form=files" in by_flag
    assert "落盘文件" in by_flag
    assert "file_write" in by_flag
    assert "可独立阅读的文字" not in by_flag

    by_artifacts = build_worker_identity(
        has_dependents=False, artifacts=["report.md"]
    )
    assert "form=files" in by_artifacts
    assert "落盘文件" in by_artifacts

    # Explicit prose still wins (builder clears requires_files, but API stays coherent).
    prose_wins = build_worker_identity(
        has_dependents=False, form="prose", requires_files=True
    )
    assert "form=prose" in prose_wins
    assert "form=files" not in prose_wins


def test_identity_handoff_topology_preserved_with_form():
    up = build_worker_identity(has_dependents=True, form="prose")
    leaf = build_worker_identity(has_dependents=False, form="prose")
    assert "必须调用 handoff" in up
    assert "不必为交而交" in leaf
    assert "必须调用 handoff" not in leaf


def test_describe_deliverable_form_split():
    prose = describe_deliverable(Deliverable(form="prose", name="问候"))
    assert "纯文字" in prose
    assert "file_write" not in prose

    files = describe_deliverable(Deliverable(form="files", name="站点"))
    assert "落盘" in files
    assert "file_write" in files


def test_schema_exposes_form_enum():
    props = TASK_DELIVERABLE_SCHEMA["properties"]
    assert "form" in props
    assert props["form"]["enum"] == ["prose", "files"]
    assert "prose" in props["form"]["description"]
    assert "才用本工具" not in DELEGATE_DESCRIPTION
    # 纠正「一次只能 / 同步阻塞到全队完成」误述（协调默认立即返回、可同回合追加）
    assert "立即返回" in DELEGATE_DESCRIPTION
    assert "一张图" in DELEGATE_DESCRIPTION
    deps = DELEGATE_PARAMETERS["properties"]["tasks"]["items"]["properties"]["depends_on"][
        "description"
    ]
    assert "id 字段字面值" in deps or "同一次 tasks" in deps
    assert ("role" in deps or "角色名" in deps) and "del_*" in deps
    props_task = DELEGATE_PARAMETERS["properties"]["tasks"]["items"]["properties"]
    assert "require_upstream" in props_task
    assert "≥1" in props_task["require_upstream"]["description"] or "全量" in props_task[
        "require_upstream"
    ]["description"]

    coord = DELEGATE_PARAMETERS["properties"]["coordinate"]["description"]
    assert "协调" in coord
    assert "阻塞" in coord


def test_schema_depends_on_teaches_when_to_declare_dependency():
    # 工具面瘦身：【何时填】长引导（生产者→消费者 + 正反例）已迁入 CEO core
    # （见 test_core_teaches_dependency_judgment_before_delegating）；schema 只留
    # 「怎么填」约束 + 顶层短线索，避免与系统提示重复烧 input tokens。
    deps = DELEGATE_PARAMETERS["properties"]["tasks"]["items"]["properties"]["depends_on"][
        "description"
    ]
    assert "id 字段字面值" in deps and "del_*" in deps
    assert "角色名" in deps or "role" in deps
    assert "生产者→消费者" in deps  # 短指针，细节在 core
    # 顶层工具描述仍钉判断线索（勿默认全平铺）。
    assert "生产者→消费者" in DELEGATE_DESCRIPTION
    assert "平铺并行" in DELEGATE_DESCRIPTION


def test_resolve_infers_files_written_from_form_files():
    plan, _ = build_run_plan(
        [{"role": "A", "task": "写 index.html", "deliverable": {"form": "files"}}],
        id_prefix="t",
    )
    criteria = resolve_completion_criteria(None, plan)
    assert criteria is not None
    assert criteria.kind == "files_written"


def test_resolve_never_infers_files_written_for_all_prose():
    plan, _ = build_run_plan(
        [
            {"role": "A", "task": "打招呼", "deliverable": {"form": "prose"}},
            {"role": "B", "task": "也打招呼", "deliverable": {"form": "prose"}},
        ],
        id_prefix="t",
    )
    assert plan_all_workers_prose(plan)
    assert resolve_completion_criteria(None, plan) is None


def test_prose_times_files_written_rejected():
    plan, _ = build_run_plan(
        [
            {"role": "A", "task": "打招呼", "deliverable": {"form": "prose"}},
            {"role": "B", "task": "也打招呼", "deliverable": {"form": "prose"}},
        ],
        id_prefix="t",
    )
    err = validate_completion_against_forms("files_written", plan)
    assert err is not None
    assert "契约矛盾" in err
    assert "form=prose" in err


def test_mixed_batch_allows_files_written():
    plan, _ = build_run_plan(
        [
            {"role": "A", "task": "分析", "deliverable": {"form": "prose"}},
            {"role": "B", "task": "写页", "deliverable": {"form": "files"}},
        ],
        id_prefix="t",
    )
    assert plan_declares_files_form(plan)
    assert not plan_all_workers_prose(plan)
    assert validate_completion_against_forms("files_written", plan) is None


def test_prose_withheld_write_tools_constant():
    assert set(PROSE_WITHHELD_WRITE_TOOLS) == {
        "file_write",
        "file_append",
        "str_replace",
    }


async def test_prose_worker_not_offered_write_tools():
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.runs.executor import build_agent_executor
    from agentcore.runtime.runs.types import RunPhase
    from agentcore.runtime.runs.wave import WaveScheduler
    from agentcore.tools.registry import ToolRegistry
    from tests.runs_executor.conftest import (
        _ContentProvider,
        _ctx,
        _GrantableTool,
        _OfferRecorder,
    )

    tasks = [{"role": "A", "task": "打招呼", "deliverable": {"form": "prose"}}]
    plan, _ = build_run_plan(tasks, id_prefix="t")
    reg = ToolRegistry()
    for name in ("file_write", "file_append", "str_replace", "file_read", "code_execute"):
        reg.register(_GrantableTool(name))
    provider = _OfferRecorder()
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="让每个 AI 打招呼",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    assert res["t_1"].phase is RunPhase.COMPLETED
    offered = set(provider.offered[0])
    assert "file_write" not in offered
    assert "file_append" not in offered
    assert "str_replace" not in offered
    assert "file_read" in offered
    assert "code_execute" in offered

    plan2, _ = build_run_plan(tasks, id_prefix="u")
    id_provider = _ContentProvider(["HI"])
    id_exec = build_agent_executor(
        plan=plan2,
        llm=id_provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="让每个 AI 打招呼",
        execution_id="e2",
    )
    await WaveScheduler().run(plan2, id_exec)
    assert "form=prose" in id_provider.system_messages[0]
    assert "file_write" not in id_provider.system_messages[0]


async def test_files_worker_keeps_write_tools_and_identity():
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.runs.executor import build_agent_executor
    from agentcore.runtime.runs.types import RunPhase
    from agentcore.runtime.runs.wave import WaveScheduler
    from agentcore.tools.registry import ToolRegistry
    from tests.runs_executor.conftest import (
        _ContentProvider,
        _ctx,
        _GrantableTool,
    )

    plan, _ = build_run_plan(
        [{"role": "A", "task": "建页面", "deliverable": {"form": "files"}}],
        id_prefix="t",
    )
    reg = ToolRegistry()
    reg.register(_GrantableTool("file_write"))
    provider = _ContentProvider(["DONE"])
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="做一个网页",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    assert res["t_1"].phase is RunPhase.COMPLETED
    assert "form=files" in provider.system_messages[0]
    assert "file_write" in provider.system_messages[0]

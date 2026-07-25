"""Unit tests for delegate completion_criteria verification."""

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.delegate.completion import (
    CompletionCriteria,
    check_delegate_completion,
    collect_worker_gaps,
    format_batch_acceptance_for_worker,
    format_completion_gap_message,
    format_resolved_acceptance_echo,
    format_worker_gaps_block,
    gap_fingerprint,
    hoist_task_completion_criteria,
    parse_completion_criteria,
    plan_suggests_code_verification,
    resolve_completion_criteria,
    resolve_completion_with_source,
    should_inject_batch_acceptance,
)
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import Deliverable, RunPhase, RunSpec, RunState


def _run(*, files: list[str] | None = None, transcript: list[LLMMessage] | None = None):
    return RunState(
        phase=RunPhase.COMPLETED,
        content="done",
        files_touched=files or [],
        transcript=transcript or [],
    )


def test_parse_defaults_to_no_enforcement_when_omitted():
    assert parse_completion_criteria(None) is None
    assert parse_completion_criteria("code_verified").kind == "code_verified"


def test_omitted_criteria_is_backward_compatible():
    criteria = parse_completion_criteria(None)
    ok, gaps = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []


def test_custom_criteria_does_not_block_completion():
    # custom is not engine-verified — must not mark successful delegates unfinished.
    criteria = parse_completion_criteria({"type": "custom", "description": "用户满意即可"})
    ok, gaps = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []

    criteria_bare = parse_completion_criteria("custom")
    ok, gaps = check_delegate_completion(criteria_bare, {"a": _run()})
    assert ok
    assert gaps == []


def test_files_written_requires_workspace_write():
    criteria = parse_completion_criteria("files_written")
    ok, gaps = check_delegate_completion(criteria, {"a": _run()})
    assert not ok
    assert "落盘" in gaps[0]

    ok, gaps = check_delegate_completion(criteria, {"a": _run(files=["main.py"])})
    assert ok
    assert gaps == []


def test_code_verified_requires_successful_code_execute():
    criteria = parse_completion_criteria("code_verified")
    ok, _ = check_delegate_completion(criteria, {"a": _run()})
    assert not ok

    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(name="code_execute", arguments="{}"),
                )
            ],
        ),
        LLMMessage(role="tool", content="stdout:\n1\n", tool_call_id="tc1"),
    ]
    ok, gaps = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert ok
    assert gaps == []


def test_format_completion_gap_message():
    msg = format_completion_gap_message(["缺文件", "缺验证"])
    assert "完成条件未满足" in msg
    assert "缺文件" in msg


def test_format_gap_names_text_inferred_source_and_decl_hint():
    msg = format_completion_gap_message(
        ["尚无 worker 成功运行 code_execute / test_run 验证代码"],
        criteria_kind="code_verified",
        source="text_inferred",
    )
    assert "任务文案推断" in msg
    assert "delegate 顶层" in msg
    assert "completion_criteria=files_written" in msg


def test_format_gap_escalates_after_same_gap_streak():
    msg = format_completion_gap_message(
        ["尚无 worker 成功运行 code_execute / test_run 验证代码"],
        criteria_kind="code_verified",
        source="text_inferred",
        escalate=True,
        delivered_files=["index.html", "style.css"],
    )
    assert "已交付产物" in msg
    assert "`index.html`" in msg
    assert "连续出现 2 次" in msg
    assert "不要再以相同标准重派" in msg


def test_plan_suggests_code_verification_on_run_open_tasks():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="w1", task="修复启动问题并验证进程能打开"),
        ],
    )
    assert plan_suggests_code_verification(plan)


def test_resolve_never_binds_code_verified_from_task_text():
    """B1: 文案「跑通」不再绑定 code_verified；省略 = 不强制。"""
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="npm run start 跑通")])
    assert plan_suggests_code_verification(plan)  # 软警告启发仍命中
    resolved = resolve_completion_with_source(None, plan)
    assert resolved.criteria is None
    assert resolved.source is None
    assert format_resolved_acceptance_echo(resolved) == "本批验收：未启用"


def test_resolve_form_files_beats_run_open_text_heuristics():
    """Regression: 宣传站 form=files + 「打开/运行」文案不得推断为 code_verified."""
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="写静态宣传官网 index.html，完成后打开页面验收",
                deliverable=Deliverable(form="files", requires_files=True),
            )
        ]
    )
    assert plan_suggests_code_verification(plan)  # 文案仍命中启发
    resolved = resolve_completion_with_source(None, plan)
    assert resolved.criteria is not None
    assert resolved.criteria.kind == "files_written"
    assert resolved.source == "structured"


def test_hoist_single_task_completion_criteria():
    raw, err = hoist_task_completion_criteria(
        None,
        [{"role": "前端", "task": "写站", "completion_criteria": "files_written"}],
    )
    assert err is None
    assert raw == "files_written"


def test_hoist_unanimous_multi_task_completion_criteria():
    raw, err = hoist_task_completion_criteria(
        None,
        [
            {"role": "A", "task": "t1", "completion_criteria": "files_written"},
            {"role": "B", "task": "t2", "completion_criteria": "files_written"},
        ],
    )
    assert err is None
    assert raw == "files_written"


def test_hoist_conflict_multi_task_completion_criteria():
    raw, err = hoist_task_completion_criteria(
        None,
        [
            {"role": "A", "task": "t1", "completion_criteria": "files_written"},
            {"role": "B", "task": "t2", "completion_criteria": "code_verified"},
        ],
    )
    assert raw is None
    assert err is not None
    assert "冲突" in err
    assert "tasks[].completion_criteria" in err
    assert "顶层" in err


def test_hoist_skipped_when_top_level_present():
    raw, err = hoist_task_completion_criteria(
        "code_verified",
        [{"role": "A", "task": "t1", "completion_criteria": "files_written"}],
    )
    assert err is None
    assert raw == "code_verified"


def test_gap_fingerprint_stable_for_streak():
    a = gap_fingerprint("code_verified", ["缺验证"])
    b = gap_fingerprint("code_verified", ["缺验证"])
    c = gap_fingerprint("files_written", ["缺验证"])
    assert a == b
    assert a != c


def test_delegate_tool_same_gap_streak_escalates_at_two():
    """Consecutive identical unmet gaps: streak 1 → 2 (escalate threshold)."""
    from agentcore.core.types import AutonomyPolicy
    from agentcore.runtime.events import EventSink
    from agentcore.tools.builtin.delegate import DelegateTool
    from agentcore.tools.registry import ToolRegistry
    from tests.delegate.conftest import Provider, ctx

    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="u",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=ctx(),
        autonomy_policy=AutonomyPolicy.FULL_AUTO,
    )
    fp = gap_fingerprint("code_verified", ["缺验证"])
    assert t.note_completion_gap(fp) == 1
    assert t.note_completion_gap(fp) == 2
    assert t.note_completion_gap(fp) == 3
    other = gap_fingerprint("files_written", ["缺落盘"])
    assert t.note_completion_gap(other) == 1
    t.clear_completion_gap_streak()
    assert t.note_completion_gap(fp) == 1


def test_resolve_keeps_legacy_no_enforcement_for_doc_tasks():
    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="写一份产品说明文档")])
    assert resolve_completion_criteria(None, plan) is None


def test_resolve_enables_files_written_when_artifacts_declared():
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="集成",
                deliverable=Deliverable(artifacts=["README.md", "examples/*"]),
            )
        ]
    )
    criteria = resolve_completion_criteria(None, plan)
    assert criteria is not None
    assert criteria.kind == "files_written"


def test_resolve_enables_files_written_when_form_files():
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="建页面",
                deliverable=Deliverable(form="files", requires_files=True),
            )
        ]
    )
    criteria = resolve_completion_criteria(None, plan)
    assert criteria is not None
    assert criteria.kind == "files_written"


def test_resolve_skips_files_written_when_all_prose():
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="打招呼",
                deliverable=Deliverable(form="prose"),
            )
        ]
    )
    assert resolve_completion_criteria(None, plan) is None


def test_collect_worker_gaps_surfaces_warnings_and_degraded_handoff():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="a", role="集成岗", task="t"),
            RunSpec(run_id="b", role="架构师", task="t"),
        ]
    )
    results = {
        "a": RunState(
            phase=RunPhase.COMPLETED,
            content="x",
            warnings=["声明的交付物路径未落盘：`README.md`"],
        ),
        "b": RunState(
            phase=RunPhase.COMPLETED,
            content="y",
            debrief={"summary": "合成", "degraded": True},
        ),
    }
    gaps = collect_worker_gaps(plan, results)
    assert len(gaps) == 2
    block = format_worker_gaps_block(gaps)
    assert "契约缺口" in block
    assert "集成岗" in block
    assert "架构师" in block
    assert "降级合成" in block
    assert "部分交付" in block
    assert "无需审计" in block


def test_format_worker_gaps_audit_off_token_budget_tip():
    gaps = [
        (
            "写手",
            [{"description": "正文缩水", "reason": "token_budget"}],
        )
    ]
    block = format_worker_gaps_block(gaps, audit_off_with_token_budget=True)
    assert "部分交付" in block
    assert "建议抽检" in block
    assert "token_budget" in block
    criteria = parse_completion_criteria("code_verified")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(name="test_run", arguments="{}"),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="### 摘要\n- 通过：3 / 失败：0 / 错误：0",
            tool_call_id="tc1",
        ),
    ]
    ok, gaps = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert ok
    assert gaps == []


def _run_empty_body(*, files: list[str] | None = None, debrief: dict | None = None):
    """COMPLETED worker that finished via 落盘 / handoff with no streamed prose."""
    return RunState(
        phase=RunPhase.COMPLETED,
        content="",
        files_touched=files or [],
        debrief=debrief,
        transcript=[],
    )


def test_files_written_empty_body_with_disk_write_passes():
    """Pure file_write finish (empty content) must still satisfy files_written."""
    criteria = parse_completion_criteria("files_written")
    ok, gaps = check_delegate_completion(
        criteria, {"a": _run_empty_body(files=["index.html"])}
    )
    assert ok
    assert gaps == []


def test_files_written_empty_body_without_evidence_is_gap_not_vacuous_pass():
    """COMPLETED + empty body + no 落盘 must gap — never vacuous-pass the empty set."""
    criteria = parse_completion_criteria("files_written")
    ok, gaps = check_delegate_completion(
        criteria,
        {"a": _run_empty_body(debrief={"summary": "写完了"})},
    )
    assert not ok
    assert "落盘" in gaps[0]


def test_code_verified_empty_body_without_verify_is_gap():
    criteria = parse_completion_criteria("code_verified")
    ok, gaps = check_delegate_completion(criteria, {"a": _run_empty_body()})
    assert not ok
    assert "code_execute" in gaps[0] or "验证" in gaps[0]


def test_format_resolved_acceptance_echo_variants():
    assert (
        format_resolved_acceptance_echo(resolve_completion_with_source(None, None))
        == "本批验收：未启用"
    )
    explicit = resolve_completion_with_source("code_verified", None)
    assert format_resolved_acceptance_echo(explicit) == "本批验收：code_verified（显式声明）"
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="建页面",
                deliverable=Deliverable(form="files", requires_files=True),
            )
        ]
    )
    structured = resolve_completion_with_source(None, plan)
    assert (
        format_resolved_acceptance_echo(structured)
        == "本批验收：files_written（结构化交付声明）"
    )


def test_should_inject_batch_acceptance_scopes_to_exec_files_nodes():
    criteria = CompletionCriteria(kind="code_verified")
    files_unrestricted = RunSpec(
        run_id="w1",
        task="写并跑通",
        deliverable=Deliverable(form="files"),
        tools=None,
    )
    files_exec = RunSpec(
        run_id="w2",
        task="写并跑通",
        deliverable=Deliverable(form="files"),
        tools=["file_write", "code_execute"],
    )
    files_no_exec = RunSpec(
        run_id="w3",
        task="只写文件",
        deliverable=Deliverable(form="files"),
        tools=["file_write", "file_read"],
    )
    prose = RunSpec(
        run_id="w4",
        task="调研",
        deliverable=Deliverable(form="prose"),
        tools=None,
    )
    assert should_inject_batch_acceptance(files_unrestricted, criteria)
    assert should_inject_batch_acceptance(files_exec, criteria)
    assert not should_inject_batch_acceptance(files_no_exec, criteria)
    assert not should_inject_batch_acceptance(prose, criteria)
    assert not should_inject_batch_acceptance(files_unrestricted, None)
    line = format_batch_acceptance_for_worker(criteria)
    assert "本批验收：code_verified" in line
    assert "code_execute" in line


def test_b2_injects_acceptance_into_deliverable_context_block():
    """B2：持执行工具 ∧ form=files 的节点交付物规格含批次验收行；prose 同伴不注入。"""
    from agentcore.runtime.runs.executor_context import _build_context_blocks

    criteria = CompletionCriteria(kind="files_written")
    writer = RunSpec(
        run_id="w1",
        task="写站点",
        deliverable=Deliverable(form="files", requires_files=True),
        tools=None,
    )
    researcher = RunSpec(
        run_id="w2",
        task="调研",
        deliverable=Deliverable(form="prose"),
        tools=None,
    )
    plan = RunPlan(nodes=[writer, researcher])
    writer_blocks = _build_context_blocks(
        plan,
        writer,
        {},
        "原始请求",
        writer.deliverable,
        [],
        batch_completion_criteria=criteria,
    )
    bodies = {b.channel: b.body for b in writer_blocks}
    assert "deliverable" in bodies
    assert "本批验收：files_written" in bodies["deliverable"]
    research_blocks = _build_context_blocks(
        plan,
        researcher,
        {},
        "原始请求",
        researcher.deliverable,
        [],
        batch_completion_criteria=criteria,
    )
    research_bodies = {b.channel: b.body for b in research_blocks}
    assert "本批验收" not in (research_bodies.get("deliverable") or "")


def test_suppress_structured_skips_form_files_inference():
    """Cold-start explore pending: no auto files_written from form=files."""
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="摸清项目",
                deliverable=Deliverable(form="files", requires_files=True),
            )
        ]
    )
    suppressed = resolve_completion_with_source(
        None, plan, suppress_structured_files_written=True
    )
    assert suppressed.criteria is None
    assert suppressed.source is None
    # Explicit still binds.
    explicit = resolve_completion_with_source(
        "files_written", plan, suppress_structured_files_written=True
    )
    assert explicit.criteria is not None
    assert explicit.criteria.kind == "files_written"
    assert explicit.source == "explicit"


def test_suppress_structured_skips_artifacts_inference():
    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="w1",
                task="摸清项目",
                deliverable=Deliverable(artifacts=["notes.md"]),
            )
        ]
    )
    assert (
        resolve_completion_with_source(
            None, plan, suppress_structured_files_written=True
        ).criteria
        is None
    )
    # Without suppress, structured still binds (建站回归).
    normal = resolve_completion_with_source(None, plan)
    assert normal.criteria is not None
    assert normal.criteria.kind == "files_written"
    assert normal.source == "structured"


def test_files_written_gap_lists_landing_tools_from_serialize():
    """Gap tool list must share serialize._FILE_PRODUCT_ARG + code_execute write-back."""
    from agentcore.runtime.runs.serialize import format_file_landing_tools_slash

    criteria = parse_completion_criteria("files_written")
    ok, gaps = check_delegate_completion(criteria, {"a": _run()})
    assert not ok
    expected = format_file_landing_tools_slash()
    assert expected in gaps[0]
    assert "file_write" in gaps[0]
    assert "file_append" in gaps[0]
    assert "str_replace" in gaps[0]
    assert "write_section" in gaps[0]
    assert "file_move" in gaps[0]
    assert "code_execute" in gaps[0]

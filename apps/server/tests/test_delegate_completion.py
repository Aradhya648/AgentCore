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
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []


def test_custom_criteria_does_not_block_completion():
    # custom is not engine-verified — must not mark successful delegates unfinished.
    criteria = parse_completion_criteria({"type": "custom", "description": "用户满意即可"})
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []

    criteria_bare = parse_completion_criteria("custom")
    ok, gaps, _soft = check_delegate_completion(criteria_bare, {"a": _run()})
    assert ok
    assert gaps == []


def test_files_written_requires_workspace_write():
    """甲⁺：未落盘 → soft note；有落盘 → 无 tip。均不挡批次。"""
    criteria = parse_completion_criteria("files_written")
    ok, gaps, soft = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []
    assert any("本批未见落盘" in n for n in soft)

    ok, gaps, soft = check_delegate_completion(criteria, {"a": _run(files=["main.py"])})
    assert ok
    assert gaps == []
    assert not any("本批未见落盘" in n for n in soft)


def test_code_verified_rejects_bare_code_execute():
    """Non-verify code_execute must not satisfy code_verified (no compat fallback)."""
    criteria = parse_completion_criteria("code_verified")
    ok, _, _soft = check_delegate_completion(criteria, {"a": _run()})
    assert not ok

    bare = [
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
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=bare)})
    assert not ok
    assert any("验证" in g or "code_execute" in g for g in gaps)


def test_code_verified_accepts_verify_shaped_code_execute_exit_zero():
    criteria = parse_completion_criteria("code_verified")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="code_execute",
                        arguments='{"code":"npx tsc -b","language":"bash"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="stdout:\n\n\n退出码：0",
            tool_call_id="tc1",
        ),
    ]
    # 乙第二刀：验绿之外还须落盘信号，避免「零写预存绿测」假绿。
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(files=["src/fixed.ts"], transcript=transcript)}
    )
    assert ok
    assert gaps == []


def test_code_verified_green_verify_without_landing_is_gap():
    """乙第二刀：绿 verify + 零落盘 → 落盘 gap（不得当修好交付）。"""
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
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert not ok
    assert any("落盘" in g for g in gaps)
    assert not any("验证" in g for g in gaps)  # verify 已绿，缺口只在落盘


def test_code_verified_green_verify_with_files_touched_passes():
    """乙第二刀：绿 verify + files_touched → ok。"""
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
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(files=["app.py"], transcript=transcript)}
    )
    assert ok
    assert gaps == []


def test_code_execute_verify_requires_explicit_exit_zero():
    """Verify-shaped args without exit 0 (or with non-zero) must gap."""
    criteria = parse_completion_criteria("code_verified")
    no_exit = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="code_execute",
                        arguments='{"code":"npx tsc -b","language":"bash"}',
                    ),
                )
            ],
        ),
        LLMMessage(role="tool", content="stdout:\nok\n", tool_call_id="tc1"),
    ]
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=no_exit)})
    assert not ok
    assert gaps

    nonzero = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc2",
                    type="function",
                    function=ToolCallFunction(
                        name="code_execute",
                        arguments='{"code":"npx tsc -b","language":"bash"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="stderr:\nerror\n退出码：1",
            tool_call_id="tc2",
        ),
    ]
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=nonzero)})
    assert not ok
    assert gaps


def test_typescript_landing_soft_note_when_criteria_omitted():
    """D2 overlay: .ts/.tsx 落盘无 verify → soft note only，不挡批次 / 无 unmet。"""
    ok, gaps, soft = check_delegate_completion(
        None, {"a": _run(files=["src/canvas/renderer.ts"])}
    )
    assert ok
    assert gaps == []
    assert soft
    assert any("不阻断验收" in g for g in soft)
    assert any("验证" in g for g in soft)

    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="code_execute",
                        arguments='{"code":"npx tsc -b","language":"bash"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="stdout:\n\n\n退出码：0",
            tool_call_id="tc1",
        ),
    ]
    ok, gaps, soft = check_delegate_completion(
        None,
        {"a": _run(files=["src/canvas/renderer.ts"], transcript=transcript)},
    )
    assert ok
    assert gaps == []
    assert soft == []


def test_terminal_tsc_counts_as_verify():
    criteria = parse_completion_criteria("code_verified")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="terminal",
                        arguments='{"subcommand":"start","command":"npx tsc -b"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="process_id: p1\nstatus: exited\nexit_code: 0\noutput:（无）",
            tool_call_id="tc1",
        ),
    ]
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(files=["src/main.ts"], transcript=transcript)}
    )
    assert ok
    assert gaps == []


def test_md_landing_without_verify_still_ok_when_omitted():
    ok, gaps, _soft = check_delegate_completion(None, {"a": _run(files=["notes.md"])})
    assert ok
    assert gaps == []


def test_format_completion_gap_message():
    msg = format_completion_gap_message(["缺文件", "缺验证"])
    assert "完成条件未满足" in msg
    assert "缺文件" in msg


def test_format_gap_names_text_inferred_source_and_decl_hint():
    msg = format_completion_gap_message(
        ["尚无 worker 成功验证代码（须 code_execute / test_run / terminal 跑通"],
        criteria_kind="code_verified",
        source="text_inferred",
    )
    assert "任务文案推断" in msg
    assert "delegate 顶层" in msg
    assert "completion_criteria=files_written" in msg


def test_format_gap_escalates_after_same_gap_streak():
    msg = format_completion_gap_message(
        ["尚无 worker 成功验证代码（须 code_execute / test_run / terminal 跑通"],
        criteria_kind="code_verified",
        source="text_inferred",
        escalate=True,
        delivered_files=["index.html", "style.css"],
    )
    assert "已交付产物" in msg
    assert "`index.html`" in msg
    assert "连续出现 2 次" in msg
    assert "不要再以相同标准重派" in msg


def test_format_gap_runtime_ready_appends_remediation():
    msg = format_completion_gap_message(
        ["尚无 worker 报告进程就绪（须 terminal start + wait_for 命中"],
        criteria_kind="runtime_ready",
        source="explicit",
    )
    assert "调度已结束" in msg
    assert "terminal list/read" in msg
    assert "browser_navigate" in msg
    assert "禁止再起同一套开发服务器" in msg
    assert "append_to=latest" in msg
    assert "勿整锅重派" in msg
    # Escalate path owns its own copy — remediation is soft-gap only.
    escalated = format_completion_gap_message(
        ["尚无 worker 报告进程就绪（须 terminal start + wait_for 命中"],
        criteria_kind="runtime_ready",
        source="explicit",
        escalate=True,
    )
    assert "补救：" not in escalated
    assert "不要再以相同标准重派" in escalated


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


def test_gap_fingerprint_unbound_criteria_no_fake_kind():
    """criteria=None must not invent typescript_verify; same gaps still streak."""
    a = gap_fingerprint(None, ["缺验证"])
    b = gap_fingerprint(None, ["缺验证"])
    bound = gap_fingerprint("code_verified", ["缺验证"])
    assert a == b
    assert a != bound
    assert a[0] == ""
    assert "typescript_verify" not in a


def test_delegate_tool_same_gap_streak_escalates_at_two():
    """Consecutive identical unmet gaps: streak 1 → 2 (escalate threshold)."""
    from agentcore.core.types import AutonomyPolicy, recipe_to_axes
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
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    fp = gap_fingerprint("code_verified", ["缺验证"])
    assert t.note_completion_gap(fp) == 1
    assert t.note_completion_gap(fp) == 2
    assert t.note_completion_gap(fp) == 3
    other = gap_fingerprint("files_written", ["缺落盘"])
    assert t.note_completion_gap(other) == 1
    t.clear_completion_gap_streak()
    assert t.note_completion_gap(fp) == 1


def test_delegate_tool_unbound_criteria_same_gap_streak():
    """Fingerprint API still streaks on None binding; soft overlays never call it."""
    from agentcore.core.types import AutonomyPolicy, recipe_to_axes
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
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    fp = gap_fingerprint(None, ["缺验证"])
    assert t.note_completion_gap(fp) == 1
    assert t.note_completion_gap(fp) == 2
    assert t.note_completion_gap(gap_fingerprint("code_verified", ["缺验证"])) == 1
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
    assert "交接说明不够完整" in block or "降级合成" in block
    assert "部分交付" in block
    assert "无需审计" in block


def test_zero_landing_soft_visible_per_worker_not_criteria_unmet():
    """定案 B：零落盘 → per-worker soft 可见；不 binding / 不 criteria_unmet。"""
    from agentcore.runtime.runs.contract import zero_files_gap_message

    plan = RunPlan(
        nodes=[
            RunSpec(
                run_id="landed",
                role="修码员",
                task="改后端",
                deliverable=Deliverable(form="files", requires_files=True),
            ),
            RunSpec(
                run_id="empty",
                role="前端工程师",
                task="改前端",
                deliverable=Deliverable(form="files", requires_files=True),
            ),
        ]
    )
    tip = zero_files_gap_message()
    results = {
        "landed": _run(files=["svc.py"]),
        "empty": RunState(
            phase=RunPhase.COMPLETED,
            content="还在读",
            delivery_gaps=[
                {
                    "description": tip,
                    "severity": "warning",
                    "reason": "files_not_landed",
                }
            ],
        ),
    }
    # Per-worker soft gap surfaces who skipped landing.
    by_worker = collect_worker_gaps(plan, results)
    assert len(by_worker) == 1
    label, rows = by_worker[0]
    assert label == "前端工程师"
    assert any("本队员本波未交卷" in r["description"] for r in rows)
    assert all(r.get("severity") == "warning" for r in rows)
    ceo_block = format_worker_gaps_block(by_worker)
    assert "前端工程师" in ceo_block
    assert "本队员本波未交卷" in ceo_block
    assert "修码员" not in ceo_block

    # Batch files_written: someone landed → no soft tip, never binding.
    criteria = parse_completion_criteria("files_written")
    ok, binding, soft = check_delegate_completion(criteria, results)
    assert ok
    assert binding == []
    assert not any("本批未见落盘" in n for n in soft)


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
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(files=["fixed.py"], transcript=transcript)}
    )
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
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run_empty_body(files=["index.html"])}
    )
    assert ok
    assert gaps == []


def test_files_written_empty_body_without_evidence_is_soft_not_vacuous_block():
    """甲⁺：COMPLETED + empty body + 无落盘 → soft note，不挡批次。"""
    criteria = parse_completion_criteria("files_written")
    ok, gaps, soft = check_delegate_completion(
        criteria,
        {"a": _run_empty_body(debrief={"summary": "写完了"})},
    )
    assert ok
    assert gaps == []
    assert any("本批未见落盘" in n for n in soft)


def test_code_verified_empty_body_without_verify_is_gap():
    criteria = parse_completion_criteria("code_verified")
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run_empty_body()})
    assert not ok
    assert any("验证" in g or "code_execute" in g for g in gaps)
    assert any("落盘" in g for g in gaps)


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
    """真纯丙：code_verified 不再按 tools 白名单收窄；有 criteria 即注入。"""
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
    files_narrow_tools = RunSpec(
        run_id="w3",
        task="只写文件",
        deliverable=Deliverable(form="files"),
        tools=["file_write", "file_read"],
    )
    # E2：验证员常 form=prose，亦须看见批次验收线。
    prose_with_exec = RunSpec(
        run_id="w4",
        task="验证修补",
        deliverable=Deliverable(form="prose"),
        tools=["code_execute", "file_read"],
    )
    prose_unrestricted = RunSpec(
        run_id="w5",
        task="验证修补",
        deliverable=Deliverable(form="prose"),
        tools=None,
    )
    prose_narrow_tools = RunSpec(
        run_id="w6",
        task="调研",
        deliverable=Deliverable(form="prose"),
        tools=["file_read", "grep"],
    )
    assert should_inject_batch_acceptance(files_unrestricted, criteria)
    assert should_inject_batch_acceptance(files_exec, criteria)
    assert should_inject_batch_acceptance(files_narrow_tools, criteria)
    assert should_inject_batch_acceptance(prose_with_exec, criteria)
    assert should_inject_batch_acceptance(prose_unrestricted, criteria)
    assert should_inject_batch_acceptance(prose_narrow_tools, criteria)
    assert not should_inject_batch_acceptance(files_unrestricted, None)
    line = format_batch_acceptance_for_worker(criteria)
    assert "本批验收：code_verified" in line
    assert "test_run" in line
    assert "code_execute" in line  # explicitly steer away from stuffing build into it
    assert "纯 prose" in line


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
    """甲⁺：未落盘改为 soft note「本批未见落盘」（不再 binding gap / 工具清单硬拦）。"""
    criteria = parse_completion_criteria("files_written")
    ok, gaps, soft = check_delegate_completion(criteria, {"a": _run()})
    assert ok
    assert gaps == []
    assert any("本批未见落盘" in n for n in soft)
    assert any("不阻断验收" in n for n in soft)

def _terminal_ready_transcript():
    return [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="terminal",
                        arguments='{"subcommand":"start","command":"npm run dev","wait_for":"Local:"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content=(
                "process_id: abc\nstatus: running\nmatched: True\n"
                "output:\n  Local: http://localhost:5173/\n"
                "\n\n【就绪判定】wait_for 已命中，可报告访问地址；"
            ),
            tool_call_id="tc1",
        ),
    ]


def test_parse_runtime_ready():
    assert parse_completion_criteria("runtime_ready").kind == "runtime_ready"


def test_runtime_ready_accepts_terminal_wait_for_matched():
    criteria = parse_completion_criteria("runtime_ready")
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(transcript=_terminal_ready_transcript())}
    )
    assert ok
    assert gaps == []


def test_runtime_ready_rejects_verify_shaped_only():
    """tsc exit 0 must not satisfy runtime_ready — different acceptance class."""
    criteria = parse_completion_criteria("runtime_ready")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="terminal",
                        arguments='{"subcommand":"exec","command":"npx tsc --noEmit"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="status: exited\nexit_code: 0\noutput:\n",
            tool_call_id="tc1",
        ),
    ]
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert not ok
    assert any("进程就绪" in g for g in gaps)


def test_code_verified_rejects_dev_server_start():
    """npm run dev ready must not satisfy code_verified."""
    criteria = parse_completion_criteria("code_verified")
    ok, gaps, _soft = check_delegate_completion(
        criteria, {"a": _run(transcript=_terminal_ready_transcript())}
    )
    assert not ok
    assert any("验证" in g for g in gaps)


def test_kind_fit_rejects_code_verified_on_start_task():
    from agentcore.runtime.delegate.completion import validate_criteria_kind_fit
    from agentcore.runtime.runs import build_run_plan

    plan, errors = build_run_plan(
        [{"role": "启动员", "task": "执行 npm run dev 启动 Vite 开发服务器并汇报 URL"}],
        valid_tools=set(),
        id_prefix="fit",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    msg = validate_criteria_kind_fit("code_verified", plan)
    assert msg is not None
    assert "runtime_ready" in msg


def test_kind_fit_rejects_runtime_ready_on_verify_task():
    from agentcore.runtime.delegate.completion import validate_criteria_kind_fit
    from agentcore.runtime.runs import build_run_plan

    plan, errors = build_run_plan(
        [{"role": "测试", "task": "跑通 pytest 并确保全部通过"}],
        valid_tools=set(),
        id_prefix="fit",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    msg = validate_criteria_kind_fit("runtime_ready", plan)
    assert msg is not None
    assert "code_verified" in msg


def test_kind_fit_allows_runtime_ready_on_start_task():
    from agentcore.runtime.delegate.completion import validate_criteria_kind_fit
    from agentcore.runtime.runs import build_run_plan

    plan, errors = build_run_plan(
        [{"role": "启动员", "task": "npm run dev 启动开发服务器"}],
        valid_tools=set(),
        id_prefix="fit",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    assert validate_criteria_kind_fit("runtime_ready", plan) is None


def test_should_inject_runtime_ready_without_files_form():
    """真纯丙：runtime_ready 对窄 tools / prose 同伴同样注入验收线。"""
    criteria = CompletionCriteria(kind="runtime_ready")
    starter = RunSpec(
        run_id="w1",
        task="启动开发服务器",
        deliverable=None,
        tools=["terminal", "file_read"],
    )
    prose_peer = RunSpec(
        run_id="w2",
        task="旁观",
        deliverable=Deliverable(form="prose"),
        tools=["file_read"],
    )
    assert should_inject_batch_acceptance(starter, criteria)
    assert should_inject_batch_acceptance(prose_peer, criteria)
    line = format_batch_acceptance_for_worker(criteria)
    assert "runtime_ready" in line
    assert "wait_for" in line


def _fit(task: str, criteria: str):
    from agentcore.runtime.delegate.completion import validate_criteria_kind_fit
    from agentcore.runtime.runs import build_run_plan

    plan, errors = build_run_plan(
        [{"role": "A", "task": task}],
        valid_tools=set(),
        id_prefix="fit",
        parent_run_id="CEO",
        depth=1,
    )
    assert not errors
    return validate_criteria_kind_fit(criteria, plan)


def test_kind_fit_bare_start_research_not_runtime_shape():
    """裸「启动调研」不得当成进程启动形去拒 code_verified。"""
    assert _fit("启动调研", "code_verified") is None


def test_kind_fit_start_npm_test_is_verify_not_runtime():
    """「启动 npm test」应以 verify 启发为准，允许 code_verified。"""
    assert _fit("启动 npm test", "code_verified") is None
    msg = _fit("启动 npm test", "runtime_ready")
    assert msg is not None
    assert "code_verified" in msg


def test_kind_fit_colloquial_run_project_blocks_code_verified():
    assert _fit("把项目跑起来", "code_verified") is not None
    assert "runtime_ready" in _fit("把项目跑起来", "code_verified")


def test_kind_fit_npm_test_without_run_keyword():
    assert _fit("执行 npm test", "code_verified") is None
    assert _fit("执行 npm test", "runtime_ready") is not None


def test_runtime_ready_rejects_read_without_start():
    criteria = parse_completion_criteria("runtime_ready")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="terminal",
                        arguments='{"subcommand":"read","process_id":"abc"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content=(
                "process_id: abc\nstatus: running\nmatched: True\n"
                "output:\n  Local: http://localhost:5173/\n"
            ),
            tool_call_id="tc1",
        ),
    ]
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert not ok
    assert any("进程就绪" in g for g in gaps)


def test_runtime_ready_ignores_matched_true_inside_output():
    """stdout 里出现 matched: True 不得冒充就绪。"""
    criteria = parse_completion_criteria("runtime_ready")
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc1",
                    type="function",
                    function=ToolCallFunction(
                        name="terminal",
                        arguments='{"subcommand":"start","command":"npm run dev","wait_for":"Local:"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content=(
                "process_id: abc\nstatus: running\nmatched: False\n"
                "output:\n  debug matched: True in log\n  still starting...\n"
            ),
            tool_call_id="tc1",
        ),
    ]
    ok, gaps, _soft = check_delegate_completion(criteria, {"a": _run(transcript=transcript)})
    assert not ok


def test_d2_skipped_when_runtime_ready_even_if_tsx_landed():
    criteria = parse_completion_criteria("runtime_ready")
    ok, gaps, soft = check_delegate_completion(
        criteria,
        {
            "a": _run(
                files=["src/App.tsx"],
                transcript=_terminal_ready_transcript(),
            )
        },
    )
    assert ok
    assert gaps == []
    assert soft == []


def test_d2_overlay_soft_note_when_criteria_omitted_with_tsx():
    ok, gaps, soft = check_delegate_completion(
        None, {"a": _run(files=["src/App.tsx"])}
    )
    assert ok
    assert gaps == []
    assert soft
    assert any("不阻断验收" in g and "验证" in g for g in soft)


def test_graph_consistent_missing_import_gap():
    from agentcore.runtime.delegate.completion import CompletionCriteria

    criteria = CompletionCriteria(kind="graph_consistent")
    file_map = {
        "src/App.vue": "import Home from './views/Home.vue'\n",
    }
    ok, gaps, _soft = check_delegate_completion(
        criteria,
        {"a": _run(files=["src/App.vue"])},
        file_map=file_map,
    )
    assert not ok
    assert any("import" in g or "缺文件" in g for g in gaps)
    assert any("Home" in g for g in gaps)


def test_graph_consistent_closed_graph_ok():
    from agentcore.runtime.delegate.completion import CompletionCriteria

    criteria = CompletionCriteria(kind="graph_consistent")
    file_map = {
        "src/App.vue": "import Home from './views/Home.vue'\n",
        "src/views/Home.vue": "<template><div>ok</div></template>\n",
    }
    ok, gaps, soft = check_delegate_completion(
        criteria,
        {
            "a": _run(files=["src/App.vue", "src/views/Home.vue"]),
        },
        file_map=file_map,
    )
    # .vue-only: no D2 soft verify; closed graph → no soft graph note either.
    assert ok
    assert gaps == []
    assert soft == []


def test_auto_graph_scan_soft_note_on_vue_landing():
    file_map = {
        "src/main.ts": "import App from './App.vue'\n",
    }
    # Has .ts → soft D2 verify note + soft graph missing App.vue; batch still ok.
    ok, gaps, soft = check_delegate_completion(
        None,
        {"a": _run(files=["src/main.ts"])},
        file_map=file_map,
    )
    assert ok
    assert gaps == []
    assert soft
    assert any("不阻断验收" in g for g in soft)
    assert any("缺文件" in g or "App.vue" in g for g in soft)
    assert any("验证" in g for g in soft)


# ── E1/E2 修码收口：怎么算修好 + code_verified 过门 ──────────────────────────


def test_parse_completion_criteria_keeps_verify_command():
    from agentcore.runtime.delegate.completion import how_fixed_text

    criteria = parse_completion_criteria(
        {"type": "code_verified", "verify_command": "pytest tests/test_app.py -q"}
    )
    assert criteria is not None
    assert criteria.kind == "code_verified"
    assert criteria.verify_command == "pytest tests/test_app.py -q"
    assert how_fixed_text(criteria) == "pytest tests/test_app.py -q"
    # aliases
    alt = parse_completion_criteria(
        {"type": "code_verified", "verify": "pnpm test", "description": "ignored-if-verify"}
    )
    assert alt is not None
    assert alt.verify_command == "pnpm test"
    desc_only = parse_completion_criteria(
        {"type": "code_verified", "description": "跑 app 的冒烟脚本 exit 0"}
    )
    assert how_fixed_text(desc_only) == "跑 app 的冒烟脚本 exit 0"


def test_default_repair_code_criteria_and_validate_how_fixed():
    from agentcore.runtime.delegate.completion import (
        default_repair_code_criteria,
        validate_repair_how_fixed,
    )

    forced = default_repair_code_criteria({"problem": "x", "verify": "pytest -q"})
    assert forced == {"type": "code_verified", "verify_command": "pytest -q"}
    bare = default_repair_code_criteria({"problem": "x"})
    assert bare == {"type": "code_verified"}

    assert (
        validate_repair_how_fixed(
            None,
            playbook="repair_code",
            playbook_args={"verify": "pytest -q"},
        )
        is None
    )
    err_pb = validate_repair_how_fixed(None, playbook="repair_code", playbook_args={})
    assert err_pb is not None
    assert "怎么算修好" in err_pb

    err_bare = validate_repair_how_fixed(
        "code_verified",
        playbook=None,
        complexity_hint="standard",
    )
    assert err_bare is not None
    assert "verify_command" in err_bare

    err_light = validate_repair_how_fixed(
        "code_verified",
        playbook=None,
        complexity_hint="light",
    )
    assert err_light is not None
    assert "light" in err_light

    assert (
        validate_repair_how_fixed(
            {"type": "code_verified", "verify_command": "npx tsc -b"},
            complexity_hint="light",
        )
        is None
    )
    # 非修码相关：files_written / 省略不拦
    assert validate_repair_how_fixed("files_written") is None
    assert validate_repair_how_fixed(None, complexity_hint="light") is None


def test_code_verified_prose_only_never_passes():
    """E2：验证员纯 prose 交卷不得过 code_verified 门（可同时有验+落盘缺口）。"""
    criteria = parse_completion_criteria(
        {"type": "code_verified", "verify_command": "pytest -q"}
    )
    ok, gaps, _soft = check_delegate_completion(
        criteria,
        {
            "verify": _run(
                transcript=[
                    # no tool calls — prose-only "pass"
                ]
            )
        },
    )
    assert not ok
    assert any("验证" in g for g in gaps)
    assert any("落盘" in g for g in gaps)
    # content-only run still gaps (验 + 落盘 dual gap)
    ok2, gaps2, _soft2 = check_delegate_completion(
        criteria,
        {
            "verify": RunState(
                phase=RunPhase.COMPLETED,
                content="测试已全部通过，可以交付。",
                files_touched=[],
                transcript=[],
            )
        },
    )
    assert not ok2
    assert any("验证" in g for g in gaps2)
    assert any("落盘" in g for g in gaps2)


def test_format_batch_acceptance_includes_how_fixed_and_no_prose():
    line = format_batch_acceptance_for_worker(
        CompletionCriteria(kind="code_verified", verify_command="pytest -q")
    )
    assert "code_verified" in line
    assert "pytest -q" in line
    assert "test_run" in line
    assert "check=command" in line
    assert "纯 prose" in line
    assert "落盘" in line
    assert "验绿" in line


def test_format_echo_includes_how_fixed():
    resolved = resolve_completion_with_source(
        {"type": "code_verified", "verify_command": "pnpm test"},
        None,
    )
    echo = format_resolved_acceptance_echo(resolved)
    assert "code_verified（显式声明）" in echo
    assert "怎么算修好：pnpm test" in echo

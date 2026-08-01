"""交付状态结构化（能力闸门与交付诚实性）：delivery_status 构建与发射单元测试。"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy, recipe_to_axes
from agentcore.runtime.delegate.delivery_status import (
    build_delivery_status,
    maybe_emit_delivery_status,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs.file_acceptance import build_file_acceptance
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import LocalBackend, Provider, ctx, local_ctx


def _plan(*specs: RunSpec) -> RunPlan:
    return RunPlan(nodes=list(specs))


def _accepted(*paths: str) -> list[dict]:
    """Stamp COMPLETED acceptance rows (new contract; no files_touched synthesis)."""
    return build_file_acceptance(list(paths), phase=RunPhase.COMPLETED)


def test_pure_prose_success_stays_silent():
    plan = _plan(RunSpec(run_id="w1", task="调研", role="研究员"))
    results = {"w1": RunState(phase=RunPhase.COMPLETED, content="综述正文")}
    assert build_delivery_status(plan, results, execution_id="e") is None


def test_files_touched_without_file_acceptance_not_synthesized():
    """No legacy acceptance: files_touched alone must not invent delivered_files."""
    plan = _plan(RunSpec(run_id="w1", task="写讲稿", role="撰写"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["讲稿.md", "notes/大纲.md"],
        )
    }
    assert build_delivery_status(plan, results, execution_id="e-no-acc") is None


def test_all_files_delivered_no_gaps():
    plan = _plan(RunSpec(run_id="w1", task="写讲稿", role="撰写"))
    touched = ["讲稿.md", "notes/大纲.md"]
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=touched,
            file_acceptance=_accepted(*touched),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e1")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert payload["delivered_files"] == ["讲稿.md", "notes/大纲.md"]
    assert payload["gaps"] == []
    assert payload["actions"] == []
    assert "已交付 2 个文件" in payload["summary"]


def test_partial_with_worker_gaps_and_degraded_debrief():
    # collect_worker_gaps 信号：缺产物 warning 仍 blocking；degraded 交接在已落盘时
    # 降为 notes（刀1 / 方案 A），不抬 partial。
    plan = _plan(
        RunSpec(run_id="w1", task="生成课件", role="课件工程师"),
        RunSpec(run_id="w2", task="写讲稿", role="撰写", depends_on=["w1"]),
    )
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="脚本已写",
            files_touched=["build_pptx.py"],
            file_acceptance=_accepted("build_pptx.py"),
            warnings=["声明产物 course.pptx 未在工作区找到"],
            debrief={"summary": "引擎合成", "degraded": True},
        ),
        "w2": RunState(
            phase=RunPhase.COMPLETED,
            content="讲稿",
            files_touched=["讲稿.md"],
            file_acceptance=_accepted("讲稿.md"),
        ),
    }
    payload = build_delivery_status(plan, results, execution_id="e2")
    assert payload is not None
    # 仍有「course.pptx 未找到」blocking → partial；degraded 为 warning 备注。
    assert payload["state"] == "partial"
    assert set(payload["delivered_files"]) == {"build_pptx.py", "讲稿.md"}
    descriptions = [g["description"] for g in payload["gaps"]]
    assert any("course.pptx" in d for d in descriptions)
    assert any("交接说明不够完整" in d or "降级" in d for d in descriptions)
    degraded = next(g for g in payload["gaps"] if g.get("reason") == "degraded_handoff")
    assert degraded.get("severity") == "warning"
    assert all(g["role"] == "课件工程师" for g in payload["gaps"])


def test_landed_files_with_only_degraded_handoff_are_notes_not_failed():
    """刀1 / 方案 A：strict 场景下已落盘 + 仅 degraded_handoff → notes，非 partial/blocked。"""
    plan = _plan(RunSpec(run_id="w1", task="写片段", role="分区"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["site/sections/s0.html"],
            file_acceptance=_accepted("site/sections/s0.html"),
            debrief={"summary": "薄", "degraded": True},
            delivery_gaps=[
                {
                    "description": "交接说明不够完整，系统已代为补写摘要",
                    "reason": "degraded_handoff",
                }
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-deg-ok")
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["delivered_files"] == ["site/sections/s0.html"]
    assert payload["gaps"][0]["severity"] == "warning"
    assert payload["gaps"][0]["reason"] == "degraded_handoff"
    assert "交接备注" in payload["summary"] or "已交付" in payload["summary"]
    assert all(a.get("status") != "rejected" for a in payload.get("artifacts") or [])


def test_no_landing_with_degraded_handoff_still_blocked():
    """无落盘 + degraded → 仍未交付（硬拦保留）。"""
    plan = _plan(RunSpec(run_id="w1", task="写片段", role="分区"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="只有文字",
            debrief={"summary": "薄", "degraded": True},
            delivery_gaps=[
                {
                    "description": "交接说明不够完整，系统已代为补写摘要",
                    "reason": "degraded_handoff",
                }
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-deg-fail")
    assert payload is not None
    assert payload["state"] == "blocked"
    assert payload["delivered_files"] == []
    assert any(g.get("reason") == "degraded_handoff" for g in payload["gaps"])
    assert all(g.get("severity") != "warning" for g in payload["gaps"] if g.get("reason") == "degraded_handoff")


def test_plan_cutoff_skip_suppressed_when_continue_from_ran():
    """同图 continue_from 补派已跑 → 不并排挂「计划收口时跳过」。"""
    plan = _plan(
        RunSpec(run_id="a", task="t", role="A"),
        RunSpec(
            run_id="a2",
            task="续",
            role="A续",
            continue_from_run_id="a",
        ),
    )
    results = {
        "a": RunState(phase=RunPhase.SKIPPED),
        "a2": RunState(
            phase=RunPhase.COMPLETED,
            files_touched=["out.md"],
            file_acceptance=_accepted("out.md"),
        ),
    }
    payload = build_delivery_status(plan, results, execution_id="e-skip-cover")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert not any("计划收口时跳过" in (g.get("description") or "") for g in payload["gaps"])
    assert payload["delivered_files"] == ["out.md"]


def test_plan_cutoff_skip_suppressed_when_replaces_ran():
    plan = _plan(
        RunSpec(run_id="old", task="t", role="原"),
        RunSpec(run_id="new", task="接手", role="新", replaces_run_id="old"),
    )
    results = {
        "old": RunState(phase=RunPhase.SKIPPED),
        "new": RunState(
            phase=RunPhase.COMPLETED,
            files_touched=["x.md"],
            file_acceptance=_accepted("x.md"),
        ),
    }
    payload = build_delivery_status(plan, results, execution_id="e-rep-cover")
    assert payload is not None
    assert not any("计划收口时跳过" in (g.get("description") or "") for g in payload["gaps"])


def test_blocked_with_criteria_gap_and_bind_action_on_cloud():
    # 「验收」批次级缺口 + 云端无执行环境 → bind_local_folder 行动项（复用单一真相源判定）。
    plan = _plan(RunSpec(run_id="w1", task="运行脚本生成 course.pptx", role="课件工程师"))
    results = {"w1": RunState(phase=RunPhase.COMPLETED, content="只有文字")}
    payload = build_delivery_status(
        plan,
        results,
        execution_id="e3",
        backend=ctx().backend,
        criteria_gaps=["尚无 worker 成功运行 code_execute / test_run 验证代码"],
    )
    assert payload is not None
    assert payload["state"] == "blocked"
    assert payload["delivered_files"] == []
    assert payload["gaps"][0]["role"] == "验收"
    assert payload["actions"] and payload["actions"][0]["kind"] == "bind_local_folder"
    assert "未能交付" in payload["summary"]
    assert "未完成" in payload["summary"]


def test_zero_landing_worker_and_criteria_merge_to_one_gap():
    # 同一零落盘谓词：worker 契约 + 批次 files_written → 用户面一条 files_not_landed。
    from agentcore.runtime.runs.serialize import format_file_landing_tools_slash
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="w1",
            task="生成 pptx",
            role="执行工程师",
            deliverable=Deliverable(name="pptx", form="files"),
        )
    )
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="做好了",
            delivery_gaps=[
                {
                    "description": (
                        "未把产物写入工作区：交付物须用 file_write / str_replace / "
                        "file_append 或 code_execute / file_copy 落盘，而非粘在回复正文里"
                    )
                }
            ],
        )
    }
    tools = format_file_landing_tools_slash()
    payload = build_delivery_status(
        plan,
        results,
        execution_id="e-merge",
        criteria_gaps=[f"尚无 worker 将产物写入工作区（需要 {tools} 落盘）"],
    )
    assert payload is not None
    assert payload["state"] == "blocked"
    assert len(payload["gaps"]) == 1
    gap = payload["gaps"][0]
    assert gap["role"] == "验收"
    assert gap["reason"] == "files_not_landed"
    assert "未交付" in gap["description"]
    assert "工作区没有新文件" in gap["description"]


def test_zero_landing_gap_attributes_channel_dead_from_transcript():
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
    from agentcore.runtime.engine.tool_exec import with_tool_failed_marker
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="w1",
            task="写文件",
            role="工程师",
            deliverable=Deliverable(form="files", requires_files=True),
        )
    )
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="w1",
                    function=ToolCallFunction(
                        name="file_write",
                        arguments='{"path": "a.md", "content": "x"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="w1",
            content=with_tool_failed_marker(
                "local workspace op 'write' rejected: channel dead（活性挂起）"
            ),
        ),
    ]
    results = {
        "w1": RunState(
            phase=RunPhase.FAILED,
            content="",
            error=(
                "未把产物写入工作区：写盘通道不可用（local workspace channel dead / "
                "活性挂起），落盘工具已失败——请恢复工作区通道后重试，"
                "勿改用正文粘贴冒充落盘"
            ),
            transcript=transcript,
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-dead")
    assert payload is not None
    gap = payload["gaps"][0]
    assert gap["reason"] == "files_not_landed"
    assert "写盘通道不可用" in gap["description"]
    assert "粘在回复正文" not in gap["description"]


def test_zero_landing_gap_attributes_write_failed_from_transcript():
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
    from agentcore.runtime.engine.tool_exec import with_tool_failed_marker
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="w1",
            task="复制成品",
            role="工程师",
            deliverable=Deliverable(form="files", requires_files=True),
        )
    )
    transcript = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="c1",
                    function=ToolCallFunction(
                        name="file_copy",
                        arguments='{"source": "a", "destination": "b.md"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="c1",
            content=with_tool_failed_marker("目标已存在：b.md"),
        ),
    ]
    results = {
        "w1": RunState(
            phase=RunPhase.FAILED,
            content="试过了",
            error="未把产物写入工作区：已尝试写盘但未成功落盘（工具失败）",
            transcript=transcript,
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-wfail")
    assert payload is not None
    gap = payload["gaps"][0]
    assert gap["reason"] == "files_not_landed"
    assert "已尝试写盘但未成功" in gap["description"]
    assert "而非粘在回复正文" in gap["description"] or "粘在回复正文" not in gap[
        "description"
    ]


def test_maybe_emit_sets_current_delivery_verdict():
    from agentcore.runtime.delegate.delivery_status import current_delivery_verdict

    current_delivery_verdict.set(None)
    sink = EventSink()
    plan = _plan(RunSpec(run_id="w1", task="写文件", role="工程师"))
    maybe_emit_delivery_status(
        sink,
        plan,
        {
            "w1": RunState(
                phase=RunPhase.COMPLETED,
                content="ok",
                files_touched=["a.md"],
                file_acceptance=_accepted("a.md"),
            )
        },
        execution_id="e-verdict",
    )
    verdict = current_delivery_verdict.get()
    assert verdict is not None
    assert verdict.state == "delivered"
    assert verdict.delivered_files == ("a.md",)
    assert verdict.execution_id == "e-verdict"

def test_soft_notes_only_are_notes_state_not_partial():
    plan = _plan(RunSpec(run_id="w1", task="写调研", role="调研员"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["findings.md"],
            file_acceptance=_accepted("findings.md"),
            warnings=[
                "含待核实/示例自注（2 处）：`findings.md` · 待核实 · 「示例」；"
                "`findings.md` · 示例数据 · 「估算」。"
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-notes")
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["gaps"][0]["severity"] == "warning"
    assert payload["gaps"][0]["reason"] == "unverified_note"
    assert "findings.md" in (payload["gaps"][0].get("paths") or [])
    assert "待核实备注" in payload["summary"]
    assert payload["actions"] == []


def test_overlay_soft_criteria_gaps_are_notes_not_partial():
    """D2 / auto-graph soft notes via criteria_gaps → notes, never partial/blocked."""
    plan = _plan(RunSpec(run_id="w1", task="写组件", role="前端"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["src/App.tsx"],
            file_acceptance=_accepted("src/App.tsx"),
        )
    }
    payload = build_delivery_status(
        plan,
        results,
        execution_id="e-overlay",
        criteria_gaps=[
            "提醒（不阻断验收）：已落盘 .ts/.tsx，建议补一次验证"
            "（code_execute / test_run / terminal 跑通 tsc|typecheck|test|build；"
            "启动开发服务器不算）"
        ],
    )
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["gaps"][0]["severity"] == "warning"
    assert "partial" not in payload["state"]
    assert "blocked" not in payload["state"]
    assert payload["actions"] == []


def test_artifact_dir_path_hint_only_is_notes_not_partial():
    """Accepted files + only artifact_dir path suggestion → notes (not partial)."""
    plan = _plan(RunSpec(run_id="w1", task="调研 Miro 落盘", role="竞品分析师"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["miro-research.md"],
            file_acceptance=_accepted("miro-research.md"),
            delivery_gaps=[
                {
                    "description": (
                        "产物未写入案卷目录 `docs/research/`"
                        "（建议落在此目录下，勿写到工作区根）"
                    ),
                    "severity": "warning",
                    "reason": "path_hint",
                }
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-adir")
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["gaps"][0]["severity"] == "warning"
    assert payload["gaps"][0]["reason"] == "path_hint"
    assert "案卷目录" in payload["gaps"][0]["description"]
    assert "路径建议" in payload["summary"]
    assert payload["delivered_files"] == ["miro-research.md"]
    assert payload["actions"] == []


def test_artifact_dir_path_hint_from_warnings_alone_is_notes():
    """Raw contract warning text (no pre-stamped severity) still soft via markers."""
    plan = _plan(RunSpec(run_id="w1", task="调研", role="研究员"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["notes.md"],
            file_acceptance=_accepted("notes.md"),
            warnings=[
                "产物未写入案卷目录 `docs/research/`（建议落在此目录下，勿写到工作区根）"
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-adir-warn")
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["gaps"][0]["severity"] == "warning"
    assert payload["gaps"][0]["reason"] == "path_hint"


def test_declared_artifact_path_mismatch_is_notes_not_partial():
    """Sibling path-reconciliation warning (declared artifacts) stays soft too."""
    plan = _plan(RunSpec(run_id="w1", task="写 README", role="文档"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["other.md"],
            file_acceptance=_accepted("other.md"),
            warnings=["声明的交付物路径未落盘：`README.md`"],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-art-path")
    assert payload is not None
    assert payload["state"] == "notes"
    assert payload["gaps"][0]["severity"] == "warning"
    assert payload["gaps"][0]["reason"] == "path_hint"

def test_partial_writing_cutoff_summary_without_continue_writing():
    plan = _plan(RunSpec(run_id="w1", task="写成篇", role="撰稿人"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            files_touched=["报告.md"],
            file_acceptance=_accepted("报告.md"),
            delivery_gaps=[
                {
                    "description": "队员因 token 预算触顶被迫收口，产出可能不完整",
                    "reason": "token_budget",
                }
            ],
            warnings=[
                "含待核实/示例自注（1 处）：`报告.md` · 待核实 · 「待补」。"
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-mix")
    assert payload is not None
    assert payload["state"] == "partial"
    assert "成篇未写完" in payload["summary"]
    assert "待核实备注" in payload["summary"]
    assert "continue_writing" not in {
        a.get("kind") for a in payload.get("actions") or []
    }


def test_no_bind_action_on_local_backend():
    plan = _plan(RunSpec(run_id="w1", task="运行脚本生成 course.pptx", role="工程师"))
    results = {"w1": RunState(phase=RunPhase.FAILED, error="超时")}
    payload = build_delivery_status(
        plan, results, execution_id="e4", backend=LocalBackend()
    )
    assert payload is not None
    assert payload["state"] == "blocked"
    assert payload["actions"] == []
    assert "失败" in payload["gaps"][0]["description"]


def test_failed_skipped_cancelled_nodes_become_gaps():
    plan = _plan(
        RunSpec(run_id="a", task="t", role="A"),
        RunSpec(run_id="b", task="t", role="B"),
        RunSpec(run_id="c", task="t", role="C"),
    )
    results = {
        "a": RunState(phase=RunPhase.FAILED, error="炸了"),
        "b": RunState(phase=RunPhase.SKIPPED),
        "c": RunState(phase=RunPhase.CANCELLED),
    }
    payload = build_delivery_status(plan, results, execution_id="e5")
    assert payload is not None
    by_role = {g["role"]: g["description"] for g in payload["gaps"]}
    assert "失败：炸了" in by_role["A"]
    assert "未执行" in by_role["B"]
    assert "取消" in by_role["C"]


def test_cancelled_node_with_completed_revision_is_not_a_gap():
    # 跑一半改方向：原 run 取消但热修修订完成 → 不算缺口；修订产物计入已交付。
    plan = _plan(RunSpec(run_id="w1", task="写页面", role="前端"))
    results = {
        "w1": RunState(phase=RunPhase.CANCELLED),
        "w1_rev1": RunState(
            phase=RunPhase.COMPLETED,
            content="重写完成",
            files_touched=["index.html"],
            file_acceptance=_accepted("index.html"),
        ),
    }
    payload = build_delivery_status(plan, results, execution_id="e6")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert payload["gaps"] == []
    assert payload["delivered_files"] == ["index.html"]


def test_maybe_emit_gates_and_emits():
    sink = EventSink()
    prose_plan = _plan(RunSpec(run_id="w1", task="调研", role="研究员"))
    maybe_emit_delivery_status(
        sink,
        prose_plan,
        {"w1": RunState(phase=RunPhase.COMPLETED, content="正文")},
        execution_id="e",
    )
    assert not any(e.type is EventType.DELIVERY_STATUS for e in sink._history)

    files_plan = _plan(RunSpec(run_id="w1", task="写文件", role="工程师"))
    maybe_emit_delivery_status(
        sink,
        files_plan,
        {
            "w1": RunState(
                phase=RunPhase.COMPLETED,
                content="ok",
                files_touched=["a.md"],
                file_acceptance=_accepted("a.md"),
            )
        },
        execution_id="e7",
    )
    events = [e for e in sink._history if e.type is EventType.DELIVERY_STATUS]
    assert len(events) == 1
    assert events[0].payload["execution_id"] == "e7"
    assert events[0].payload["state"] == "delivered"


def test_qa_deferred_budget_emits_website_verify_action():
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="qa",
            role="页面 QA",
            task="独立【整页验收】站点【GEO 官网】…",
            deliverable=Deliverable(
                name="QA",
                form="files",
                artifacts=["site/QA.md"],
                visual_critic=True,
            ),
        )
    )
    results = {
        "qa": RunState(
            phase=RunPhase.SKIPPED,
            delivery_gaps=[
                {
                    "description": "整页验收波未跑（本回合预算用尽）",
                    "reason": "qa_deferred_budget",
                }
            ],
            files_touched=[],
        )
    }
    # Need a delivered file elsewhere so state is partial (or gaps alone → blocked).
    plan.nodes.insert(
        0,
        RunSpec(run_id="s0", role="区0", task="分区"),
    )
    results["s0"] = RunState(
        phase=RunPhase.COMPLETED,
        files_touched=["site/index.html"],
        file_acceptance=_accepted("site/index.html"),
    )
    payload = build_delivery_status(plan, results, execution_id="e-qa")
    assert payload is not None
    assert payload["state"] == "partial"
    assert any(a.get("kind") == "website_verify" for a in payload["actions"])
    action = next(a for a in payload["actions"] if a["kind"] == "website_verify")
    assert "build_website_verify" in action["prompt"]
    assert "GEO 官网" in action["prompt"]
    assert "site=" in action["prompt"]


@pytest.mark.asyncio
async def test_execute_emits_delivery_status_on_criteria_unmet():
    # drive 接线（验收未满足路径）：code_verified 未被满足 → gap 消息之外，同回合发出
    # 结构化 delivery_status（状态 blocked、验收缺口）。本地后端（闸门放行）+ FULL_AUTO。
    sink = EventSink()
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=sink,
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
    assert "完成条件未满足" in result.output
    events = [e for e in sink._history if e.type is EventType.DELIVERY_STATUS]
    assert len(events) == 1
    assert events[0].payload["state"] == "blocked"
    assert events[0].payload["gaps"][0]["role"] == "验收"


def _failed_browser_transcript():
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction

    return [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="nav1",
                    type="function",
                    function=ToolCallFunction(
                        name="browser_navigate",
                        arguments='{"url":"https://example.com"}',
                    ),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="浏览器操作失败：连接超时\n<!--agentcore:tool_failed-->",
            tool_call_id="nav1",
        ),
    ]


def _failed_test_run_transcript():
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction

    return [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tr1",
                    type="function",
                    function=ToolCallFunction(name="test_run", arguments="{}"),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            content="测试未通过（退出码 1）\n- 通过：0 / 失败：2 / 错误：0\n<!--agentcore:tool_failed-->",
            tool_call_id="tr1",
        ),
    ]


def _failed_verify_tsc_transcript():
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction

    return [
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
            content="stdout:\nerror TS2304\n\n退出码：1\n<!--agentcore:tool_failed-->",
            tool_call_id="tc1",
        ),
    ]


def test_verify_failed_browser_navigate_depresses_delivered():
    """丙：COMPLETED + browser_navigate 失败 → verify_failed，不得 delivered。"""
    plan = _plan(RunSpec(run_id="w1", task="打开验收", role="质检"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已尝试打开",
            files_touched=["site/index.html"],
            file_acceptance=_accepted("site/index.html"),
            transcript=_failed_browser_transcript(),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-vf-nav")
    assert payload is not None
    assert payload["state"] == "partial"
    assert any(g.get("reason") == "verify_failed" for g in payload["gaps"])
    assert any("browser_navigate" in g["description"] for g in payload["gaps"])


def test_verify_failed_test_run_depresses_delivered():
    plan = _plan(RunSpec(run_id="w1", task="跑测", role="工程师"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="测完",
            files_touched=["src/a.ts"],
            file_acceptance=_accepted("src/a.ts"),
            transcript=_failed_test_run_transcript(),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-vf-test")
    assert payload is not None
    assert payload["state"] != "delivered"
    assert any(g.get("reason") == "verify_failed" for g in payload["gaps"])


def test_verify_failed_tsc_depresses_delivered():
    plan = _plan(RunSpec(run_id="w1", task="类型检查", role="工程师"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="tsc 过了？",
            files_touched=["src/a.ts"],
            file_acceptance=_accepted("src/a.ts"),
            transcript=_failed_verify_tsc_transcript(),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-vf-tsc")
    assert payload is not None
    assert payload["state"] != "delivered"
    assert any(g.get("reason") == "verify_failed" for g in payload["gaps"])


def test_landed_files_without_verify_failure_still_delivered():
    """无验证失败且仅落盘 → 仍可为 delivered。"""
    plan = _plan(RunSpec(run_id="w1", task="写讲稿", role="撰写"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["讲稿.md"],
            file_acceptance=_accepted("讲稿.md"),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-ok")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert payload["gaps"] == []


def test_cloud_delivered_adds_export_to_local():
    """云端 backend + delivered_files → 含 export_to_local（即使 state=delivered）。"""
    plan = _plan(RunSpec(run_id="w1", task="写 SPA", role="前端"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["app/package.json", "app/src/main.ts"],
            file_acceptance=_accepted("app/package.json", "app/src/main.ts"),
        )
    }
    payload = build_delivery_status(
        plan, results, execution_id="e-export", backend=ctx().backend
    )
    assert payload is not None
    assert payload["state"] == "delivered"
    kinds = [a["kind"] for a in payload["actions"]]
    assert "export_to_local" in kinds
    action = next(a for a in payload["actions"] if a["kind"] == "export_to_local")
    assert "云端" in action["description"]
    assert "npm" in action["description"]


def test_local_delivered_omits_export_to_local():
    plan = _plan(RunSpec(run_id="w1", task="写 SPA", role="前端"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["app/package.json"],
            file_acceptance=_accepted("app/package.json"),
        )
    }
    payload = build_delivery_status(
        plan, results, execution_id="e-local", backend=LocalBackend()
    )
    assert payload is not None
    assert payload["state"] == "delivered"
    assert "export_to_local" not in {a["kind"] for a in payload["actions"]}


def test_is_availability_status_question_narrow():
    from agentcore.runtime.delegate.delivery_status import is_availability_status_question

    assert is_availability_status_question("可以使用了吗")
    assert is_availability_status_question("能不能用")
    assert is_availability_status_question("好了吗")
    assert is_availability_status_question("完成了吗？")
    assert not is_availability_status_question("请继续补全质检面板并接好 API")
    assert not is_availability_status_question(
        "刚才做好的那个页面，你能在本地直接打开浏览器帮我验证一下能不能用吗？"
    )


def test_cite_failure_path_rejected_not_in_delivered_files():
    """Soft-COMPLETED + cite-tier path reject → artifacts rejected, not delivered_files."""
    from agentcore.runtime.runs.file_acceptance import (
        REASON_CITATIONS_UNVERIFIED,
        build_file_acceptance,
        path_rejections_from_contract_messages,
    )

    cite_msg = (
        "`paper.md`：正文出现学位论文/期刊式著录标记（[D]）但未就地绑定本回合台账 #rN——"
        "属于未核验或编造引用。"
    )
    path_rej = path_rejections_from_contract_messages([cite_msg])
    acceptance = build_file_acceptance(
        ["paper.md", "outline.md"],
        phase=RunPhase.COMPLETED,
        path_rejections=path_rej,
    )
    plan = _plan(RunSpec(run_id="w1", task="写综述", role="撰写"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["paper.md", "outline.md"],
            file_acceptance=acceptance,
            warnings=[cite_msg],
            delivery_gaps=[{"description": cite_msg, "reason": REASON_CITATIONS_UNVERIFIED}],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-cite")
    assert payload is not None
    assert payload["delivered_files"] == ["outline.md"]
    by_path = {a["path"]: a for a in payload["artifacts"]}
    assert by_path["paper.md"]["status"] == "rejected"
    assert by_path["paper.md"]["reason"] == REASON_CITATIONS_UNVERIFIED
    assert by_path["outline.md"]["status"] == "accepted"
    assert payload["state"] == "partial"


def test_failed_with_landed_files_rejected_in_artifacts():
    """FAILED but files on disk → paths rejected in artifacts, not delivered_files."""
    from agentcore.runtime.runs.file_acceptance import build_file_acceptance

    err = "`site/index.html`：交付正文含未替换占位符/硬信号"
    acceptance = build_file_acceptance(
        ["site/index.html", "site/style.css"],
        phase=RunPhase.FAILED,
        error=err,
    )
    plan = _plan(RunSpec(run_id="w1", task="建站", role="前端"))
    results = {
        "w1": RunState(
            phase=RunPhase.FAILED,
            content="半成品",
            error=err,
            files_touched=["site/index.html", "site/style.css"],
            file_acceptance=acceptance,
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-fail-land")
    assert payload is not None
    assert payload["delivered_files"] == []
    assert payload["state"] == "blocked"
    assert {a["path"] for a in payload["artifacts"]} == {
        "site/index.html",
        "site/style.css",
    }
    assert all(a["status"] == "rejected" for a in payload["artifacts"])


def test_clean_completed_artifacts_all_accepted():
    plan = _plan(RunSpec(run_id="w1", task="写讲稿", role="撰写"))
    from agentcore.runtime.runs.file_acceptance import build_file_acceptance

    touched = ["讲稿.md"]
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=touched,
            file_acceptance=build_file_acceptance(touched, phase=RunPhase.COMPLETED),
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-ok-acc")
    assert payload is not None
    assert payload["delivered_files"] == ["讲稿.md"]
    assert payload["artifacts"] == [{"path": "讲稿.md", "status": "accepted"}]


def test_phase_b_cite_fail_rejected_not_in_delivered_files():
    """阶段 B 引用不过闸 → rejected(citations_unverified)，不进 delivered_files；无 draft 行。"""
    from agentcore.runtime.runs.file_acceptance import (
        REASON_CITATIONS_UNVERIFIED,
        build_file_acceptance,
        path_rejections_from_contract_messages,
    )

    cite_msg = (
        "`AgentCore/文档/research/渠道.md`：正文用了 #r3 这些台账引用来源，但它们不在"
        "本回合成稿可引用集中（须 deep_read 或 selected；search-only / 伪造 / 越界均不可）。"
    )
    path_rej = path_rejections_from_contract_messages([cite_msg])
    acceptance = build_file_acceptance(
        ["AgentCore/文档/research/渠道.md"],
        phase=RunPhase.COMPLETED,
        path_rejections=path_rej,
    )
    # draft 不进 file_acceptance / artifacts（仅 accepted|rejected）
    assert all(a["status"] in ("accepted", "rejected") for a in acceptance)
    assert acceptance[0]["status"] == "rejected"
    assert acceptance[0]["reason"] == REASON_CITATIONS_UNVERIFIED

    plan = _plan(RunSpec(run_id="w1", task="调研渠道", role="调研员"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="草案已升 B 仍不过闸",
            files_touched=["AgentCore/文档/research/渠道.md"],
            file_acceptance=acceptance,
            warnings=[cite_msg],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-phase-b")
    assert payload is not None
    assert payload["delivered_files"] == []
    assert len(payload["artifacts"]) == 1
    assert payload["artifacts"][0]["status"] == "rejected"
    assert payload["artifacts"][0]["reason"] == REASON_CITATIONS_UNVERIFIED
    assert all(a.get("status") != "draft" for a in payload["artifacts"])


def test_two_phase_predicate_and_playbook_stamp():
    from agentcore.runtime.runs.playbooks import PLAYBOOKS
    from agentcore.runtime.runs.research_quality import is_two_phase_citation_deliverable
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace.stage_dirs import RESEARCH_PREFIX

    assert is_two_phase_citation_deliverable(
        Deliverable(citation_mode="two_phase", form="files", artifacts=["a.md"])
    )
    assert not is_two_phase_citation_deliverable(
        Deliverable(form="files", artifacts=["a.md"])
    )
    assert not is_two_phase_citation_deliverable(None)
    # 自由 delegate：声明/落盘在 research/ → 与 playbook 同口径（不扫 task 文）
    research_path = f"{RESEARCH_PREFIX}pricing_summary.md"
    assert is_two_phase_citation_deliverable(
        Deliverable(form="files", artifacts=[research_path])
    )
    assert is_two_phase_citation_deliverable(
        Deliverable(form="files"),
        landed_paths=[research_path],
    )
    # reviews/ 与 research/ 同口径进 two_phase
    from agentcore.workspace.stage_dirs import REVIEWS_PREFIX

    reviews_path = f"{REVIEWS_PREFIX}legal_review.md"
    assert is_two_phase_citation_deliverable(
        Deliverable(form="files", artifacts=[reviews_path])
    )
    assert is_two_phase_citation_deliverable(
        Deliverable(form="files"),
        landed_paths=[reviews_path],
    )
    assert not is_two_phase_citation_deliverable(
        Deliverable(
            citation_mode="immediate",
            form="files",
            artifacts=[research_path],
        )
    )
    assert not is_two_phase_citation_deliverable(
        Deliverable(
            citation_mode="immediate",
            form="files",
            artifacts=[reviews_path],
        )
    )

    tasks, errs = PLAYBOOKS["research_report"].build({"topic": "测试主题", "angles": ["甲", "乙"]})
    assert not errs
    research_tasks = [t for t in tasks if str(t.get("id", "")).startswith("research_")]
    assert research_tasks
    for t in research_tasks:
        assert t["deliverable"].get("citation_mode") == "two_phase"
    write = next(t for t in tasks if t.get("id") == "write")
    assert write["deliverable"].get("citation_mode") == "two_phase"

    ml_tasks, ml_errs = PLAYBOOKS["multi_lens_research"].build({"topic": "测试事件"})
    assert not ml_errs
    for t in ml_tasks:
        assert t["deliverable"].get("citation_mode") == "two_phase"


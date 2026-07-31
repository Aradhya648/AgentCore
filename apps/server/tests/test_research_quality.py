"""成篇质量定案：research_quality 谓词、空 handoff、审计硬门、file_delete、检索空 streak."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from agentcore.runtime.delegate.batch_shape import annotate_batch_meta
from agentcore.runtime.delegate.delivery_status import build_delivery_status
from agentcore.runtime.delegate.playbook_declaration import (
    resolve_playbook_declaration,
)
from agentcore.runtime.engine.governance import (
    maybe_inject_audit_hard_block,
    should_audit_hard_block,
)
from agentcore.runtime.loop_controller import LoopController
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.research_quality import (
    MIN_UPSTREAM_BODY_CHARS,
    deliverable_signals_long_form,
    has_landed_prose_artifact,
    plan_signals_long_form_audit,
    upstream_body_floor_satisfied,
)
from agentcore.runtime.runs.types import Deliverable, RunPhase, RunSpec, RunState
from agentcore.tools.builtin.file_ops import FileDeleteTool, FileWriteTool
from agentcore.tools.builtin.handoff import HandoffTool
from agentcore.tools.protocol import RetrievalBudgetState, ToolContext, ToolResult
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

_PROSE_BODY = "# 报告\n\n" + ("这是实质正文段落。" * 50)
_SKELETON_BODY = "# 报告\n\n## 一\n\n## 二\n\n<!-- OUTLINE -->\n"


def _ctx(tmp_path: Path, **kwargs) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="r",
        agent_id="a",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u",
        **kwargs,
    )


def test_long_form_audit_only_structured_deliverable():
    """成篇硬审计不扫自由文；只认 deliverable.min_length≥3000 等结构腿。"""
    assert not deliverable_signals_long_form({"min_length": 500})
    assert deliverable_signals_long_form({"min_length": 3000})
    assert deliverable_signals_long_form({"min_length": 5000, "name": "报告"})
    # Free-text task/role alone must not trip the audit signal.
    assert not plan_signals_long_form_audit(
        [
            {
                "role": "撰稿",
                "task": "写一篇起诉第三者立案实务研究报告，约 5000–8000 字",
                "deliverable": {"min_length": 200},
            }
        ]
    )
    assert plan_signals_long_form_audit(
        [
            {
                "role": "撰稿",
                "task": "随便写点",
                "deliverable": {"min_length": 4000},
            }
        ]
    )


def test_prose_research_intent_no_longer_a_predicate():
    """Former is_research_report_intent / word-count RE predicates removed."""
    from agentcore.runtime.runs import research_quality as rq

    assert not hasattr(rq, "is_research_report_intent")
    assert not hasattr(rq, "has_word_count_commitment")


def test_paper_parallel_merge_discipline_constant():
    from agentcore.runtime.runs.research_quality import (
        DEFAULT_RESEARCH_REPORT_ARTIFACT,
        PAPER_PARALLEL_MERGE_DISCIPLINE,
        research_report_main_artifact,
    )

    assert "单主文件" in PAPER_PARALLEL_MERGE_DISCIPLINE
    assert "合并责任" in PAPER_PARALLEL_MERGE_DISCIPLINE
    assert "建站" in PAPER_PARALLEL_MERGE_DISCIPLINE  # 明示不误伤多产物
    assert research_report_main_artifact(None) == DEFAULT_RESEARCH_REPORT_ARTIFACT
    assert research_report_main_artifact("paper/thesis.md") == "paper/thesis.md"
    assert research_report_main_artifact("\\drafts\\a.md") == "drafts/a.md"


def test_research_handwritten_ok_without_declaration():
    """调研意图手写 tasks：可不声明 playbook；不再强推 research_report / 收紧预算。"""
    name, reason, err = resolve_playbook_declaration(
        {
            "tasks": [{"role": "调研员", "task": "写实务研究报告"}],
        },
        user_message="写一篇调研报告",
    )
    assert err is None
    assert name is None
    assert reason is None


def test_resolve_optional_research_report_still_expands():
    name, reason, err = resolve_playbook_declaration(
        {
            "playbook": "research_report",
            "playbook_args": {"topic": "立案实务"},
        }
    )
    assert err is None
    assert name == "research_report"
    assert reason is None


def test_annotate_batch_meta_audit_flags():
    result = ToolResult(tool_call_id="", success=True, output="ok")
    stamped = annotate_batch_meta(
        result,
        node_count=5,
        has_deps=True,
        playbook="research_report",
        audit_hard=True,
        includes_review=True,
    )
    assert stamped.metadata["batch_playbook"] == "research_report"
    assert stamped.metadata["audit_hard"] is True
    assert stamped.metadata["batch_includes_review"] is True


def test_parallel_brief_does_not_signal_long_form_audit():
    """A 档摸底批：无 min_length 成篇信号；硬门只认 research_report / 结构字段。"""
    from agentcore.runtime.runs.playbooks import expand_playbook
    from agentcore.runtime.runs.research_quality import plan_signals_long_form_audit

    tasks, errors = expand_playbook(
        "parallel_brief",
        {"topic": "开源选型", "angles": ["兼容", "闭源风险", "生态"]},
    )
    assert errors == []
    assert plan_signals_long_form_audit(tasks) is False
    # 对照：显式成篇 min_length 才进结构硬门信号
    tasks_long = [
        {
            "id": "w",
            "role": "撰稿人",
            "task": "写报告",
            "deliverable": {"form": "files", "min_length": 4000},
        }
    ]
    assert plan_signals_long_form_audit(tasks_long) is True


def test_audit_hard_block_after_soft_nudge():
    c = LoopController()
    c.mark_post_delegate(node_count=5, has_deps=True, audit_hard=True)
    assert c.audit_hard_required is True
    assert should_audit_hard_block(c, role="captain") is False  # soft not fired
    c.mark_audit_gate_fired()
    assert should_audit_hard_block(c, role="captain") is True
    from agentcore.llm.provider.protocol import LLMMessage

    msgs: list[LLMMessage] = []
    assert maybe_inject_audit_hard_block(
        c, messages=msgs, run_id="r", round_idx=1, role="captain"
    )
    assert any("硬门" in (m.content or "") for m in msgs)
    # Second delegate satisfies.
    c.mark_post_delegate(node_count=1, has_deps=False, includes_review=True)
    assert should_audit_hard_block(c, role="captain") is False


def test_research_report_includes_review_skips_hard_block():
    c = LoopController()
    c.mark_post_delegate(
        node_count=5, has_deps=True, audit_hard=True, includes_review=True
    )
    c.mark_audit_gate_fired()
    assert should_audit_hard_block(c, role="captain") is False


@pytest.mark.asyncio
async def test_file_delete_rejects_substantial(tmp_path: Path):
    body = "成篇正文。" * 80
    (tmp_path / "report.md").write_text(body, encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "report.md"}, _ctx(tmp_path))
    assert result.success is False
    assert "拒绝删除成篇草稿" in (result.error or "")
    assert result.contract_failure is True
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == body


@pytest.mark.asyncio
async def test_file_delete_allows_tiny(tmp_path: Path):
    (tmp_path / "stub.txt").write_text("tiny", encoding="utf-8")
    result = await FileDeleteTool().execute({"path": "stub.txt"}, _ctx(tmp_path))
    assert result.success is True
    assert not (tmp_path / "stub.txt").exists()


def test_upstream_body_floor_predicate():
    # No contract floor: non-empty body OK; empty blocked unless prose landed.
    assert upstream_body_floor_satisfied(
        body_chars=1, landed_artifact_kinds={}, min_body_chars=0
    )
    assert not upstream_body_floor_satisfied(
        body_chars=0, landed_artifact_kinds={}, min_body_chars=0
    )
    # Explicit contract floor.
    assert upstream_body_floor_satisfied(
        body_chars=MIN_UPSTREAM_BODY_CHARS,
        landed_artifact_kinds={},
        min_body_chars=MIN_UPSTREAM_BODY_CHARS,
    )
    assert not upstream_body_floor_satisfied(
        body_chars=10, landed_artifact_kinds={}, min_body_chars=MIN_UPSTREAM_BODY_CHARS
    )
    assert not upstream_body_floor_satisfied(
        body_chars=0, landed_artifact_kinds={"a.md": "skeleton"}, min_body_chars=80
    )
    assert has_landed_prose_artifact({"a.md": "prose"})
    assert upstream_body_floor_satisfied(
        body_chars=0, landed_artifact_kinds={"a.md": "prose"}, min_body_chars=80
    )


@pytest.mark.asyncio
async def test_handoff_rejects_empty_body_when_required(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
        round_content_chars=10,
    )
    result = await HandoffTool().execute({"summary": "结论够长" * 10}, ctx)
    assert result.success is False
    assert "空交付不得交接" in (result.error or "")
    assert "prose" in (result.error or "")
    assert result.contract_failure is True


@pytest.mark.asyncio
async def test_handoff_allows_short_body_when_no_contract_floor(tmp_path: Path):
    """无 min_length 时：有下游只挡空交，不挡「一句话」级短正文。"""
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=0,
        round_content_chars=19,
    )
    result = await HandoffTool().execute({"summary": "Greeter 问好"}, ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_handoff_allows_empty_body_when_prose_landed(tmp_path: Path):
    """手工 stamp prose kinds（同 ctx）仍应放行；bool 豁免路径已退役。"""
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
        round_content_chars=0,
        landed_artifact_kinds={"notes.md": "prose"},
    )
    result = await HandoffTool().execute({"summary": "已落盘调研"}, ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_handoff_rejects_empty_body_when_only_skeleton_landed(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
        round_content_chars=0,
        landed_artifact_kinds={"outline.md": "skeleton"},
        has_landed_files=True,  # bool 不得单独豁免
    )
    result = await HandoffTool().execute({"summary": "骨架已落盘"}, ctx)
    assert result.success is False
    assert "空交付不得交接" in (result.error or "")


@pytest.mark.asyncio
async def test_handoff_prose_landed_survives_replace_empty_body(tmp_path: Path):
    """生产路径：多轮 replace + file_write 置位后，下一轮空 body handoff 应成功。"""
    assert len(_PROSE_BODY) >= 400
    base = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
    )
    # tool_round stamps round_content_chars; tool_exec replace()s again per call.
    write_round = replace(base, round_content_chars=12)
    write_ctx = replace(write_round)
    written = await FileWriteTool().execute(
        {"path": "miro-research.md", "content": _PROSE_BODY}, write_ctx
    )
    assert written.success is True
    assert write_ctx.landed_artifact_kinds.get("miro-research.md") == "prose"
    # Shared dict survives; bool on replace-copy does not propagate to base.
    assert base.landed_artifact_kinds.get("miro-research.md") == "prose"
    assert base.has_landed_files is False
    handoff_ctx = replace(base, round_content_chars=0)
    assert handoff_ctx.has_landed_files is False
    result = await HandoffTool().execute({"summary": "Miro 调研已落盘"}, handoff_ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_handoff_skeleton_write_after_replace_still_blocks(tmp_path: Path):
    base = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
    )
    write_ctx = replace(replace(base, round_content_chars=0))
    written = await FileWriteTool().execute(
        {"path": "outline.md", "content": _SKELETON_BODY}, write_ctx
    )
    assert written.success is True
    assert base.landed_artifact_kinds.get("outline.md") == "skeleton"
    handoff_ctx = replace(base, round_content_chars=0)
    result = await HandoffTool().execute({"summary": "提纲已落盘"}, handoff_ctx)
    assert result.success is False
    assert "空交付不得交接" in (result.error or "")
    assert "skeleton" in (result.error or "") or "骨架" in (result.error or "")


@pytest.mark.asyncio
async def test_handoff_allows_sufficient_body(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        handoff_min_body_chars=MIN_UPSTREAM_BODY_CHARS,
        round_content_chars=MIN_UPSTREAM_BODY_CHARS + 5,
    )
    result = await HandoffTool().execute({"summary": "调研要点已齐"}, ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_write_marks_landed_files(tmp_path: Path):
    ctx = _ctx(tmp_path)
    assert ctx.has_landed_files is False
    result = await FileWriteTool().execute(
        {"path": "a.md", "content": "hello"}, ctx
    )
    assert result.success is True
    assert ctx.has_landed_files is True


def test_delivery_status_no_continue_writing_action():
    """成篇未写完：标 partial + 成篇未写完摘要，不再挂 continue_writing 按钮。"""
    from agentcore.runtime.runs.file_acceptance import build_file_acceptance

    plan = RunPlan()
    plan.add(
        RunSpec(
            run_id="write",
            role="撰稿人",
            task="写成报告",
            deliverable=Deliverable(name="报告", requires_files=True),
        )
    )
    results = {
        "write": RunState(
            phase=RunPhase.COMPLETED,
            content="",
            files_touched=["report.md"],
            file_acceptance=build_file_acceptance(
                ["report.md"], phase=RunPhase.COMPLETED
            ),
            delivery_gaps=[
                {
                    "description": "队员因 token 预算触顶被迫收口，产出可能不完整",
                    "reason": "token_budget",
                }
            ],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e1")
    assert payload is not None
    assert payload["state"] == "partial"
    assert "成篇未写完" in payload["summary"]
    kinds = {a.get("kind") for a in payload.get("actions") or []}
    assert "continue_writing" not in kinds


def test_retrieval_empty_streak_helpers():
    budget = RetrievalBudgetState(limit=5)
    assert budget.note_search_empty() == 1
    assert budget.note_search_empty() == 2
    budget.note_search_hit()
    assert budget.consecutive_empty_searches == 0


def test_research_report_write_task_has_chapter_discipline():
    from agentcore.runtime.runs.playbooks import expand_playbook

    tasks, errors = expand_playbook("research_report", {"topic": "X", "angles": ["甲", "乙"]})
    assert not errors
    write = next(t for t in tasks if t["id"] == "write")
    assert "按章" in write["task"]
    assert "file_delete" in write["task"]
    assert "章边界" in write["task"]
    # 中间环案卷契约：调研 + 提纲 form=files，路径在 RESEARCH_DIR，角度名入文件名。
    from agentcore.workspace.stage_dirs import RESEARCH_DIR

    research = [t for t in tasks if t["id"].startswith("research_")]
    assert len(research) == 2
    for t, angle in zip(research, ["甲", "乙"], strict=True):
        d = t["deliverable"]
        assert d["form"] == "files"
        assert d["artifacts"] == [f"{RESEARCH_DIR}/{angle}调研报告.md"]
    outline = next(t for t in tasks if t["id"] == "outline")
    assert outline["deliverable"]["form"] == "files"
    assert outline["deliverable"]["artifacts"] == [f"{RESEARCH_DIR}/提纲.md"]

"""成篇质量定案：research_quality 谓词、空 handoff、审计硬门、file_delete、检索空 streak."""

from __future__ import annotations

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
    has_word_count_commitment,
    is_research_report_intent,
)
from agentcore.runtime.runs.types import Deliverable, RunPhase, RunSpec, RunState
from agentcore.tools.builtin.file_ops import FileDeleteTool, FileWriteTool
from agentcore.tools.builtin.handoff import HandoffTool
from agentcore.tools.protocol import RetrievalBudgetState, ToolContext, ToolResult
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(tmp_path: Path, **kwargs) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="r",
        agent_id="a",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u",
        **kwargs,
    )


def test_research_report_intent_and_word_count():
    assert is_research_report_intent("写一篇起诉第三者立案实务研究报告")
    assert has_word_count_commitment("约 5000–8000 字可直接使用")
    assert not is_research_report_intent("把超时改成 30s")


def test_research_report_intent_covers_competitor_compare_deliverable():
    """竞品对比「调研+Markdown 落盘」须命中成篇/对比意图（team_gate 硬收）。"""
    from agentcore.runtime.runs.research_quality import is_local_file_edit_intent

    competitor = (
        "调研一下 Notion、Obsidian、Logseq 三家在个人知识管理上的定位差异，"
        "整理成一份 Markdown 对比表（功能、定价、适合谁），落盘到 research/km-compare.md。"
    )
    lawsuit = (
        "写一篇关于起诉第三者如何才能立案的实务研究，婚姻家事领域，实务指南，"
        "中等篇幅 4000–6000 字，Markdown 落盘。"
    )
    readme = (
        "帮我改一下项目根目录的 README.md：在最上面加一小节「快速开始」，"
        "写三条安装命令，其余内容别动。"
    )
    assert is_research_report_intent(competitor)
    assert is_research_report_intent(lawsuit)
    assert not is_research_report_intent("今天天气怎么样，随便聊聊")
    assert not is_research_report_intent(readme)
    assert is_local_file_edit_intent(readme)
    assert not is_local_file_edit_intent(competitor)
    assert not is_local_file_edit_intent("随便聊聊")


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


@pytest.mark.asyncio
async def test_handoff_rejects_empty_body_when_required(tmp_path: Path):
    ctx = _ctx(tmp_path, handoff_requires_body=True, round_content_chars=10)
    result = await HandoffTool().execute({"summary": "结论够长" * 10}, ctx)
    assert result.success is False
    assert "空交付不得交接" in (result.error or "")
    assert result.contract_failure is True


@pytest.mark.asyncio
async def test_handoff_allows_empty_body_when_files_landed(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
        round_content_chars=0,
        has_landed_files=True,
    )
    result = await HandoffTool().execute({"summary": "已落盘提纲"}, ctx)
    assert result.success is True


@pytest.mark.asyncio
async def test_handoff_allows_sufficient_body(tmp_path: Path):
    ctx = _ctx(
        tmp_path,
        handoff_requires_body=True,
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


def test_delivery_status_continue_writing_action():
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
    kinds = {a.get("kind") for a in payload.get("actions") or []}
    assert "continue_writing" in kinds


def test_retrieval_empty_streak_helpers():
    budget = RetrievalBudgetState(limit=5)
    assert budget.note_search_empty() == 1
    assert budget.note_search_empty() == 2
    budget.note_search_hit()
    assert budget.consecutive_empty_searches == 0


def test_research_report_write_task_has_chapter_discipline():
    from agentcore.runtime.runs.playbooks import expand_playbook

    tasks, errors = expand_playbook("research_report", {"topic": "X"})
    assert not errors
    write = next(t for t in tasks if t["id"] == "write")
    assert "按章" in write["task"]
    assert "file_delete" in write["task"]
    assert "章边界" in write["task"]

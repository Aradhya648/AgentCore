"""委派编排四项增强：CEO 评审前置 / 部分并行 / handoff 写参清理 / 记忆复用。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.memory.store import FileMemoryStore, topic_path
from agentcore.runtime.delegate.ceo_review import deterministic_ceo_review, run_ceo_review
from agentcore.runtime.delegate.parallelism import (
    resolve_parallelism,
    widen_post_checkpoint_deps,
)
from agentcore.runtime.engine.write_args_clear import (
    project_cleared_write_args,
    write_args_stub,
)
from agentcore.runtime.events import plan_review_required
from agentcore.runtime.events.payloads.interaction import PlanReviewRequiredPayload
from agentcore.runtime.memory_consult_cache import (
    consulted_memory_cache,
    get_consult_cache,
    remember_consult,
    seed_consult_cache_from_window,
)
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.tools.builtin.consult_memory import ConsultMemoryTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(user_id: str = "u") -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id=user_id,
    )


def _state(summary: str, *, files: list[str] | None = None) -> RunState:
    return RunState(
        phase=RunPhase.COMPLETED,
        content=summary,
        debrief={"summary": summary, "key_points": ["要点A"], "assumptions": ["假设X"]},
        files_touched=files or [],
    )


# ── 1. CEO 评审前置 ──────────────────────────────────────────────────────────


def test_deterministic_ceo_review_shape():
    nodes = [RunSpec(run_id="r1", agent_id="r1", role="架构师", task="写规格")]
    completed = {"r1": _state("规格已落盘", files=["docs/spec.md"])}
    review = deterministic_ceo_review(nodes, completed)
    assert "规格" in review["conclusion"] or "架构师" in review["conclusion"]
    assert review["risks"]
    assert review["suggestions"]
    assert review["source"] == "deterministic"
    assert any("docs/spec.md" in s for s in review["suggestions"])


async def test_run_ceo_review_uses_llm_json():
    class _LLM:
        async def complete(self, request):  # noqa: ANN001
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "conclusion": "规格可过，缺错误处理",
                        "risks": ["无超时策略"],
                        "suggestions": ["补错误边界"],
                    },
                    ensure_ascii=False,
                )
            )

    nodes = [RunSpec(run_id="r1", agent_id="r1", role="架构师", task="写规格")]
    review = await run_ceo_review(
        nodes=nodes,
        completed={"r1": _state("done", files=["a.md"])},
        llm=_LLM(),
        model="test-model",
    )
    assert review["conclusion"] == "规格可过，缺错误处理"
    assert review["risks"] == ["无超时策略"]
    assert review["suggestions"] == ["补错误边界"]
    assert review["source"] == "llm"


def test_plan_review_required_carries_ceo_review():
    event = plan_review_required(
        checkpoint_id="cp1",
        conversation_id="c1",
        steps=[{"run_id": "r1", "role": "架构师", "summary": "ok"}],
        pending=[{"run_id": "r2", "role": "实现"}],
        ceo_review={
            "conclusion": "可过",
            "risks": ["风险"],
            "suggestions": ["建议"],
        },
    )
    assert event.payload["ceo_review"]["conclusion"] == "可过"
    PlanReviewRequiredPayload.model_validate(event.payload)


def test_plan_review_required_omits_ceo_review_when_absent():
    event = plan_review_required(
        checkpoint_id="cp1",
        conversation_id="c1",
        steps=[{"run_id": "r1", "role": "A", "summary": "x"}],
        pending=[],
    )
    assert "ceo_review" not in event.payload
    PlanReviewRequiredPayload.model_validate(event.payload)


# ── 2. 部分并行 ──────────────────────────────────────────────────────────────


def _linear_checkpoint_plan() -> RunPlan:
    """architect(cp) → core → table → power → verifier"""
    nodes = [
        RunSpec(run_id="architect", agent_id="a", role="架构", task="规格", checkpoint_after=True),
        RunSpec(run_id="core", agent_id="c", role="核心", task="引擎", depends_on=["architect"]),
        RunSpec(run_id="table", agent_id="t", role="表格", task="视图", depends_on=["core"]),
        RunSpec(run_id="power", agent_id="p", role="增强", task="能力", depends_on=["table"]),
        RunSpec(run_id="verifier", agent_id="v", role="验收", task="验收", depends_on=["power"]),
    ]
    plan = RunPlan()
    for n in nodes:
        plan.add(n)
    return plan


def test_resolve_parallelism_defaults_conservative():
    assert resolve_parallelism(None) == "conservative"
    assert resolve_parallelism("balanced") == "balanced"
    assert resolve_parallelism("aggressive") == "aggressive"
    assert resolve_parallelism("nope") == "conservative"


def test_widen_conservative_noop():
    plan = _linear_checkpoint_plan()
    assert widen_post_checkpoint_deps(plan, "conservative") == 0
    assert plan.by_id("table").depends_on == ["core"]


def test_widen_balanced_fans_middle():
    plan = _linear_checkpoint_plan()
    changed = widen_post_checkpoint_deps(plan, "balanced")
    assert changed > 0
    # C → A → {B,D} → last  ⇒ core stays on architect; table+power on core; verifier on both
    assert plan.by_id("core").depends_on == ["architect"]
    assert plan.by_id("table").depends_on == ["core"]
    assert plan.by_id("power").depends_on == ["core"]
    assert set(plan.by_id("verifier").depends_on) == {"table", "power"}


def test_widen_aggressive_fans_from_checkpoint():
    plan = _linear_checkpoint_plan()
    widen_post_checkpoint_deps(plan, "aggressive")
    assert plan.by_id("core").depends_on == ["architect"]
    assert plan.by_id("table").depends_on == ["architect"]
    assert plan.by_id("power").depends_on == ["architect"]
    assert set(plan.by_id("verifier").depends_on) == {"core", "table", "power"}


# ── 3. handoff 写参清理 ──────────────────────────────────────────────────────


def test_write_args_stub_keeps_path():
    args = json.dumps({"path": "docs/spec.md", "content": "X" * 2000}, ensure_ascii=False)
    stub = write_args_stub("file_write", args, 2000)
    data = json.loads(stub)
    assert data["path"] == "docs/spec.md"
    assert data["content"] == "[已清理]"
    assert "_cleared" in data


def test_write_args_stub_keeps_html_structure_summary():
    """清参后保留 HTML class/id 结构摘要，供后续文件对照契约（非凭记忆盲写）。"""
    from agentcore.runtime.engine.write_args_clear import structural_write_summary

    html = (
        "<!doctype html><html><body>"
        '<div id="app" class="hero shell">'
        '<button class="btn primary" id="cta">Go</button>'
        '<span class="muted">hint</span>'
        "</div></body></html>"
    )
    # Pad past min_chars so project path also exercises the stub.
    html = html + ("<!-- pad -->" * 80)
    summary = structural_write_summary("index.html", html)
    assert summary is not None
    assert "app" in summary and "cta" in summary
    assert "hero" in summary and "btn" in summary and "primary" in summary

    args = json.dumps({"path": "index.html", "content": html}, ensure_ascii=False)
    stub = write_args_stub("file_write", args, len(html))
    data = json.loads(stub)
    assert data["content"] == "[已清理]"
    assert "_structure" in data
    assert "classes=[" in data["_structure"]
    assert "hero" in data["_structure"]
    assert "primary" in data["_structure"]
    assert "ids=[" in data["_structure"]
    assert "app" in data["_structure"]
    # Full body must not leak back into the stub.
    assert html[:40] not in stub
    assert len(data["_structure"]) < 1200


def test_project_cleared_write_args_collapses_completed_writes():
    big = "正文" * 400
    call_id = "w1"
    msgs = [
        LLMMessage(role="user", content="go"),
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=ToolCallFunction(
                        name="file_write",
                        arguments=json.dumps(
                            {"path": "docs/a.md", "content": big}, ensure_ascii=False
                        ),
                    ),
                )
            ],
        ),
        LLMMessage(role="tool", content="已写入 100 字节到 docs/a.md", tool_call_id=call_id),
        LLMMessage(role="assistant", content="准备 handoff"),
    ]
    out = project_cleared_write_args(msgs, min_chars=100)
    assert out is not msgs
    args = json.loads(out[1].tool_calls[0].function.arguments)
    assert args["path"] == "docs/a.md"
    assert big not in args["content"]
    # canonical-shape: stub is stable on re-project
    out2 = project_cleared_write_args(out, min_chars=100)
    assert out2 is out or out2[1].tool_calls[0].function.arguments == (
        out[1].tool_calls[0].function.arguments
    )


def test_project_cleared_write_args_skips_pending_write():
    """No tool result yet → keep args (model may still be mid-write)."""
    call_id = "w1"
    msgs = [
        LLMMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=ToolCallFunction(
                        name="file_write",
                        arguments=json.dumps({"path": "a.md", "content": "Y" * 800}),
                    ),
                )
            ],
        )
    ]
    assert project_cleared_write_args(msgs, min_chars=100) is msgs


# ── 4. 记忆复用 ──────────────────────────────────────────────────────────────


async def test_consult_memory_reuses_turn_cache(tmp_path):
    store = FileMemoryStore(tmp_path)
    body = "## 审美\n- 简约商务\n"
    await store.save("u", topic_path("设计审美"), body)
    tool = ConsultMemoryTool(store=store)
    token = consulted_memory_cache.set({})
    try:
        first = await tool.execute({"name": "设计审美"}, _ctx())
        assert first.success and first.output == body
        assert "设计审美" in get_consult_cache()
        second = await tool.execute({"name": "设计审美"}, _ctx())
        assert second.success and second.output == body
        assert (second.display or {}).get("reused") is True
    finally:
        consulted_memory_cache.reset(token)


def test_seed_consult_cache_from_window():
    token = consulted_memory_cache.set({})
    try:
        msgs = [
            LLMMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        function=ToolCallFunction(
                            name="consult_memory",
                            arguments=json.dumps({"name": "设计审美"}),
                        ),
                    )
                ],
            ),
            LLMMessage(role="tool", content="审美正文", tool_call_id="c1"),
        ]
        assert seed_consult_cache_from_window(msgs) == 1
        assert get_consult_cache()["设计审美"] == "审美正文"
        remember_consult("其他", "x")
        assert seed_consult_cache_from_window(msgs) == 0  # already present
    finally:
        consulted_memory_cache.reset(token)

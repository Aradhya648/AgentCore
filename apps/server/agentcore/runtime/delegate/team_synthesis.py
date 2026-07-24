"""Phase 1 CEO 协调模式：多 worker 委派期间的确定性团队进展摘要。

挂在 ``drive._progress`` 旁路——不改 ReAct / delegate 阻塞语义，不调 LLM。
仅当 plan 有 ≥2 个 worker 时生成；单 worker 路径保持今日行为。

→ 见 docs/03-AI核心/编排器与CEO主Agent.md §协调模式（合成通道）
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunState

# One-line clip for a worker's output blurb (template, not LLM).
_SUMMARY_CHARS = 80


def _clip(text: str, limit: int = _SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def worker_output_blurb(state: RunState) -> str:
    """Best-effort one-line product blurb from a completed (or failed) worker."""
    if state.phase is RunPhase.FAILED:
        err = (state.error or "").strip()
        return _clip(f"失败：{err}") if err else "失败"
    if state.phase is RunPhase.CANCELLED:
        return "已停止"
    debrief = state.debrief if isinstance(state.debrief, dict) else None
    if debrief:
        summary = str(debrief.get("summary") or "").strip()
        if summary:
            return _clip(summary)
    content = (state.content or "").strip()
    if content:
        first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
        if first:
            return _clip(first)
    return "（无摘要）"


def build_team_synthesis_preview(
    plan: RunPlan,
    completed: dict[str, RunState],
    *,
    execution_id: str,
) -> dict[str, Any] | None:
    """Build a ``team_synthesis_preview`` payload, or ``None`` when the gate fails.

    Gate: ≥2 plan nodes (solo / finalize paths stay silent). Uses only the plan's
    declared workers — hot-redirect revisions are not separate roster rows.
    """
    nodes = list(plan.nodes)
    if len(nodes) < 2:
        return None

    workers: list[dict[str, Any]] = []
    done = 0
    for node in nodes:
        role = node.role or node.agent_name or node.run_id
        state = completed.get(node.run_id)
        if state is not None and state.phase is RunPhase.COMPLETED:
            status = "completed"
            done += 1
            summary = worker_output_blurb(state)
        elif state is not None and state.phase is RunPhase.FAILED:
            status = "failed"
            summary = worker_output_blurb(state)
        elif state is not None and state.phase is RunPhase.CANCELLED:
            status = "cancelled"
            summary = worker_output_blurb(state)
        else:
            status = "pending"
            summary = ""
        workers.append(
            {
                "run_id": node.run_id,
                "role": role,
                "status": status,
                "summary": summary,
            }
        )

    total = len(workers)
    # Status line: 「已完成 2/4：✅ A ✅ B ⏳ C ⏳ D」
    marks: list[str] = []
    for w in workers:
        if w["status"] == "completed":
            marks.append(f"✅ {w['role']}")
        elif w["status"] == "failed":
            marks.append(f"❌ {w['role']}")
        elif w["status"] == "cancelled":
            marks.append(f"⏹ {w['role']}")
        else:
            marks.append(f"⏳ {w['role']}")
    headline = f"已完成 {done}/{total}：{' '.join(marks)}"

    # One-line blurbs for finished workers (completed / failed / cancelled).
    blurbs = [
        f"· {w['role']}：{w['summary']}"
        for w in workers
        if w["status"] != "pending" and w["summary"]
    ]
    text = headline if not blurbs else headline + "\n" + "\n".join(blurbs)

    return {
        "execution_id": execution_id,
        "completed": done,
        "total": total,
        "headline": headline,
        "text": text,
        "workers": workers,
        "in_progress": done < total,
    }


def maybe_emit_team_synthesis_preview(
    sink: Any,
    plan: RunPlan,
    completed: dict[str, RunState],
    *,
    execution_id: str,
) -> None:
    """Emit ``team_synthesis_preview`` when the multi-worker gate passes. Never raises."""
    try:
        payload = build_team_synthesis_preview(plan, completed, execution_id=execution_id)
        if payload is None:
            return
        from agentcore.runtime.events import team_synthesis_preview

        sink.emit(team_synthesis_preview(**payload))
    except Exception:  # noqa: BLE001 — progress hook must never break redirect drain
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning(
            "delegate.team_synthesis_preview_failed",
            execution_id=execution_id,
            exc_info=True,
        )

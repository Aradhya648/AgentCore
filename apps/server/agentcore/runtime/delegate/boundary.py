"""WaveScheduler decision-boundary hook (CHECKPOINT / BIND / SCOPE)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.delegate.ceo_review import run_ceo_review
from agentcore.runtime.delegate.suspension import persist_suspension
from agentcore.runtime.events import plan_review_required
from agentcore.runtime.runs.constants import PLAN_REVIEW_SUMMARY_CHARS

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec

DelegateTool = Any

logger = get_logger(__name__)


def checkpoint_active(tool: DelegateTool) -> bool:
    """Whether structured checkpoints fire this turn (结构化挂起 2a)."""
    return bool(tool._checkpoint_enabled and tool._registry and tool._conversation_id)


def review_summary_text(
    state: Any | None,
    *,
    limit: int = PLAN_REVIEW_SUMMARY_CHARS,
) -> str:
    """Build a plan-review / boundary card excerpt for one completed run.

    Prefer handoff debrief (``summary`` + ``key_points``) so cards show scannable
    structure (e.g. outline chapters) instead of a mid-cut markdown body. Fall back
    to files_touched, then truncated ``content``.

    Engine-synthesized (``degraded``) briefs still clip raw prose — when files exist,
    prefer the file pointer / key_points and skip that clipped markdown head.
    """
    if state is None:
        return ""

    parts: list[str] = []
    files = [
        str(p).strip()
        for p in (getattr(state, "files_touched", None) or [])
        if str(p).strip()
    ]
    debrief = state.debrief if isinstance(getattr(state, "debrief", None), dict) else None
    if debrief:
        degraded = bool(debrief.get("degraded"))
        raw_points = debrief.get("key_points") or []
        if isinstance(raw_points, str):
            raw_points = [raw_points]
        points = [str(kp).strip() for kp in raw_points if str(kp).strip()]

        if degraded and files:
            # Skip engine-clipped markdown head; card should point at the product.
            for text in points:
                parts.append(f"· {text}")
            if not parts:
                parts.append("已落盘 " + ", ".join(files[:5]))
        else:
            lead = str(debrief.get("summary") or "").strip()
            if lead:
                parts.append(lead)
            for text in points:
                parts.append(f"· {text}")

    if not parts and files:
        parts.append("已落盘 " + ", ".join(files[:5]))

    if not parts:
        content = (getattr(state, "content", None) or "").strip()
        if content:
            parts.append(content)

    text = "\n".join(parts)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def review_step(node: RunSpec, completed: dict) -> dict[str, Any]:
    """One just-completed checkpoint node's review card entry."""
    state = completed.get(node.run_id)
    return {
        "run_id": node.run_id,
        "role": node.role or node.run_id,
        "summary": review_summary_text(state),
    }


def pending_preview(plan: RunPlan, completed: dict) -> list[dict[str, Any]]:
    """The downstream nodes about to run once the user proceeds."""
    return [
        {"run_id": n.run_id, "role": n.role or n.run_id}
        for n in plan.nodes
        if n.run_id not in completed
    ]


def boundary_hook(tool: DelegateTool, plan: RunPlan):
    """Build the WaveScheduler ``on_boundary`` hook for ``plan`` (受监督的波循环)."""
    from agentcore.runtime.runs import BoundaryOutcome, BoundaryReason

    async def on_boundary(reason, nodes, completed) -> BoundaryOutcome:
        if reason is BoundaryReason.BIND or reason is BoundaryReason.SCOPE:
            tool._pending_boundary = (reason, list(nodes))
            return BoundaryOutcome.YIELD
        # CHECKPOINT 结构挂起须尊重 checkpoint 闸（``checkpoint_gate_enabled ∧ approvals`` →
        # ``tool._checkpoint_enabled``，经 ``checkpoint_active``）。闸关时跳过。
        # BIND/SCOPE（上面）不受此闸约束。
        if not checkpoint_active(tool):
            return BoundaryOutcome.PROCEED
        # 挂起即收口 (②, Phase 3): plan_review 是「顶层 (depth 0) 用户监督点」。嵌套子团队
        # (depth>0) 的回合无法 durable 恢复（``can_persist_suspension`` 要求 depth==0），② 收口
        # 只在顶层成立；嵌套若在此暂停只能退到已退役的 live-park 双态。故嵌套不再为复核暂停，
        # 直接放行（顶层 CEO 仍照常 checkpoint）。
        if tool._depth != 0:
            return BoundaryOutcome.PROCEED

        # 协调态 + checkpoint_after → 事件，不是回合暂停（选项 1）：不写 TurnSuspension、
        # 不 seal journal、不发 plan_review_required 作收口。波边界只 YIELD，由 host 投递
        # BOUNDARY_YIELD；真正要用户拍板走 ask_user 软停。经典阻塞 drive（无 CoordinationSession）
        # 仍走下方 durable plan_review。
        from agentcore.runtime.coordination.session import active_coordination

        if active_coordination() is not None:
            tool._pending_boundary = (BoundaryReason.CHECKPOINT, list(nodes))
            logger.info(
                "plan_review.coord_yield",
                nodes=[n.run_id for n in nodes],
            )
            return BoundaryOutcome.YIELD

        conversation_id = tool._conversation_id
        assert conversation_id is not None  # checkpoint_active

        checkpoint_id = new_id()
        steps = [review_step(n, completed) for n in nodes]
        pending = pending_preview(plan, completed)
        # CEO 评审前置：worker handoff 后、plan_review 暂停前强制把关一轮。
        backend = getattr(tool._base_tool_context, "backend", None)
        model = None
        profile_set = getattr(tool, "_profile_set", None)
        if profile_set is not None and hasattr(profile_set, "model"):
            model = profile_set.model
        ceo_review = await run_ceo_review(
            nodes=list(nodes),
            completed=completed,
            llm=getattr(tool, "_llm", None),
            backend=backend,
            model=model,
            pending=pending,
        )
        required = plan_review_required(
            checkpoint_id=checkpoint_id,
            conversation_id=conversation_id,
            steps=steps,
            pending=pending,
            ceo_review=ceo_review,
        )
        try:
            saved = await persist_suspension(
                tool,
                checkpoint_id,
                plan,
                completed,
                steps,
                pending,
                required,
                ceo_review=ceo_review,
            )
        except Exception:
            # D11：运行态落帧失败（saver 抛错）⇒ 显式终止，不许静默放行烧钱。
            logger.exception(
                "plan_review.persist_failed",
                checkpoint_id=checkpoint_id,
            )
            raise
        if saved:
            tool._sink.emit(required)
            tool._pending_pause = True
            logger.info(
                "plan_review.finalized",
                checkpoint_id=checkpoint_id,
                ceo_review=True,
            )
            return BoundaryOutcome.YIELD
        # 配置态不可用（无 transcript 等非生产场景）⇒ 跳过挂起放行下游。
        logger.warning(
            "plan_review.persist_unavailable",
            checkpoint_id=checkpoint_id,
            reason="no_durable_frame",
        )
        return BoundaryOutcome.PROCEED

    return on_boundary

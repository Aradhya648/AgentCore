"""Structured job-plan summary for the kickoff card (开工卡)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agentcore.runtime.debate.types import DebateConfig
    from agentcore.runtime.runs.plan import RunPlan

KickoffPrimitive = Literal["delegate", "debate"]


@dataclass(frozen=True)
class KickoffSummary:
    """Fan-out-facing job plan the kickoff gate shows / persists.

    ``primitive`` discriminates card layout. ``workers`` is the delegate分工表;
    debate fills ``motion`` / ``sides`` / ``max_rounds`` / ``thorough`` instead
    (``workers`` stays empty). ``debate_arguments`` is the resume blob so
    ``recover_turn`` can re-enter ``DebateTool.execute`` after CONTINUE/ADJUST.
    """

    primitive: KickoffPrimitive
    workers: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    motion: str = ""
    form: str = ""
    sides: list[dict[str, Any]] = field(default_factory=list)
    max_rounds: int = 0
    thorough: bool = True
    debate_arguments: dict[str, Any] = field(default_factory=dict)
    # Debate kickoff only: offer「先多视角调研再辩」when this turn has zero research.
    offer_research_first: bool = False
    # Debate kickoff: elevate research-first as visual primary (zero research + courtroom triggers).
    research_first_recommended: bool = False

    def card_payload(self) -> dict[str, Any]:
        """Wire fields for ``team_preview_required`` / suspension extras."""
        out: dict[str, Any] = {
            "primitive": self.primitive,
            "workers": list(self.workers),
            "tools": list(self.tools),
            "motion": self.motion,
            "form": self.form,
            "sides": list(self.sides),
            "max_rounds": self.max_rounds,
            "thorough": self.thorough,
        }
        if self.offer_research_first:
            out["offer_research_first"] = True
        if self.research_first_recommended:
            out["research_first_recommended"] = True
        return out


def worker_rows(plan: RunPlan) -> list[dict[str, Any]]:
    """Delegate card rows: role / task excerpt / depends_on / debate flag."""
    from agentcore.runtime.runs.constants import PLAN_REVIEW_SUMMARY_CHARS

    limit = PLAN_REVIEW_SUMMARY_CHARS
    rows: list[dict[str, Any]] = []
    for n in plan.nodes:
        task = (n.task or n.objective or "").strip()
        if len(task) > limit:
            task = task[:limit] + "…"
        rows.append(
            {
                "run_id": n.run_id,
                "role": n.role or n.agent_name or n.run_id,
                "task": task,
                "depends_on": list(n.depends_on),
                "debate": bool(n.stance) or int(n.round or 0) > 0,
            }
        )
    return rows


def delegate_kickoff_summary(
    plan: RunPlan,
    *,
    tools: list[str] | None = None,
) -> KickoffSummary:
    return KickoffSummary(
        primitive="delegate",
        workers=worker_rows(plan),
        tools=list(tools or []),
    )


def debate_kickoff_summary(
    config: DebateConfig,
    *,
    arguments: dict[str, Any],
    tools: list[str] | None = None,
) -> KickoffSummary:
    sides = [
        {
            "key": s.key,
            "name": s.name,
            "stance": s.stance,
            "is_subject": bool(s.is_subject),
        }
        for s in config.sides
    ]
    return KickoffSummary(
        primitive="debate",
        tools=list(tools or []),
        motion=config.motion,
        form=config.form.value if hasattr(config.form, "value") else str(config.form),
        sides=sides,
        max_rounds=int(config.policy.max_rounds),
        thorough=bool(config.policy.thorough),
        debate_arguments=dict(arguments),
    )

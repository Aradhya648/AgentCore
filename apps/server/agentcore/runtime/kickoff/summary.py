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
    # §7.5 裁判选型（开赛卡展示；可与辩手同模）。
    moderator_model: str = ""
    moderator_origin: str = ""
    moderator_provider_id: str = ""
    same_model_debate: bool = False
    # §7.5 D：消歧候选（开赛卡展示）；缺省空，旧 journal 兼容。
    model_candidates: list[dict[str, Any]] = field(default_factory=list)

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
        if self.moderator_model:
            out["moderator_model"] = self.moderator_model
            if self.moderator_origin:
                out["moderator_origin"] = self.moderator_origin
            if self.moderator_provider_id:
                out["moderator_provider_id"] = self.moderator_provider_id
        if self.same_model_debate:
            out["same_model_debate"] = True
        if self.model_candidates:
            out["model_candidates"] = [dict(c) for c in self.model_candidates]
        return out


def worker_rows(plan: RunPlan) -> list[dict[str, Any]]:
    """Delegate card rows: role / task excerpt / depends_on / debate / write capability."""
    from agentcore.runtime.runs.constants import PLAN_REVIEW_SUMMARY_CHARS

    limit = PLAN_REVIEW_SUMMARY_CHARS
    rows: list[dict[str, Any]] = []
    for n in plan.nodes:
        task = (n.task or n.objective or "").strip()
        if len(task) > limit:
            task = task[:limit] + "…"
        form = getattr(n.deliverable, "form", None) if n.deliverable else None
        # form=prose → 仅文字；form=files / omitted → 可改文件（写工具仍装配）。
        if form == "prose":
            write_capability = "text_only"
            write_capability_label = "仅文字报告"
        else:
            write_capability = "can_write_files"
            write_capability_label = "可改文件"
        rows.append(
            {
                "run_id": n.run_id,
                "role": n.role or n.agent_name or n.run_id,
                "task": task,
                "depends_on": list(n.depends_on),
                "debate": bool(n.stance) or int(n.round or 0) > 0,
                "form": form,
                "write_capability": write_capability,
                "write_capability_label": write_capability_label,
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
    from agentcore.runtime.debate.models import side_wire_fields

    sides = [side_wire_fields(s) for s in config.sides]
    return KickoffSummary(
        primitive="debate",
        tools=list(tools or []),
        motion=config.motion,
        form=config.form.value if hasattr(config.form, "value") else str(config.form),
        sides=sides,
        max_rounds=int(config.policy.max_rounds),
        thorough=bool(config.policy.thorough),
        debate_arguments=dict(arguments),
        moderator_model=config.moderator_model or "",
        moderator_origin=config.moderator_origin or "",
        moderator_provider_id=config.moderator_provider_id or "",
        same_model_debate=bool(config.same_model_debate),
        model_candidates=list(getattr(config, "model_candidates", None) or []),
    )

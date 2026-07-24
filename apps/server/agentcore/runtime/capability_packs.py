"""Deployment-gated capability packs (能力包) layered on the platform skill registry.

``legal_vertical_enabled`` is the **listing + activation** gate: off → the legal pack
is invisible and not registered (same outward posture as before). On → the pack
appears in ``GET /v1/capabilities`` ``packs[]`` (catalog only) and its skills are
registered into every user's runtime skill registry — no per-user binding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agentcore.config import settings
from agentcore.runtime.skills import SystemSkill

LEGAL_PACK_ID = "legal"


@dataclass(frozen=True)
class CapabilityPackDef:
    """Code-defined pack metadata + the skills it contributes when the gate is on."""

    id: str
    name: str
    summary: str

    def skills(self) -> tuple[SystemSkill, ...]:
        if self.id == LEGAL_PACK_ID:
            from agentcore.runtime.legal_skills import LEGAL_SKILLS

            return LEGAL_SKILLS
        return ()


_LEGAL_PACK = CapabilityPackDef(
    id=LEGAL_PACK_ID,
    name="法律垂直",
    summary=(
        "律师作业能力包：民事答辩状作战室 + 三方视角案情研判"
        "（legal_answer_brief / legal_case_analysis）"
    ),
)


def all_pack_defs() -> tuple[CapabilityPackDef, ...]:
    """Every known pack definition (independent of deployment listing)."""
    return (_LEGAL_PACK,)


def get_pack_def(pack_id: str) -> CapabilityPackDef | None:
    for pack in all_pack_defs():
        if pack.id == pack_id:
            return pack
    return None


def is_pack_listed(pack_id: str) -> bool:
    """Whether a pack is listed (and thus active) on this deployment."""
    if pack_id == LEGAL_PACK_ID:
        return bool(settings.legal_vertical_enabled)
    return False


def listed_packs() -> list[CapabilityPackDef]:
    """Packs visible in the capability catalog on this deployment."""
    return [p for p in all_pack_defs() if is_pack_listed(p.id)]


def enabled_packs() -> frozenset[str]:
    """Pack ids registered into the runtime skill registry for every user.

    Identical to deployment-listed packs — the listing gate is also the activation
    gate (no per-user state).
    """
    return frozenset(p.id for p in listed_packs())


def pack_skills(pack_ids: Sequence[str]) -> list[SystemSkill]:
    """Flatten skills for the given pack ids (stable pack-def order)."""
    wanted = set(pack_ids)
    out: list[SystemSkill] = []
    for pack in all_pack_defs():
        if pack.id in wanted:
            out.extend(pack.skills())
    return out

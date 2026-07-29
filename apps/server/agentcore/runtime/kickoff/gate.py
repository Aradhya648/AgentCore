"""Kickoff trigger rules — single copy for delegate + debate + ask_user kickoff."""

from __future__ import annotations

import re
from typing import Any

from agentcore.core.types import PermissionAxes

# Short verbal affirmations (governance filters these out of "real user intent"
# chunks). Not used to skip kickoff — only journal ``checkpoint_resolved`` settles.
_AFFIRM_RE = re.compile(
    r"^(好的?|可以|行|没问题|同意|认可|就这样|按这个|按此|按方案|开干|继续|开始吧?|"
    r"ok|okay|yes|yep|sure|go|lgtm)[.!！。…]*$",
    re.IGNORECASE,
)


def should_preview_delegate_plan(plan: Any, *, finalize: bool) -> bool:
    """Whether the *plan half* of a delegate kickoff would show (ignores autonomy).

    Hang when ≥2 workers OR any debate-marked node. Skip single-worker + finalize
    (zero-friction solo path). Nested depth / resume / ask_user skip / full_auto
    are decided by :func:`should_kickoff` and the caller.

    When any node has ``checkpoint_after``, the plan-preview half yields — mid-batch
    outline / plan_review cards own that拍板; capability-auth half is independent.
    """
    if any(bool(getattr(n, "checkpoint_after", False)) for n in plan.nodes):
        return False
    if len(plan.nodes) >= 2:
        return True
    if any(bool(n.stance) or int(n.round or 0) > 0 for n in plan.nodes):
        return True
    if len(plan.nodes) == 1 and finalize:
        return False
    return False


# Back-compat aliases used by tests / call sites.
should_preview_plan = should_preview_delegate_plan
should_preview = should_preview_delegate_plan


def needs_capability_auth(
    *,
    local_gate: bool,
    axes: PermissionAxes,
) -> bool:
    """Whether the capability-auth half of the kickoff applies.

    - ``command=ask``: no kickoff grant → False
    - ``command=auto``: silent auto-grant → False
    - ``command=kickoff`` + local gate: True (show tools / await grant)
    """
    if not local_gate:
        return False
    return axes.honors_kickoff_grant


def should_kickoff(
    *,
    plan_preview: bool,
    local_gate: bool,
    axes: PermissionAxes,
) -> bool:
    """Whether to durable-pause for the merged kickoff card.

    ``plan_preview`` is primitive-specific (delegate: :func:`should_preview_delegate_plan`;
    debate top-level: always True). ``team_kickoff``:
    - ``skip`` — release both halves (对齐原 full_auto 跳卡)
    - ``always`` — force plan half on (仍由调用方限定「仍该挂的场景」)
    - ``rules`` — honor ``plan_preview`` soft-skip rules
    """
    if axes.skips_team_kickoff:
        return False
    effective_plan = True if axes.forces_team_kickoff else plan_preview
    if effective_plan:
        return True
    return needs_capability_auth(local_gate=local_gate, axes=axes)


def _sink_journal(tool: Any) -> list[dict[str, Any]]:
    sink = getattr(tool, "_sink", None) or getattr(tool, "sink", None)
    if sink is None:
        return []
    journal = sink.execution_journal()
    return list(journal) if journal else []


def is_short_affirmation(text: str) -> bool:
    """True for short verbal affirmations (e.g. 「好的」「认可」).

    Used by governance to filter non-intent user turns; does **not** skip kickoff.
    """
    compact = re.sub(r"\s+", "", text)
    if not compact or len(compact) > 24:
        return False
    return _AFFIRM_RE.match(compact) is not None


def user_confirmed_kickoff_decisions(tool: Any) -> bool:
    """Whether kickoff-class decisions are already settled (skip re-asking).

    Unified skip predicate for:
    - delegate / debate team-preview kickoff cards
    - ``ask_user`` with kickoff intent (开工提案卡)

    Settled only when this CEO turn's journal already has ``checkpoint_resolved``
    (blocking ask settled). Verbal affirmation alone does not skip kickoff.
    """
    journal = _sink_journal(tool)
    return any(e.get("type") == "checkpoint_resolved" for e in journal)


def skip_after_confirmed_ask(tool: Any) -> bool:
    """Skip kickoff when user already settled kickoff-class decisions.

    See :func:`user_confirmed_kickoff_decisions` (journal ``checkpoint_resolved`` only).
    """
    return user_confirmed_kickoff_decisions(tool)

"""Kickoff trigger rules — single copy for delegate + debate + ask_user kickoff."""

from __future__ import annotations

import re
from typing import Any

from agentcore.core.types import PermissionAxes

# Short verbal affirmations that settle a previously proposed kickoff / plan
# (covers「认可」「就这样」after a free-text collaboration outline — not only card resume).
_AFFIRM_RE = re.compile(
    r"^(好的?|可以|行|没问题|同意|认可|就这样|按这个|按此|按方案|开干|继续|开始吧?|"
    r"ok|okay|yes|yep|sure|go|lgtm)[.!！。…]*$",
    re.IGNORECASE,
)

# Assistant already laid out a team / collaboration plan worth treating as settled
# once the user affirms (or when a kickoff card already resolved).
_PLAN_MARKERS = ("协作", "团队", "分工", "委派", "delegate")
_PLAN_SHAPE_MARKERS = ("方案", "worker", "调研", "队员", "拓扑", "扇出", "并行")


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


def _tool_user_text(tool: Any) -> str:
    return str(
        getattr(tool, "user_message", None) or getattr(tool, "_user_message", None) or ""
    ).strip()


def _tool_history(tool: Any) -> list[Any]:
    history = getattr(tool, "_history", None)
    if history is None:
        history = getattr(tool, "history", None)
    if history is not None:
        return list(history)
    return []


def _message_text(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content") or "").strip()
    return str(getattr(msg, "content", None) or "").strip()


def _message_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or "")
    return str(getattr(msg, "role", None) or "")


def _history_has_plan_outline(history: list[Any]) -> bool:
    """True when a prior assistant turn already proposed a collaboration / team plan."""
    for msg in history:
        if _message_role(msg) != "assistant":
            continue
        text = _message_text(msg)
        if not text:
            continue
        if any(m in text for m in _PLAN_MARKERS) and any(
            m in text for m in _PLAN_SHAPE_MARKERS
        ):
            return True
    return False


def is_short_affirmation(text: str) -> bool:
    """True for short verbal affirmations that settle a prior plan / kickoff."""
    compact = re.sub(r"\s+", "", text)
    if not compact or len(compact) > 24:
        return False
    return _AFFIRM_RE.match(compact) is not None


def user_confirmed_kickoff_decisions(tool: Any) -> bool:
    """Whether kickoff-class decisions are already settled (skip re-asking).

    Unified skip predicate for:
    - delegate / debate team-preview kickoff cards
    - ``ask_user`` with kickoff intent (开工提案卡)

    Settled when any of:
    1. This CEO turn's journal already has ``checkpoint_resolved`` (blocking ask settled)
    2. Latest user text is a short verbal affirmation **and** history already contains
       a collaboration / team plan outline (covers「认可」after free-text plan, not only
       same-turn card resume)
    """
    journal = _sink_journal(tool)
    if any(e.get("type") == "checkpoint_resolved" for e in journal):
        return True

    user_text = _tool_user_text(tool)
    return bool(
        user_text
        and is_short_affirmation(user_text)
        and _history_has_plan_outline(_tool_history(tool))
    )


def skip_after_confirmed_ask(tool: Any) -> bool:
    """Skip kickoff when user already settled kickoff-class decisions.

    Extends the original same-turn ``checkpoint_resolved`` skip to also cover
    prior-turn verbal confirmation of an already-proposed collaboration plan.
    See :func:`user_confirmed_kickoff_decisions`.
    """
    return user_confirmed_kickoff_decisions(tool)

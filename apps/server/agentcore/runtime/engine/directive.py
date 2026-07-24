"""LoopDirective: the sealed set of next-step decisions for the ReAct loop.

Governance returns exactly one of these per round; the loop is a thin ``match``
executor over them. This replaces the prior ad-hoc control flow — a stringly-typed
``NoToolRoundAction.kind``, a ``terminal`` sentinel, a ``LoopExit | None``, and the
``Intervention`` enum leaking into the loop — so every way a round can end / continue
is ONE typed, exhaustive vocabulary — new terminal paths become new variants +
handlers, not another out-param threaded through the loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentcore.runtime.events import FinishReason


@dataclass(frozen=True)
class Continue:
    """Advance to the next round (any steer for this round was already injected)."""


@dataclass(frozen=True)
class Rework:
    """finish_guard rejected the answer: discard it, inject the steer, re-run the round."""


@dataclass(frozen=True)
class Finalize:
    """Force one tool-free round to guarantee a textual answer, then end the turn.

    ``reason`` labels the trigger (logs + the finalize instruction); ``finish_reason``
    (when set) is stamped on the turn via the caller's ``finish_override_sink``.
    """

    reason: str
    finish_reason: FinishReason | None = None


@dataclass(frozen=True)
class Return:
    """End the turn now with the accumulated content (no forced extra round).

    ``extra_content`` is appended to the accumulated content (a terminal tool's
    handoff text); ``finish_reason`` (when set) is stamped via ``finish_override_sink``
    (e.g. DEGRADED). A clean model answer is ``Return()`` with neither field set.
    """

    finish_reason: FinishReason | None = None
    extra_content: str = ""


LoopDirective = Continue | Rework | Finalize | Return

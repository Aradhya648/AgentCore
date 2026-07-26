"""User checkpoint coordination — the CEO pausing a turn to ask the user.

The ask_user checkpoint's typed result, settled over the unified interaction
bridge (``runtime/interaction.py``), alongside tool approvals
(``runtime/approvals.py``) and local-workspace ops (``workspace/channel.py``). A
GRANTABLE tool approval carries a one-shot *decision*; a checkpoint carries the
user's answer to a question the CEO raised mid-turn (continue / adjust / stop).

Unlike approvals and ops (pure transport), a checkpoint's question + answer are
journaled to the turn_journal table (see ``events._JOURNAL_EVENT_TYPES``) and
projected into the assistant message's runs payload, so a reload replays the
exchange inline — it is part of the conversation, not just gating.

State is in-process (single-worker posture, same as the approval gate); front
with Redis to scale to multiple workers (see ``config.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

AskCheckpointIntent = Literal[
    "kickoff", "decision", "proposal_pick", "risk_ack", "organize_plan"
]


class CheckpointDecision(StrEnum):
    """How the user (or a timeout / orphan) settled a checkpoint the CEO raised.

    ``CONTINUE`` / ``ADJUST`` / ``STOP`` are shared by ask_user / plan_review /
    team_preview (开工卡). On the kickoff card, ``CONTINUE`` means grant + start
    (non-empty ``note`` steers all unrun workers — former adjust semantics);
    ``PER_CALL`` means start with per-call approval (no delegation grant) — enum
    retained for historical timelines / API clients; the kickoff UI no longer
    offers it. ``PER_CALL`` is kickoff-only — ask_user / plan_review ignore it.
    ``ADJUST`` remains for debate kickoff (开赛嘱咐：note 只注入首轮焦点，
    不改 motion / sides；与 CONTINUE+note 同构) and plan_review steer,
    plus historical non-debate kickoff resolves.
    ``RESEARCH_FIRST`` is debate kickoff only: 不开赛，回灌固定文案令 CEO 立即挂
    ``multi_lens_research``（与 STOP 同构的恢复分支；非辩论开工卡须拒绝/降级）。
    """

    CONTINUE = "continue"  # proceed (kickoff: grant + start; note → steer)
    PER_CALL = "per_call"  # kickoff only (historical/API): start without a grant
    ADJUST = "adjust"  # steer with a note, then continue (kickoff: also grants)
    STOP = "stop"  # end this turn gracefully
    RESEARCH_FIRST = "research_first"  # debate kickoff only: 先多视角调研再辩
    TIMEOUT = "timeout"  # no answer within the deadline (engine-set, never user-set)
    ORPHANED = "orphaned"  # 热路失效终态（冷路检查点一般不走 orphan；枚举公共尾部对齐）


@dataclass
class CheckpointResponse:
    """The settled outcome of a checkpoint: a decision + an optional note + picks.

    ``note`` carries the user's steer for ``ADJUST``, an optional 嘱咐 on kickoff
    ``CONTINUE`` (steers unrun workers), and an optional closing remark for
    ``STOP``; it is empty for ``TIMEOUT``. ``selected`` holds the option(s) the
    user picked from the CEO's ``options`` menu — one for a single-select ask,
    several when the ask is ``multiple`` — and is a first-class part of the
    answer (no longer folded into ``note``), so ``CONTINUE`` carries the pick
    too. Empty when the ask offered no options or the user chose none.
    ``style_id`` is the structured website style pick (``s0``/``s1``/…) when the
    kickoff card offered ``style_options``. ``format_id`` is the structured
    presentation delivery pick (``f0``/``f1``/…) when the card offered
    ``format_options``.
    """

    decision: CheckpointDecision
    note: str = ""
    selected: list[str] = field(default_factory=list)
    # Structured website style pick (ask_user kickoff); empty when absent.
    style_id: str = ""
    # Structured presentation format pick (ask_user kickoff); empty when absent.
    format_id: str = ""

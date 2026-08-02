"""Conformance vector builders — debate and roundtable scenarios.

See ``vectors/__init__.py`` for the aggregated ``VECTORS`` registry.
"""

from __future__ import annotations

from collections.abc import Callable

from agentcore.runtime.events import SSEEvent

from .debate_followup import _multi_agent_debate_followup
from .debate_multibeat import _multi_agent_debate_multibeat
from .debate_pretrial import (
    _multi_agent_debate_pretrial_evidence_pack_full,
    _multi_agent_debate_pretrial_evidence_pack_partial,
    _multi_agent_debate_pretrial_fast,
    _multi_agent_debate_pretrial_no_pack,
)
from .debate_single import _multi_agent_debate
from .legacy_compat import _multi_agent_red_team_legacy_risk_severities
from .red_team import _multi_agent_red_team
from .roundtable import _multi_agent_roundtable_rounds, _multi_agent_roundtable_settled

VECTORS: dict[str, tuple[str, Callable[[], list[SSEEvent]]]] = {
    "multi_agent_debate": ("多 Agent：辩论（debate 工具）主持人→辩手 + 决策简报/叙事线双产物", _multi_agent_debate),
    "multi_agent_debate_multibeat": (
        "多 Agent：多轮对抗辩论 + 每轮质询 + 结辩（协作图 beat 列 / channel 角标契约）",
        _multi_agent_debate_multibeat,
    ),
    "multi_agent_debate_pretrial_fast": (
        "庭前取证：thorough=False 不带庭前重流程秒过（skip_reason=fast）",
        _multi_agent_debate_pretrial_fast,
    ),
    "multi_agent_debate_pretrial_no_pack": (
        "庭前取证：thorough 无 pack → skip_reason=no_pack（无舰队，进入立论）",
        _multi_agent_debate_pretrial_no_pack,
    ),
    "multi_agent_debate_pretrial_evidence_pack_full": (
        "庭前取证：Evidence Pack 完整 → skip 外证（budget=0、completeness=full）",
        _multi_agent_debate_pretrial_evidence_pack_full,
    ),
    "multi_agent_debate_pretrial_evidence_pack_partial": (
        "庭前取证：Evidence Pack 截断 → skip 外证舰队（completeness=partial）",
        _multi_agent_debate_pretrial_evidence_pack_partial,
    ),
    "multi_agent_debate_followup": ("多 Agent：辩论收场带用户追问（user_interjections verbatim 复盘）", _multi_agent_debate_followup),
    "multi_agent_roundtable_rounds": (
        "刷新重建（P2）：圆桌逐轮 debate_round_started/debate_round DURABLE → debateRounds 进行态",
        _multi_agent_roundtable_rounds,
    ),
    "multi_agent_red_team": (
        "多 Agent：红队三拍 + finding 台账 + 门决（form=red_team）",
        _multi_agent_red_team,
    ),
    "multi_agent_roundtable_settled": (
        "多 Agent：圆桌点名串行线程 + 共识/分歧地图（form=roundtable）",
        _multi_agent_roundtable_settled,
    ),
    "multi_agent_red_team_legacy": (
        "旧红队载荷降级：仅 risk_severities、无 findings/beat",
        _multi_agent_red_team_legacy_risk_severities,
    ),
}

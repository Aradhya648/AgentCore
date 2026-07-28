"""Agent / automation delivery-format confirmation ledger (dual-gate · mirror presentation).

Unique source for the user-selected ``format_id`` after ask_user resume (or a
full_auto default). Resume wire priority: explicit ``format_id`` → legitimate
``fN`` in ``selected``; prose note alone never confirms.

Keyed on conversation — delegate hard-gate reads this ledger
(:func:`resolve_delivery_confirmation`). Orthogonal to website ``style_id`` /
presentation ``format_id`` (same wire, separate ledger by kickoff intent).

Persistence (与挂起恢复同构):
- Durable fact ``automation_delivery_confirmed`` via :func:`record_turn_fact`.
- ``turn_paused.automation_delivery`` snapshot at durable pause; resume rehydrates.
- Process-local ``_LEDGER`` is a hot cache only — clear + rehydrate from journal /
  paused must still surface the confirmation.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from agentcore.runtime.facts import Fact, FactKind, current_fact_log, record_turn_fact
from agentcore.runtime.runs.presentation_format import (
    FormatConfirmation,
    resolve_format_from_resume,
)

# full_auto narrow default when CEO skips the format card.
DEFAULT_FORMAT_ID = "f_default"
DEFAULT_FORMAT_LABEL_RUNNABLE = "可运行自动化"
DEFAULT_FORMAT_LABEL_CONSOLE = "控制台原型"
DEFAULT_FORMAT_LABEL_PLAN = "仅方案"

DeliveryKind = Literal["runnable", "console", "plan"]

# Canonical delivery-form hints for teaching / option labels (ids still minted f0/f1…).
SUGGESTED_FORMAT_LABELS: tuple[str, ...] = (
    "可运行自动化 — 真实可调度的 Agent/工作流（有执行环境时按环境能力交付；无则如实降级）",
    "控制台原型 — 工具台 / 运营后台 UI 原型（才允许 build_toolshed）",
    "仅方案 — 方案文档 / 架构说明，不进 toolshed/website 硬锁流水线",
)

# Narrow kickoff: 做/打造/生成 + Agent|自动化|工作流|流水线，或明确多步骤代运营.
_AUTOMATION_KICKOFF_RE = re.compile(
    r"(?:"
    r"(?:做|打造|生成|搭建|构建|开发|创建|写个|写一个|帮.?我(?:做|打造|生成|搭))"
    r".{0,48}"
    r"(?:Agent|agent|自动化|工作流|流水线|workflow|pipeline|automation)"
    r"|"
    r"(?:Agent|agent|自动化|工作流|流水线|workflow|pipeline|automation)"
    r".{0,32}"
    r"(?:做|打造|生成|搭建|构建|开发)"
    r"|"
    r"(?:build|create|make|develop)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:(?:automation|automated)\s+)?"
    r"(?:agent|workflow|pipeline|automation)\b"
    r"|"
    r"(?:多步骤|多步).{0,20}代运营|"
    r"代运营.{0,20}(?:流水线|工作流|自动化|Agent|agent)|"
    r"(?:自动(?:化)?).{0,24}(?:代运营|运营流水线)"
    r")",
    re.IGNORECASE,
)

# 勿误伤：调研 / 写提示词（即便含 Agent 字样）.
_AUTOMATION_FALSE_POSITIVE_RE = re.compile(
    r"(?:"
    r"提示词|system\s*prompt|prompt\s*(?:工程|词|模板|撰写|优化|改写)|"
    r"(?:写|撰写|起草|优化|改).{0,16}(?:agent|Agent).{0,16}"
    r"(?:提示|prompt|system)|"
    r"(?:用|让|请).{0,12}(?:团队|Agent|agent).{0,24}"
    r"(?:调研|研究|分析|审查)|"
    r"(?:做|进行|开展|帮忙).{0,12}调研|"
    r"(?:调研|研究).{0,20}(?:报告|竞品|市场)"
    r")",
    re.IGNORECASE,
)

_RUNNABLE_LABEL_RE = re.compile(
    r"(?:可运行\s*自动化|真实可调度|runnable\s*automation|automation\s*agent)",
    re.IGNORECASE,
)
_CONSOLE_LABEL_RE = re.compile(
    r"(?:控制台\s*原型|工具台|运营后台|console\s*prototype|toolshed)",
    re.IGNORECASE,
)
_PLAN_LABEL_RE = re.compile(
    r"(?:仅\s*方案|方案文档|架构说明|plan\s*only|outline\s*only)",
    re.IGNORECASE,
)

_lock = threading.Lock()


@dataclass(frozen=True)
class DeliveryConfirmation:
    format_id: str
    label: str
    source: str  # "ask_user" | "full_auto_default"


# conversation_id → DeliveryConfirmation (hot cache; durable source = journal / paused)
_LEDGER: dict[str, DeliveryConfirmation] = {}


@dataclass(frozen=True, slots=True)
class AutomationDeliveryConfirmedFact:
    """Durable structured format pick for automation delivery gate rehydration."""

    format_id: str
    label: str
    source: str
    conversation_id: str = ""
    kind: ClassVar[FactKind] = FactKind.AUTOMATION_DELIVERY_CONFIRMED

    def to_fact(self, ts: str | None = None) -> Fact:
        return Fact(
            kind=self.kind.value,
            payload={
                "format_id": self.format_id,
                "label": self.label,
                "source": self.source,
                "conversation_id": self.conversation_id,
            },
            ts=ts,
        )


def is_automation_kickoff_text(*parts: str) -> bool:
    """True when kickoff framing looks like Agent / automation / workflow ask.

    Excludes research-with-team and agent-prompt writing false positives.
    Pure「做控制台/官网」without automation vocabulary does **not** match.
    """
    blob = " ".join(p for p in parts if p)
    if not blob:
        return False
    if _AUTOMATION_FALSE_POSITIVE_RE.search(blob):
        return False
    return bool(_AUTOMATION_KICKOFF_RE.search(blob))


def automation_kickoff_requires_formats_error() -> str:
    return (
        "Agent / 自动化 / 工作流开工提案卡必须提供非空 format_options"
        "（三档：可运行自动化 / 控制台原型 / 仅方案，id=f0/f1…）。"
        "请补 format_options 后重调 ask_user；选定形态会结构化记账（format_id）。"
    )


def automation_missing_delivery_error() -> str:
    return (
        "Agent / 自动化交付需要先经 ask_user 开工卡确认交付形态"
        "（非空 format_options → 用户选定 format_id 已记账）。"
        "请先开开工提案卡选形态，或在 AutonomyPolicy.full_auto 下由机制落默认形态。"
    )


def automation_toolshed_rejected_message() -> str:
    return (
        "当前记账交付形态禁止 `playbook=\"build_toolshed\"`："
        "可运行自动化请自由组队 / `build_feature`；仅方案不进 toolshed 硬锁流水线。"
        "若要做控制台原型，请先经 ask_user 重选「控制台原型」。"
    )


def automation_website_rejected_message() -> str:
    return (
        "当前记账交付形态为「仅方案」：禁止 `playbook=\"build_website\"` / "
        "`build_toolshed` 硬锁流水线。请手写 tasks 交方案文档，或经 ask_user 重选形态。"
    )


def automation_runnable_no_exec_soft_tip() -> str:
    return (
        "[能力提示] 用户已选可运行自动化，但本回合执行面有限："
        "请如实降级交付（脚本+说明 / 可本地跑的草案），勿假称已部署可调度的线上 Agent。"
    )


def classify_delivery_kind(conf: DeliveryConfirmation | None) -> DeliveryKind | None:
    """Map ledger label → runnable | console | plan (None if unknown)."""
    if conf is None:
        return None
    label = (conf.label or "").strip()
    if not label:
        return None
    if label == DEFAULT_FORMAT_LABEL_RUNNABLE or (
        _RUNNABLE_LABEL_RE.search(label) and not _CONSOLE_LABEL_RE.search(label)
    ):
        return "runnable"
    if label == DEFAULT_FORMAT_LABEL_CONSOLE or _CONSOLE_LABEL_RE.search(label):
        return "console"
    if label == DEFAULT_FORMAT_LABEL_PLAN or _PLAN_LABEL_RE.search(label):
        return "plan"
    # Default full_auto id without matched label keywords → runnable.
    if conf.format_id == DEFAULT_FORMAT_ID and conf.source == "full_auto_default":
        return "runnable"
    return None


def is_runnable_delivery(conf: DeliveryConfirmation | None) -> bool:
    return classify_delivery_kind(conf) == "runnable"


def is_console_prototype_delivery(conf: DeliveryConfirmation | None) -> bool:
    return classify_delivery_kind(conf) == "console"


def is_plan_only_delivery(conf: DeliveryConfirmation | None) -> bool:
    return classify_delivery_kind(conf) == "plan"


def format_options_look_like_automation(
    format_options: list[dict[str, Any]] | None,
) -> bool:
    """True when option labels are the Agent/自动化三档 (not pptx/marp)."""
    labels = [
        str(o.get("label") or "")
        for o in (format_options or [])
        if isinstance(o, dict)
    ]
    if not labels:
        return False
    blob = " ".join(labels)
    hits = sum(
        1
        for pat in (_RUNNABLE_LABEL_RE, _CONSOLE_LABEL_RE, _PLAN_LABEL_RE)
        if pat.search(blob)
    )
    return hits >= 2


def automation_intent_from_parts(*parts: str) -> bool:
    """Automation intent for the delegate gate (same kickoff vocabulary)."""
    return is_automation_kickoff_text(*parts)


def delivery_confirmation_to_payload(conf: DeliveryConfirmation) -> dict[str, str]:
    return {
        "format_id": conf.format_id,
        "label": conf.label,
        "source": conf.source,
    }


def delivery_confirmation_from_payload(
    payload: dict[str, Any] | None,
) -> DeliveryConfirmation | None:
    if not isinstance(payload, dict):
        return None
    fid = str(payload.get("format_id") or "").strip()
    if not fid:
        return None
    return DeliveryConfirmation(
        format_id=fid,
        label=str(payload.get("label") or "").strip() or fid,
        source=str(payload.get("source") or "").strip() or "ask_user",
    )


def delivery_from_journal_entries(
    entries: list[dict[str, Any]] | None,
) -> DeliveryConfirmation | None:
    """Fold the last ``automation_delivery_confirmed`` fact from a journal stream."""
    if not entries:
        return None
    last: DeliveryConfirmation | None = None
    kind = FactKind.AUTOMATION_DELIVERY_CONFIRMED.value
    for entry in entries:
        if (entry.get("kind") or "") != kind:
            continue
        conf = delivery_confirmation_from_payload(entry.get("payload"))
        if conf is not None:
            last = conf
    return last


def _cache_put(conversation_id: str, conf: DeliveryConfirmation) -> DeliveryConfirmation:
    with _lock:
        _LEDGER[conversation_id] = conf
    return conf


def _cache_get(conversation_id: str) -> DeliveryConfirmation | None:
    with _lock:
        return _LEDGER.get(conversation_id)


def hydrate_delivery_confirmation(
    conversation_id: str,
    conf: DeliveryConfirmation,
) -> DeliveryConfirmation:
    """Fill the hot cache only (no journal append) — used by rehydrate paths."""
    cid = (conversation_id or "").strip()
    if not cid:
        raise ValueError("conversation_id required")
    return _cache_put(cid, conf)


def rehydrate_delivery_confirmation(
    conversation_id: str | None,
    *,
    entries: list[dict[str, Any]] | None = None,
    turn_paused_delivery: dict[str, Any] | None = None,
) -> DeliveryConfirmation | None:
    """Restore memory from ``turn_paused.automation_delivery`` and/or journal facts.

    Priority: turn_paused snapshot → last ``automation_delivery_confirmed`` in ``entries``.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    conf = delivery_confirmation_from_payload(turn_paused_delivery)
    if conf is None:
        conf = delivery_from_journal_entries(entries)
    if conf is None:
        return None
    return hydrate_delivery_confirmation(cid, conf)


def record_delivery_confirmation(
    conversation_id: str,
    *,
    format_id: str,
    label: str,
    source: str,
) -> DeliveryConfirmation:
    """Overwrite the conversation's confirmed delivery and append a durable journal fact."""
    cid = (conversation_id or "").strip()
    fid = (format_id or "").strip()
    if not cid or not fid:
        raise ValueError("conversation_id and format_id required")
    conf = DeliveryConfirmation(
        format_id=fid,
        label=(label or "").strip() or fid,
        source=source,
    )
    _cache_put(cid, conf)
    record_turn_fact(
        AutomationDeliveryConfirmedFact(
            format_id=conf.format_id,
            label=conf.label,
            source=conf.source,
            conversation_id=cid,
        ).to_fact()
    )
    return conf


def get_delivery_confirmation(conversation_id: str | None) -> DeliveryConfirmation | None:
    """Hot cache, then ambient fact log (same-turn durable rehydrate without DB)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    hit = _cache_get(cid)
    if hit is not None:
        return hit
    log = current_fact_log.get()
    if log is None:
        return None
    conf = delivery_from_journal_entries(log.entries())
    if conf is None:
        return None
    return hydrate_delivery_confirmation(cid, conf)


def clear_delivery_confirmation(conversation_id: str | None) -> None:
    """Test helper — drop a conversation's hot-cache entry (journal untouched)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return
    with _lock:
        _LEDGER.pop(cid, None)


def ensure_full_auto_default_delivery(
    conversation_id: str,
) -> DeliveryConfirmation:
    """Narrow full_auto exemption: ledger 可运行自动化 if none confirmed yet."""
    existing = get_delivery_confirmation(conversation_id)
    if existing is not None:
        return existing
    return record_delivery_confirmation(
        conversation_id,
        format_id=DEFAULT_FORMAT_ID,
        label=DEFAULT_FORMAT_LABEL_RUNNABLE,
        source="full_auto_default",
    )


async def load_delivery_confirmation_from_db(
    conversation_id: str | None,
) -> DeliveryConfirmation | None:
    """Cold path: scan recent turn journals for ``automation_delivery_confirmed``."""
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    hit = _cache_get(cid)
    if hit is not None:
        return hit
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository
    except Exception:
        return None
    try:
        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            payload = await repo.find_latest_automation_delivery(conversation_id=cid)
    except Exception:
        return None
    conf = delivery_confirmation_from_payload(payload)
    if conf is None:
        return None
    return hydrate_delivery_confirmation(cid, conf)


async def resolve_delivery_confirmation(
    conversation_id: str | None,
) -> DeliveryConfirmation | None:
    """Gate helper: memory / ambient journal → else durable DB scan."""
    conf = get_delivery_confirmation(conversation_id)
    if conf is not None:
        return conf
    return await load_delivery_confirmation_from_db(conversation_id)


def snapshot_automation_delivery_for_pause(
    journal_entries: list[dict[str, Any]] | None,
    *,
    conversation_id: str | None = None,
) -> dict[str, str] | None:
    """Build ``turn_paused.automation_delivery`` from journal fact or hot cache."""
    conf = delivery_from_journal_entries(journal_entries)
    if conf is None and conversation_id:
        conf = _cache_get((conversation_id or "").strip())
    if conf is None:
        return None
    return delivery_confirmation_to_payload(conf)


def resolve_delivery_from_resume(
    format_options: list[dict[str, Any]] | None,
    *,
    format_id: str | None = None,
    selected: list[str] | None = None,
    note: str = "",
) -> DeliveryConfirmation | None:
    """Map structured resume wire onto a format_options entry (reuse presentation wire)."""
    conf: FormatConfirmation | None = resolve_format_from_resume(
        format_options,
        format_id=format_id,
        selected=selected,
        note=note,
    )
    if conf is None:
        return None
    return DeliveryConfirmation(
        format_id=conf.format_id,
        label=conf.label,
        source=conf.source,
    )

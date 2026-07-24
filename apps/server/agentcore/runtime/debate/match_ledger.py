"""对局台账（P0 对局记忆）—— 解析 / 累积 / 注入摘要。

裁判 ``judge_and_summarize`` 每轮 JSON 兼产 ``ledger_events``；主持人跨轮累积；下一轮
``round_feedback`` / ``round_draft_brief`` / 结辩材料注入摘要块。服务端内部流转，不上 wire。

→ 见设计: docs/03-AI核心/辩论编排设计.md
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agentcore.runtime.debate.moderator_common import _as_str, _clip
from agentcore.runtime.debate.types import (
    DebateSide,
    LedgerEvent,
    LedgerEventKind,
    RoundResult,
)

# 单条事件内容封顶（喂 prompt 前再裁）；与 moderator_common 截断同思路。
_EVENT_CONTENT_CLIP = 120
# 每轮最多收几条（宁缺勿滥硬顶，防裁判灌水）。
_EVENTS_PER_ROUND_LIMIT = 8
# 注入辩手的台账摘要总预算。
_LEDGER_DIGEST_CLIP = 1200
# 己方历轮论点标题一览预算。
_OWN_TITLES_CLIP = 800
_OWN_TITLES_MAX = 12

_KIND_ALIASES: dict[str, LedgerEventKind] = {
    "withdrawal": LedgerEventKind.WITHDRAWAL,
    "撤回": LedgerEventKind.WITHDRAWAL,
    "correction": LedgerEventKind.CORRECTION,
    "更正": LedgerEventKind.CORRECTION,
    "disputed_fact": LedgerEventKind.DISPUTED_FACT,
    "争议事实": LedgerEventKind.DISPUTED_FACT,
    "争议": LedgerEventKind.DISPUTED_FACT,
    "concession": LedgerEventKind.CONCESSION,
    "关键让步": LedgerEventKind.CONCESSION,
    "让步": LedgerEventKind.CONCESSION,
}

_KIND_LABELS: dict[LedgerEventKind, str] = {
    LedgerEventKind.WITHDRAWAL: "已撤回",
    LedgerEventKind.CORRECTION: "已更正",
    LedgerEventKind.DISPUTED_FACT: "争议事实",
    LedgerEventKind.CONCESSION: "关键让步",
}


def _parse_kind(raw: Any) -> LedgerEventKind | None:
    if not isinstance(raw, str):
        return None
    return _KIND_ALIASES.get(raw.strip().lower()) or _KIND_ALIASES.get(raw.strip())


def as_ledger_events(
    value: Any,
    valid_keys: set[str],
    *,
    round_no: int = 0,
    limit: int = _EVENTS_PER_ROUND_LIMIT,
) -> list[LedgerEvent]:
    """把裁判返回的 ``ledger_events`` 规整为校验过的事件列表（容错风格同 ``_as_clashes``）。

    - 非 list → []；
    - kind 未知 / content 空 → 跳过；
    - ``side`` 非空时须命中真实 side_key（争议事实允许 side 空）；
    - 整体截到 ``limit``；content 头尾裁剪。
    """
    if not isinstance(value, list):
        return []
    out: list[LedgerEvent] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _parse_kind(item.get("kind") or item.get("type") or item.get("类别"))
        if kind is None:
            continue
        content = _clip(
            _as_str(item.get("content") or item.get("text") or item.get("内容")),
            _EVENT_CONTENT_CLIP,
        )
        if not content:
            continue
        side = _as_str(item.get("side") or item.get("side_key") or item.get("方"))
        if side and side not in valid_keys:
            continue
        if kind is not LedgerEventKind.DISPUTED_FACT and not side:
            # 撤回/更正/让步必须挂当事方；争议事实可空（描述双方分歧）。
            continue
        dedupe = (kind.value, side, content)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append(
            LedgerEvent(kind=kind, side=side, content=content, round_no=round_no)
        )
        if len(out) >= limit:
            break
    return out


def accumulate_match_ledger(rounds: Sequence[RoundResult]) -> list[LedgerEvent]:
    """跨轮累积对局台账（按轮序；事件已带 ``round_no``）。"""
    out: list[LedgerEvent] = []
    for rr in rounds:
        for ev in rr.verdict.ledger_events:
            if ev.round_no:
                out.append(ev)
            else:
                out.append(
                    LedgerEvent(
                        kind=ev.kind,
                        side=ev.side,
                        content=ev.content,
                        round_no=rr.round_no,
                    )
                )
    return out


def format_match_ledger_block(
    ledger: Sequence[LedgerEvent],
    *,
    side_names: dict[str, str] | None = None,
) -> str:
    """渲染注入辩手 brief/feedback 的【对局台账】摘要块；空台账 → 空串。"""
    if not ledger:
        return ""
    names = side_names or {}
    lines: list[str] = []
    total = 0
    for ev in ledger:
        label = _KIND_LABELS.get(ev.kind, ev.kind.value)
        who = ""
        if ev.side:
            who = f"·{names.get(ev.side, ev.side)}"
        rnd = f"R{ev.round_no}" if ev.round_no else ""
        prefix = f"- [{label}{who}"
        if rnd:
            prefix += f"·{rnd}"
        prefix += "]"
        line = f"{prefix} {ev.content}"
        if total + len(line) + 1 > _LEDGER_DIGEST_CLIP and lines:
            break
        lines.append(line)
        total += len(line) + 1
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "【对局台账】（跨轮有效）已撤回的论据【禁止再引用或归因给对方】；"
        "争议事实引用时【须注明双方分歧】；关键让步【可利用、不得翻供】。\n"
        f"{body}\n"
    )


def format_own_argument_titles(
    history: Sequence[RoundResult],
    side: DebateSide,
) -> str:
    """己方历轮结构化论点的【标题级】一览（防自漂移与重复）；无则空串。

    只取 ``arguments[*].title``，不塞 body——成稿 brief 保持轻量。
    """
    lines: list[str] = []
    total = 0
    for rr in history:
        turn = next((t for t in rr.ok_turns if t.side_key == side.key), None)
        if turn is None:
            continue
        for arg in turn.arguments or []:
            if len(lines) >= _OWN_TITLES_MAX:
                break
            title = (arg.get("title") or "").strip()
            if not title:
                continue
            line = f"- 【第{rr.round_no}轮】{title}"
            if total + len(line) + 1 > _OWN_TITLES_CLIP and lines:
                break
            lines.append(line)
            total += len(line) + 1
        if len(lines) >= _OWN_TITLES_MAX or total >= _OWN_TITLES_CLIP:
            break
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "【你历轮已立论点（标题一览）】勿与下列自相矛盾或简单换措辞重复；"
        "本轮只补焦点下的新论点 / 新回应：\n"
        f"{body}\n"
    )

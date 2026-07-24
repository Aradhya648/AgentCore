"""红队 finding 台账 —— 解析 / 去重合并 / 跨轮累积 / 门决派生。

→ 见提案: docs/06-规划/红队与圆桌形态重设计提案.md §3.2、O5/O7
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agentcore.runtime.debate.types import (
    Finding,
    FindingSeverity,
    FindingStatus,
    GateDecision,
    SideTurn,
)

_SEVERITY_ALIASES = {
    "critical": FindingSeverity.CRITICAL,
    "高危": FindingSeverity.CRITICAL,
    "致命": FindingSeverity.CRITICAL,
    "major": FindingSeverity.MAJOR,
    "中危": FindingSeverity.MAJOR,
    "重要": FindingSeverity.MAJOR,
    "high": FindingSeverity.MAJOR,  # 旧按方口径降级映射
    "minor": FindingSeverity.MINOR,
    "低危": FindingSeverity.MINOR,
    "low": FindingSeverity.MINOR,
    "medium": FindingSeverity.MAJOR,
}

# 攻方发言里「### F1」或「- [critical] 指向：…」类轻量结构（坏 JSON 降级路径）。
_HEADING_FINDING_RE = re.compile(
    r"(?:^|\n)#{2,3}\s*(?:Finding|刺|风险)?\s*([Ff]?\d+)[:：.\s]+(.+?)(?=\n#{2,3}|\Z)",
    re.DOTALL,
)
_BULLET_FINDING_RE = re.compile(
    r"(?:^|\n)\s*[-*]\s*\[(critical|major|minor|高危|中危|低危|high|medium|low)\]\s*"
    r"(?:指向[:：]\s*)?(.+?)(?=\n\s*[-*]|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _norm_severity(raw: Any) -> FindingSeverity:
    token = str(raw or "").strip().lower()
    return _SEVERITY_ALIASES.get(token, FindingSeverity.MAJOR)


def findings_from_attack_turns(turns: Sequence[SideTurn], *, round_no: int) -> list[Finding]:
    """从攻击波发言启发式抽出 finding（LLM 合并前的种子；坏结构时每方一条兜底）。"""
    out: list[Finding] = []
    seq = 0
    for t in turns:
        if not t.ok or not (t.content or "").strip():
            continue
        parsed = _parse_findings_in_text(t.content, attacker_key=t.side_key, run_id=t.run_id)
        if parsed:
            for f in parsed:
                seq += 1
                f.id = f"r{round_no}-f{seq}"
                out.append(f)
            continue
        # 兜底：每方成功攻击 → 一条 major finding（指向=焦点级摘要）
        seq += 1
        claim = (t.content or "").strip().split("\n", 1)[0][:200]
        out.append(
            Finding(
                id=f"r{round_no}-f{seq}",
                severity=FindingSeverity.MAJOR,
                target=claim[:80] or t.side_name,
                attacker_key=t.side_key,
                status=FindingStatus.OPEN,
                attack_run_id=t.run_id,
                claim=claim,
            )
        )
    return out


def _parse_findings_in_text(text: str, *, attacker_key: str, run_id: str) -> list[Finding]:
    items: list[Finding] = []
    for m in _BULLET_FINDING_RE.finditer(text or ""):
        sev = _norm_severity(m.group(1))
        body = (m.group(2) or "").strip()
        if not body:
            continue
        target, _, claim = body.partition("—")
        if not claim:
            target, _, claim = body.partition(":")
        items.append(
            Finding(
                id="",  # 由调用方编号
                severity=sev,
                target=(target or body).strip()[:120],
                attacker_key=attacker_key,
                status=FindingStatus.OPEN,
                attack_run_id=run_id,
                claim=(claim or body).strip()[:500],
            )
        )
    if items:
        return items
    for m in _HEADING_FINDING_RE.finditer(text or ""):
        body = (m.group(2) or "").strip()
        if not body:
            continue
        items.append(
            Finding(
                id="",
                severity=FindingSeverity.MAJOR,
                target=body.split("\n", 1)[0][:120],
                attacker_key=attacker_key,
                status=FindingStatus.OPEN,
                attack_run_id=run_id,
                claim=body[:500],
            )
        )
    return items


def apply_merge_plan(
    seeds: Sequence[Finding],
    merge_data: dict[str, Any],
) -> list[Finding]:
    """应用主持人去重合并计划（O5：宁少合并勿误合并）。

    ``merge_data`` 形如 ``{"keep": ["r1-f1", ...], "merges": [{"into": "r1-f1", "from": ["r1-f2"]}]}``。
    坏 / 空计划 → 原样返回 seeds。
    """
    by_id = {f.id: f for f in seeds if f.id}
    if not by_id:
        return list(seeds)
    keep_raw = merge_data.get("keep")
    merges_raw = merge_data.get("merges")
    if not isinstance(keep_raw, list) and not isinstance(merges_raw, list):
        return list(seeds)

    drop: set[str] = set()
    if isinstance(merges_raw, list):
        for item in merges_raw:
            if not isinstance(item, dict):
                continue
            into = str(item.get("into") or "")
            sources = item.get("from") or item.get("sources") or []
            if into not in by_id or not isinstance(sources, list):
                continue  # 宁少合并：目标不存在则跳过
            for src in sources:
                sid = str(src)
                if sid == into or sid not in by_id:
                    continue
                drop.add(sid)
                tgt = by_id[into]
                if sid not in tgt.merged_from:
                    tgt.merged_from.append(sid)

    keep_ids = {str(x) for x in keep_raw} if isinstance(keep_raw, list) else set(by_id)
    # 被合并掉的不得再 keep
    keep_ids -= drop
    if not keep_ids:
        # 全空 keep → 退回未合并种子（防误吞）
        return list(seeds)
    return [by_id[i] for i in by_id if i in keep_ids and i not in drop]


def mark_unanswered(findings: Sequence[Finding]) -> list[Finding]:
    """O7：方案方回应拍失败 → 全部标 unanswered。"""
    out: list[Finding] = []
    for f in findings:
        out.append(
            Finding(
                id=f.id,
                severity=f.severity,
                target=f.target,
                attacker_key=f.attacker_key,
                status=FindingStatus.UNANSWERED,
                disposition=f.disposition,
                attack_run_id=f.attack_run_id,
                response_run_id=f.response_run_id,
                rebuttal_run_id=f.rebuttal_run_id,
                claim=f.claim,
                response_note=f.response_note,
                rebuttal_note=f.rebuttal_note,
                merged_from=list(f.merged_from),
            )
        )
    return out


def mark_answered(
    findings: Sequence[Finding],
    *,
    response_run_id: str,
    dispositions: dict[str, str] | None = None,
) -> list[Finding]:
    """回应拍成功：全部 → answered，可选挂 disposition。"""
    dispositions = dispositions or {}
    out: list[Finding] = []
    for f in findings:
        out.append(
            Finding(
                id=f.id,
                severity=f.severity,
                target=f.target,
                attacker_key=f.attacker_key,
                status=FindingStatus.ANSWERED,
                disposition=dispositions.get(f.id, f.disposition),
                attack_run_id=f.attack_run_id,
                response_run_id=response_run_id,
                rebuttal_run_id=f.rebuttal_run_id,
                claim=f.claim,
                response_note=f.response_note,
                rebuttal_note=f.rebuttal_note,
                merged_from=list(f.merged_from),
            )
        )
    return out


def apply_rebuttal_statuses(
    findings: Sequence[Finding],
    status_map: dict[str, str],
    *,
    rebuttal_run_ids: dict[str, str] | None = None,
) -> list[Finding]:
    """复攻拍：按 finding id 写 closed / escalated / deadlocked。"""
    rebuttal_run_ids = rebuttal_run_ids or {}
    valid = {
        FindingStatus.CLOSED.value,
        FindingStatus.ESCALATED.value,
        FindingStatus.DEADLOCKED.value,
    }
    out: list[Finding] = []
    for f in findings:
        raw = (status_map.get(f.id) or "").strip().lower()
        status = FindingStatus(raw) if raw in valid else f.status
        out.append(
            Finding(
                id=f.id,
                severity=f.severity,
                target=f.target,
                attacker_key=f.attacker_key,
                status=status,
                disposition=f.disposition,
                attack_run_id=f.attack_run_id,
                response_run_id=f.response_run_id,
                rebuttal_run_id=rebuttal_run_ids.get(f.attacker_key, f.rebuttal_run_id),
                claim=f.claim,
                response_note=f.response_note,
                rebuttal_note=f.rebuttal_note,
                merged_from=list(f.merged_from),
            )
        )
    return out


def accumulate_findings(rounds: Sequence[Any]) -> list[Finding]:
    """跨轮累积：后轮同 id 覆盖；escalated 进下一轮优先（由 agenda 消费）。"""
    by_id: dict[str, Finding] = {}
    for rr in rounds:
        for f in getattr(rr, "findings", []) or []:
            by_id[f.id] = f
    return list(by_id.values())


def open_critical_major(findings: Sequence[Finding]) -> list[Finding]:
    """未关闭的 critical/major（含 unanswered / escalated / open / answered / deadlocked）。"""
    closed = {FindingStatus.CLOSED}
    sev_ok = {FindingSeverity.CRITICAL, FindingSeverity.MAJOR}
    return [
        f
        for f in findings
        if f.severity in sev_ok and f.status not in closed
    ]


def derive_gate(findings: Sequence[Finding]) -> tuple[str, list[str]]:
    """从台账派生门决 + must_fix 清单。

    - 无未关闭 critical/major → conditional_pass
    - 有 unanswered / escalated critical → not_viable
    - 否则 needs_major_rework
    """
    open_cm = open_critical_major(findings)
    must = [f.id for f in open_cm]
    if not must:
        return GateDecision.CONDITIONAL_PASS.value, []
    if any(
        f.severity is FindingSeverity.CRITICAL
        and f.status in (FindingStatus.UNANSWERED, FindingStatus.ESCALATED, FindingStatus.OPEN)
        for f in open_cm
    ):
        return GateDecision.NOT_VIABLE.value, must
    return GateDecision.NEEDS_MAJOR_REWORK.value, must


def format_findings_block(findings: Sequence[Finding], *, include_claim: bool = True) -> str:
    """注入回应拍 / 复攻拍的 finding 清单块。"""
    if not findings:
        return "（本轮无 finding）"
    lines: list[str] = []
    for f in findings:
        sev = f.severity.value if isinstance(f.severity, FindingSeverity) else f.severity
        st = f.status.value if isinstance(f.status, FindingStatus) else f.status
        line = f"- [{f.id}] severity={sev} status={st} 指向={f.target}"
        if include_claim and f.claim:
            line += f"\n  主张：{f.claim[:300]}"
        if f.disposition:
            line += f"\n  处置：{f.disposition}"
        if f.merged_from:
            line += f"\n  合并自：{', '.join(f.merged_from)}（复攻可申诉拆分）"
        lines.append(line)
    return "\n".join(lines)

"""调研/实务成篇质量策略（通用，非法务专用通道）。

定案：大纲按章落盘 / 空检索换策略 / 空 handoff 挡写作 /
成篇审计硬门 / 论文并行拆章须单主文件合并门禁。
结局分层：``parallel_brief`` = 对齐推进（不进成篇硬门）；
``research_report`` = 成文专线（进硬门）。本模块只放纯谓词与文案常量，
供 playbook 声明、skill、检索预算、audit gate、delivery_status 复用——不新建子系统。

成篇硬审计**只认结构化成文契约**：``playbook=="research_report"``（入口另判）与
deliverable 结构字段（如 ``min_length≥3000``）。不扫 task/角色自由文猜意图；
``parallel_brief`` / 普通多角摸底**不**因多人而进硬门。

调研两阶段引用（块 2）：``citation_mode=="two_phase"``（playbook 盖戳）或
落盘/声明路径在 ``AgentCore/文档/research/`` / ``AgentCore/文档/reviews/``
→ A 检索草案不跑成稿引用闸 → 同 worker 自动升级 B 后再验；``immediate`` 显式退出；
draft 不进 ``file_acceptance`` / artifacts 主清单。

文献成文证据降档（学术综述诚实性）：``research_report`` / 同等成文综述在证据不足时
由 ``delivery_status`` 注入 ``reason=evidence_deficit`` blocking gap → state 不得
``delivered``（仅 partial/blocked）。**不**扫「综述已完成」等完成话术词；**不**套
``parallel_brief``。消费学术搜索块真源 ``evidence_gap``（见接缝常量；
``evidence_deficit`` 仍兼容）。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from agentcore.workspace.stage_dirs import (
    RESEARCH_DIR,
    RESEARCH_PREFIX,
    REVIEWS_DIR,
    REVIEWS_PREFIX,
)

# 论文/综述/长文成篇：允许并行拆章起草，但最终验收必须单一主文件（定案：
# 禁的是「并行拆章无合并门禁」，不是双文件本身；调研/代码/建站多产物不受本条约束）。
PAPER_PARALLEL_MERGE_DISCIPLINE = (
    "【论文/综述·单主文件门禁】允许并行拆章起草到临时路径，但最终交付验收必须是"
    "【同一主文件】；并行各章 brief 须写死同一目标路径 + 合并责任"
    "（末尾 merge worker，或 CEO 收口合并）。禁止各章各交各的当终稿。"
    "调研透镜 / 代码 / 建站等多产物场景不受本条约束。"
)

# 出行/报告成文：主交付永远是 .md；用户要 PDF/可分享时才 md→md_to_pdf→handoff。
MD_PDF_EXPORT_DISCIPLINE = (
    "【成文交付·MD 为主】主交付永远是 `.md`。"
    "用户要 PDF / 可分享文件时：顺序 = 成篇 `.md` → 调用 `md_to_pdf`（对主文件）→ handoff；"
    "【禁止】用多份 HTML 顶替 PDF；【禁止】把 code_execute + reportlab 当主路径做 PDF"
    "（确定性 `md_to_pdf` 才是主路径）。"
)

# research_report 默认成篇路径（可被 playbook_args.output_path 覆盖）。
DEFAULT_RESEARCH_REPORT_ARTIFACT = f"{RESEARCH_DIR}/报告.md"

# 本地改文件 / 广度摸底 / 成篇意图 / 字数承诺：用户·task 文 RE 猜意图腿已撤；
# team_gate 与成篇硬门不扫自由文分叉；选型靠提示词，硬门只认结构字段。

_REVIEW_ROLE_MARKERS = (
    "审校",
    "审计",
    "审查",
    "质检",
    "复核",
    "review",
    "audit",
)

# Playbook 显式声明上游 prose 地板时的默认值（如 repair_code 诊断员）。
# 不再作为「有下游 → 一律抬 min」的拓扑常量；交接地板只认 deliverable.min_length。
MIN_UPSTREAM_BODY_CHARS = 80

# 独立复核短报告：案 20260803-longfix-thin-review-claim-pass B——须 files_written，禁薄 handoff。
_INDEPENDENT_REVIEW_REPORT_MIN_CHARS = 80
INDEPENDENT_REVIEW_REPORT_DISCIPLINE = (
    "【复核落盘】须将带行号的短复核报告 file_write 到案卷 reviews/；"
    "逐条写清结论与证据指针（文件:行号）；"
    "禁止仅用十余字 handoff 冒充过闸；handoff 只作速览+路径。"
)

# 成篇门槛：派单时已知的 min_length（字）。≥ 此值视作成篇报告结构信号。
_LONG_FORM_MIN_LENGTH = 3_000


def is_independent_review_role(role: str) -> bool:
    """True when the role is an independent review / audit / 复核 seat."""
    r = (role or "").strip().lower()
    if not r:
        return False
    return any(m in r for m in _REVIEW_ROLE_MARKERS)


def _safe_review_artifact_label(role: str) -> str:
    s = (role or "复核").strip().replace("\\", "_").replace("/", "_").replace("..", "_")
    return (s[:40] or "复核")


def apply_independent_review_report_deliverables(plan: object) -> None:
    """Stamp files_written short-report deliverable on independent review seats.

    案 B：复核须落带行号短报告；已声明 form=files / requires_files / artifacts 的不覆盖。
    """
    nodes = getattr(plan, "nodes", None)
    if not isinstance(nodes, list):
        return
    apply_independent_review_report_deliverables_to_specs(nodes)


def apply_independent_review_report_deliverables_to_specs(specs: list) -> None:
    """Same as :func:`apply_independent_review_report_deliverables` for replan adds."""
    from dataclasses import replace

    from agentcore.runtime.runs.types import Deliverable

    for spec in specs:
        role = str(getattr(spec, "role", "") or "")
        if not is_independent_review_role(role):
            continue
        deliverable = getattr(spec, "deliverable", None)
        if deliverable is not None and (
            deliverable.requires_files
            or deliverable.form == "files"
            or bool(deliverable.artifacts)
        ):
            # Already file-shaped (code_audit etc.) — only ensure task discipline.
            task = str(getattr(spec, "task", "") or "")
            if INDEPENDENT_REVIEW_REPORT_DISCIPLINE not in task and "带行号" not in task:
                spec.task = f"{task.rstrip()}{INDEPENDENT_REVIEW_REPORT_DISCIPLINE}"
            continue
        artifact = f"{REVIEWS_DIR}/复核-{_safe_review_artifact_label(role)}.md"
        name = (
            deliverable.name.strip()
            if deliverable is not None and deliverable.name.strip()
            else "带行号复核短报告"
        )
        min_length = max(
            int(deliverable.min_length) if deliverable is not None else 0,
            _INDEPENDENT_REVIEW_REPORT_MIN_CHARS,
        )
        base = deliverable if deliverable is not None else Deliverable()
        spec.deliverable = replace(
            base,
            name=name,
            form="files",
            requires_files=True,
            artifacts=[artifact],
            min_length=min_length,
            artifact_dir=REVIEWS_DIR,
        )
        task = str(getattr(spec, "task", "") or "")
        if INDEPENDENT_REVIEW_REPORT_DISCIPLINE not in task:
            spec.task = f"{task.rstrip()}{INDEPENDENT_REVIEW_REPORT_DISCIPLINE}"


def has_landed_prose_artifact(kinds: object) -> bool:
    """True when this run already landed at least one ``prose`` artifact.

    Reads ``ToolContext.landed_artifact_kinds`` (shared mutable dict that survives
    ``dataclasses.replace``). Skeleton / empty landings do **not** count — only
    prose exempts the upstream body floor at handoff / executor completion.
    """
    if not isinstance(kinds, dict) or not kinds:
        return False
    return any(v == "prose" for v in kinds.values())


def upstream_body_floor_satisfied(
    *,
    body_chars: int,
    landed_artifact_kinds: object,
    min_body_chars: int = 0,
) -> bool:
    """Upstream floor from the same deliverable contract as ``check_contract``.

    ``min_body_chars`` = ``deliverable.min_length``（0 = 无字数地板）。已落盘 prose
    一律满足。无地板时：非空正文即视为可消费产出（拓扑仍靠
    ``handoff_requires_body`` 挡真正空交）；有地板时须 ``body ≥ min``。
    禁止再用全局 80 发明地板。
    """
    if has_landed_prose_artifact(landed_artifact_kinds):
        return True
    floor = max(0, int(min_body_chars or 0))
    n = int(body_chars or 0)
    if floor <= 0:
        return n > 0
    return n >= floor


def promote_brief_to_deliverable(
    summary: str,
    key_points: object = None,
) -> str:
    """升格交接简报为下游可读候选正文（同轮正文 0 字时的交付替身）。

    ``summary`` 为首段；非空 ``key_points`` 附作 ``- …`` 列表。空 summary → ``""``
    （不豁免空交）。handoff / 收工闸 / 依赖注入共用。
    """
    head = (summary or "").strip()
    if not head:
        return ""
    points: list[str] = []
    if isinstance(key_points, list):
        for raw in key_points:
            item = str(raw).strip()
            if item:
                points.append(item)
    elif key_points is not None:
        item = str(key_points).strip()
        if item:
            points.append(item)
    if not points:
        return head
    bullets = "\n".join(f"- {p}" for p in points)
    return f"{head}\n\n{bullets}"


def batch_includes_review_role(tasks: object) -> bool:
    """True when hand-written tasks already include an independent review role."""
    if not isinstance(tasks, list):
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        role = str(task.get("role") or "").strip()
        if is_independent_review_role(role):
            return True
    return False


def deliverable_signals_long_form(deliverable: Any) -> bool:
    """True when a deliverable dict/object signals long-form via structured fields."""
    if deliverable is None:
        return False
    if isinstance(deliverable, dict):
        min_length = int(deliverable.get("min_length") or 0)
    else:
        min_length = int(getattr(deliverable, "min_length", 0) or 0)
    return min_length >= _LONG_FORM_MIN_LENGTH


def plan_signals_long_form_audit(plan_nodes: object) -> bool:
    """True when any plan node deliverable has structured long-form signals.

    Does **not** scan free-text ``task`` / ``role`` for research/word-count intent.
    """
    if not isinstance(plan_nodes, (list, tuple)):
        return False
    for node in plan_nodes:
        deliverable = getattr(node, "deliverable", None)
        if deliverable is None and isinstance(node, dict):
            deliverable = node.get("deliverable")
        if deliverable_signals_long_form(deliverable):
            return True
    return False


def research_report_main_artifact(output_path: str | None = None) -> str:
    """Single main-file path for research_report acceptance (merge gate)."""
    cleaned = (output_path or "").strip().replace("\\", "/")
    if cleaned:
        return cleaned.lstrip("/")
    return DEFAULT_RESEARCH_REPORT_ARTIFACT


def _research_casefile_path(path: str) -> bool:
    """True when path is under research/ or reviews/ stage dirs (``stage_dirs``)."""
    p = (path or "").strip().lstrip("/")
    return (
        p in (RESEARCH_DIR, REVIEWS_DIR)
        or p.startswith(RESEARCH_PREFIX)
        or p.startswith(REVIEWS_PREFIX)
    )


def is_two_phase_citation_deliverable(
    deliverable: Any,
    *,
    landed_paths: list[str] | None = None,
) -> bool:
    """True when deliverable opts into A(draft)→B(cite-tier) citation acceptance.

    判定「调研类」（不扫 task/角色自由文）：
    - ``citation_mode=="immediate"`` → 否（显式退出）
    - ``citation_mode=="two_phase"`` → 是（playbook / CEO 盖戳）
    - 否则：声明的 ``artifacts`` / ``artifact_dir`` 或已落盘路径落在
      ``AgentCore/文档/research/`` 或 ``AgentCore/文档/reviews/`` → 是
      （自由 delegate 案卷与 playbook 同口径）
    """
    mode: str | None
    artifacts: list[str] = []
    artifact_dir = ""
    if deliverable is None:
        mode = None
    elif isinstance(deliverable, dict):
        mode = deliverable.get("citation_mode")
        raw_arts = deliverable.get("artifacts") or []
        if isinstance(raw_arts, list):
            artifacts = [str(a) for a in raw_arts if a]
        ad = deliverable.get("artifact_dir") or ""
        artifact_dir = ad if isinstance(ad, str) else ""
    else:
        mode = getattr(deliverable, "citation_mode", None)
        artifacts = [str(a) for a in (getattr(deliverable, "artifacts", None) or []) if a]
        artifact_dir = str(getattr(deliverable, "artifact_dir", "") or "")

    if mode == "immediate":
        return False
    if mode == "two_phase":
        return True

    candidates = list(artifacts)
    if artifact_dir.strip():
        candidates.append(artifact_dir.strip())
    for path in landed_paths or []:
        if path:
            candidates.append(str(path))
    return any(_research_casefile_path(p) for p in candidates)


# ── 文献成文证据降档（delivery_status 消费）────────────────────────────────

# Machine gap reason — mirrored as REASON_EVIDENCE_DEFICIT in delivery_status.
REASON_EVIDENCE_DEFICIT = "evidence_deficit"

# ── 与「学术搜索块」的稳定接缝（字段名约定；本块只读、不写搜索实现）────────
# 学术搜索块在 junk / uniformly_weak / 空注入时，应至少留下下列之一，供本模块消费：
#
# 1) RunState.delivery_gaps 行：``{"reason": "evidence_deficit", "description": "..."}``
#    （经 ``collect_worker_gaps`` 进卡；本谓词不再重复生成）
# 2) RunState 可选属性（getattr，不强制改 types 契约）：
#    - ``evidence_gap: bool``（真源；executor 可从 RetrievalBudgetState sticky 落盘）
#    - ``evidence_deficit: bool``（兼容旧戳）
#    - ``evidence_meta`` / ``search_evidence`` dict，键见下
# 3) web_search ToolResult.output JSON（进 transcript 的 tool content）或 metadata：
#    - ``evidence_gap``: bool（搜索真源）
#    - ``evidence_deficit``: bool（兼容）
#    - ``evidence_quality``: ``"poor"``（或其它非 ok）
#    - ``academic_usable_count``: int（0 = 本轮无学术可用命中）
#    - ``search_policy``: ``"academic_literature"``（或含 ``academic`` 的 policy 名；
#      旧名 ``academic_evidence`` 作别名）
#    - 既有：``low_relevance`` / ``empty`` / ``empty_streak``（有 academic policy 时计）
#
# 降档仍可由「几乎无学术可用源」与「无参考文献·靠先验」可观测缺口触发。
# 非文献形态（parallel_brief）会在 delivery_status 丢弃误入的 evidence_deficit。

EVIDENCE_GAP_KEY = "evidence_gap"
EVIDENCE_DEFICIT_KEY = "evidence_deficit"
EVIDENCE_QUALITY_KEY = "evidence_quality"
ACADEMIC_USABLE_COUNT_KEY = "academic_usable_count"
# Align with tools.builtin.web.relevance.SEARCH_POLICY_ACADEMIC_LITERATURE.
SEARCH_POLICY_ACADEMIC_LITERATURE = "academic_literature"
# Legacy alias kept for older stamps / fixtures.
SEARCH_POLICY_ACADEMIC_EVIDENCE = SEARCH_POLICY_ACADEMIC_LITERATURE
EVIDENCE_QUALITY_POOR = "poor"

# 有检索痕迹但学术可用源极少 → 近零误报：至少若干非学术 citation 才认「搜了但水」。
_MIN_CITATIONS_FOR_ACADEMIC_GAP = 2

# 论文库 / DOI / 预印本等（假设名单；与学术搜索偏置对齐，非允许域硬闸）。
_ACADEMIC_HOST_SUFFIXES: frozenset[str] = frozenset(
    {
        "arxiv.org",
        "pubmed.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "doi.org",
        "dx.doi.org",
        "semanticscholar.org",
        "acm.org",
        "dl.acm.org",
        "ieee.org",
        "ieeexplore.ieee.org",
        "springer.com",
        "link.springer.com",
        "nature.com",
        "science.org",
        "sciencedirect.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "nih.gov",
        "biorxiv.org",
        "medrxiv.org",
        "ssrn.com",
        "openalex.org",
        "crossref.org",
        "jstor.org",
        "plos.org",
        "frontiersin.org",
        "mdpi.com",
        "tandfonline.com",
        "sagepub.com",
        "oup.com",
        "academic.oup.com",
        "cell.com",
        "thelancet.com",
        "nejm.org",
        "bmj.com",
        "cochranelibrary.com",
        "who.int",
    }
)

# 成稿/审校可观测「无参考文献 · 靠先验」缺口（窄匹配；禁完成话术词）。
_NO_REFS_OR_PRIOR_MARKERS: tuple[str, ...] = (
    "无参考文献",
    "没有参考文献",
    "缺少参考文献",
    "未附参考文献",
    "无引用文献",
    "靠先验",
    "基于先验",
    "基于对该领域的了解",
    "基于已有知识",
    "基于模型知识",
    "搜不到文献",
    "未能检索到相关文献",
    "常规搜索拿不到",
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _node_deliverable(node: Any) -> Any:
    if isinstance(node, dict):
        return node.get("deliverable")
    return getattr(node, "deliverable", None)


def _node_role(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("role") or "").strip()
    return str(getattr(node, "role", "") or "").strip()


def plan_is_literature_report_delivery(plan_nodes: object) -> bool:
    """True for ``research_report`` / 同等成文综述；``parallel_brief`` 默认 False.

    判定（结构字段，不扫 task 自由文）：
    - ``deliverable.min_length≥3000`` 成篇信号；或
    - 批内含审校/审查角色 **且** 存在 two_phase / research·reviews 案卷 deliverable
      （``research_report`` 与手写同构；``parallel_brief`` 无审校 → 不进）。
    """
    if plan_signals_long_form_audit(plan_nodes):
        return True
    if not isinstance(plan_nodes, (list, tuple)) or not plan_nodes:
        return False
    as_tasks = [
        {"role": _node_role(n), "deliverable": _node_deliverable(n)} for n in plan_nodes
    ]
    if not batch_includes_review_role(as_tasks):
        return False
    for node in plan_nodes:
        deliverable = _node_deliverable(node)
        if is_two_phase_citation_deliverable(deliverable):
            return True
    return False


def is_academic_usable_url(url: str) -> bool:
    """True when URL host looks like a paper / DOI / preprint venue."""
    host = urlparse(url if "://" in (url or "") else f"https://{url or ''}").netloc.casefold()
    host = host.removeprefix("www.")
    if not host:
        return False
    for suffix in _ACADEMIC_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def academic_usable_citation_count(citations: object) -> int:
    """Count citations whose URL is an academic-usable host (dedupe by URL)."""
    if not isinstance(citations, list):
        return 0
    seen: set[str] = set()
    n = 0
    for row in citations:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if is_academic_usable_url(url):
            n += 1
    return n


def _citation_total(citations: object) -> int:
    if not isinstance(citations, list):
        return 0
    seen: set[str] = set()
    for row in citations:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
    return len(seen)


def _meta_signals_evidence_deficit(meta: object) -> bool:
    """True when a search/tool metadata dict carries a structured evidence-gap stamp."""
    if not isinstance(meta, dict) or not meta:
        return False
    # Search-side true source (academic_literature junk / empty inject).
    if meta.get(EVIDENCE_GAP_KEY) is True:
        return True
    # Legacy stamp — keep reading so older workers / fixtures still trip.
    if meta.get(EVIDENCE_DEFICIT_KEY) is True:
        return True
    quality = str(meta.get(EVIDENCE_QUALITY_KEY) or "").strip().casefold()
    if quality and quality == EVIDENCE_QUALITY_POOR:
        return True
    policy = str(meta.get("search_policy") or "").strip().casefold()
    academic_policy = (
        policy == SEARCH_POLICY_ACADEMIC_LITERATURE.casefold()
        or policy == "academic_evidence"
        or "academic" in policy
    )
    if academic_policy:
        if meta.get("low_relevance") is True or meta.get("empty") is True:
            return True
        try:
            streak = int(meta.get("empty_streak") or 0)
        except (TypeError, ValueError):
            streak = 0
        if streak >= 2:
            return True
        if ACADEMIC_USABLE_COUNT_KEY in meta:
            try:
                if int(meta.get(ACADEMIC_USABLE_COUNT_KEY) or 0) <= 0:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        match = _JSON_OBJECT_RE.search(raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            return None
    return data if isinstance(data, dict) else None


def _transcript_search_evidence_deficit(transcript: object) -> bool:
    """Scan web_search tool messages for structured evidence-gap fields in output JSON."""
    if not isinstance(transcript, (list, tuple)) or not transcript:
        return False
    call_names: dict[str, str] = {}
    for msg in transcript:
        tool_calls = getattr(msg, "tool_calls", None)
        if getattr(msg, "role", None) == "assistant" and tool_calls:
            for tc in tool_calls:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "") if fn is not None else ""
                tc_id = getattr(tc, "id", "") or ""
                if tc_id and name:
                    call_names[tc_id] = str(name)
        if getattr(msg, "role", None) != "tool":
            continue
        tc_id = getattr(msg, "tool_call_id", None) or ""
        if call_names.get(str(tc_id)) != "web_search":
            continue
        payload = _parse_json_object(str(getattr(msg, "content", "") or ""))
        if payload is not None and _meta_signals_evidence_deficit(payload):
            return True
    return False


def _state_structured_evidence_deficit(state: Any) -> bool:
    """True when this RunState already carries a structured evidence-gap stamp.

    Prefers search-side stamps (``evidence_gap`` attr / sticky via
    ``evidence_meta`` / ``search_evidence`` / web_search transcript JSON).
    ``evidence_deficit`` attr remains a compatibility read. Does **not** re-read
    ``delivery_gaps`` rows with ``reason=evidence_deficit`` — those already flow
    through ``collect_worker_gaps`` into the delivery card.
    """
    if state is None:
        return False
    if getattr(state, EVIDENCE_GAP_KEY, False) is True:
        return True
    if getattr(state, EVIDENCE_DEFICIT_KEY, False) is True:
        return True
    for key in ("evidence_meta", "search_evidence"):
        if _meta_signals_evidence_deficit(getattr(state, key, None)):
            return True
    if _transcript_search_evidence_deficit(getattr(state, "transcript", None)):
        return True
    return False


def _batch_has_structured_evidence_deficit(results: dict[str, Any]) -> bool:
    return any(_state_structured_evidence_deficit(st) for st in (results or {}).values())


def _batch_almost_no_academic_sources(results: dict[str, Any]) -> bool:
    """True when the batch consulted sources but almost none are academic-usable."""
    all_cites: list[dict[str, Any]] = []
    for state in (results or {}).values():
        if state is None:
            continue
        for row in getattr(state, "citations", None) or []:
            if isinstance(row, dict):
                all_cites.append(row)
    total = _citation_total(all_cites)
    if total < _MIN_CITATIONS_FOR_ACADEMIC_GAP:
        return False
    return academic_usable_citation_count(all_cites) == 0


def _text_has_no_refs_or_prior_gap(text: str) -> bool:
    return any(marker in (text or "") for marker in _NO_REFS_OR_PRIOR_MARKERS)


def _batch_has_no_refs_or_prior_gap(
    plan_nodes: object,
    results: dict[str, Any],
) -> bool:
    """True when writer/reviewer surfaces (content/warnings/debrief/gaps) admit no-refs/prior."""
    reviewish_ids: set[str] = set()
    writerish_ids: set[str] = set()
    if isinstance(plan_nodes, (list, tuple)):
        for node in plan_nodes:
            role = _node_role(node).casefold()
            rid = ""
            if isinstance(node, dict):
                rid = str(node.get("run_id") or node.get("id") or "")
            else:
                rid = str(getattr(node, "run_id", "") or "")
            if not rid:
                continue
            if is_independent_review_role(role):
                reviewish_ids.add(rid)
            if any(m in role for m in ("撰稿", "写作", "writer", "作者")):
                writerish_ids.add(rid)

    for rid, state in (results or {}).items():
        if state is None:
            continue
        # Prefer writer / reviewer surfaces; also accept any delivery_gap already tagged.
        prefer = (not reviewish_ids and not writerish_ids) or (
            rid in reviewish_ids or rid in writerish_ids
        )
        if not prefer:
            continue
        surfaces: list[str] = [
            str(getattr(state, "content", "") or ""),
            *[str(w) for w in (getattr(state, "warnings", None) or [])],
        ]
        debrief = getattr(state, "debrief", None)
        if isinstance(debrief, dict):
            surfaces.append(str(debrief.get("summary") or ""))
            for kp in debrief.get("key_points") or []:
                surfaces.append(str(kp))
            for a in debrief.get("assumptions") or []:
                surfaces.append(str(a))
        for row in getattr(state, "delivery_gaps", None) or []:
            if isinstance(row, dict):
                surfaces.append(str(row.get("description") or ""))
        if any(_text_has_no_refs_or_prior_gap(s) for s in surfaces):
            return True
    return False


def literature_evidence_deficit_hit(
    plan_nodes: object,
    results: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return ``(hit, reason_bits)`` for literature-report evidence deficit (combinable)."""
    if not plan_is_literature_report_delivery(plan_nodes):
        return False, []
    bits: list[str] = []
    if _batch_has_structured_evidence_deficit(results):
        bits.append("学术检索侧结构化证据差信号")
    if _batch_almost_no_academic_sources(results):
        bits.append("几乎无学术可用源")
    if _batch_has_no_refs_or_prior_gap(plan_nodes, results):
        bits.append("成稿或审校标明无参考文献或靠先验")
    return bool(bits), bits


def collect_evidence_deficit_gaps(
    plan_nodes: object,
    results: dict[str, Any],
) -> list[dict[str, str]]:
    """Blocking gap rows for ``delivery_status`` when literature evidence is insufficient.

    Empty when not a literature-report shape, or evidence looks adequate.
    Does **not** scan completion-claim phrases（如「综述已完成」）.
    """
    hit, bits = literature_evidence_deficit_hit(plan_nodes, results)
    if not hit:
        return []
    detail = "；".join(bits) if bits else "证据不足"
    return [
        {
            "description": (
                f"文献成文证据不足，本批仅能按草稿/部分交付（{detail}）"
            ),
            "reason": REASON_EVIDENCE_DEFICIT,
        }
    ]

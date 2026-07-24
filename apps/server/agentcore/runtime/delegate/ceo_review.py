"""CEO 评审前置：checkpoint 波完成后、plan_review 暂停前强制把关摘要。

读取本波 worker 落盘 / handoff 产出，生成结构化把关意见（结论 + 风险点 + 建议），
随 ``plan_review_required`` payload 下发。拍板卡展示；用户「继续」且 ``source=="llm"``
时压缩注入下游 ``gate_notes``（deterministic 默认不下发）。

LLM 不可用或解析失败时回落确定性摘要（debrief / 落盘路径），保证暂停路径不因评审失败而中断。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.llm.profiles import build_request, get_profile
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.runs.constants import PLAN_REVIEW_SUMMARY_CHARS

if TYPE_CHECKING:
    from agentcore.runtime.runs.types import RunSpec

logger = get_logger(__name__)

_JSON_RE = re.compile(r"\{[\s\S]*\}")
_MAX_FILE_CHARS = 6000
_MAX_FILES_PER_NODE = 3


def deterministic_ceo_review(
    nodes: list[RunSpec],
    completed: dict[str, Any],
) -> dict[str, Any]:
    """Build a put-through review from debriefs / files when LLM review is unavailable."""
    conclusions: list[str] = []
    risks: list[str] = []
    suggestions: list[str] = []
    for node in nodes:
        state = completed.get(node.run_id)
        role = node.role or node.run_id
        if state is None:
            risks.append(f"{role}：本波无完成态产出")
            continue
        debrief = state.debrief if isinstance(getattr(state, "debrief", None), dict) else None
        summary = ""
        if debrief:
            summary = str(debrief.get("summary") or "").strip()
            for kp in debrief.get("key_points") or []:
                text = str(kp).strip()
                if text:
                    suggestions.append(f"{role}：{text}")
            next_steps = str(debrief.get("next_steps") or "").strip()
            if next_steps:
                suggestions.append(f"{role} 建议下一步：{next_steps}")
            assumptions = debrief.get("assumptions") or []
            if isinstance(assumptions, list):
                for a in assumptions:
                    text = str(a).strip()
                    if text:
                        risks.append(f"{role} 假设：{text}")
        if not summary:
            content = (getattr(state, "content", None) or "").strip()
            if content:
                summary = content[:PLAN_REVIEW_SUMMARY_CHARS]
        files = list(getattr(state, "files_touched", None) or [])
        if summary:
            conclusions.append(f"{role}：{summary}")
        elif files:
            conclusions.append(f"{role}：已落盘 {', '.join(files[:5])}")
        else:
            risks.append(f"{role}：缺少交接结论与落盘文件")
        if files:
            suggestions.append(f"请重点复核：{', '.join(files[:_MAX_FILES_PER_NODE])}")
    conclusion = (
        "；".join(conclusions) if conclusions else "本波 worker 已完成，请人工复核后再放行下游。"
    )
    return {
        "conclusion": conclusion[:1200],
        "risks": risks[:8] or ["未识别到显式风险点，请对照落盘产物自行判断。"],
        "suggestions": suggestions[:8] or ["确认规格与下游任务对齐后继续。"],
        "source": "deterministic",
    }


async def _read_wave_artifacts(
    nodes: list[RunSpec],
    completed: dict[str, Any],
    backend: Any,
) -> str:
    """Assemble a compact brief of this wave's products for the reviewer LLM."""
    parts: list[str] = []
    for node in nodes:
        state = completed.get(node.run_id)
        role = node.role or node.run_id
        if state is None:
            parts.append(f"### {role}\n（无完成态）")
            continue
        block = [f"### {role} ({node.run_id})"]
        debrief = state.debrief if isinstance(getattr(state, "debrief", None), dict) else None
        if debrief:
            block.append(f"交接结论：{debrief.get('summary') or '（无）'}")
            kps = debrief.get("key_points") or []
            if kps:
                block.append("要点：\n" + "\n".join(f"- {k}" for k in kps[:6]))
        content = (getattr(state, "content", None) or "").strip()
        if content:
            clip = content[:800] + ("…" if len(content) > 800 else "")
            block.append(f"正文摘要：\n{clip}")
        files = list(getattr(state, "files_touched", None) or [])
        if files and backend is not None and hasattr(backend, "read"):
            block.append("落盘文件：")
            for path in files[:_MAX_FILES_PER_NODE]:
                try:
                    body = await backend.read(path)
                    text = body if isinstance(body, str) else str(body)
                    if len(text) > _MAX_FILE_CHARS:
                        text = text[:_MAX_FILE_CHARS] + "\n…（截断）"
                    block.append(f"—— {path} ——\n{text}")
                except Exception:  # noqa: BLE001 — best-effort read for review only
                    block.append(f"—— {path} ——\n（读取失败）")
        elif files:
            block.append("落盘：" + ", ".join(files[:10]))
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def _parse_review_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    conclusion = str(data.get("conclusion") or "").strip()
    raw_risks = data.get("risks")
    risks = raw_risks if isinstance(raw_risks, list) else []
    raw_suggestions = data.get("suggestions")
    suggestions = raw_suggestions if isinstance(raw_suggestions, list) else []
    if not conclusion:
        return None
    return {
        "conclusion": conclusion[:1200],
        "risks": [str(r).strip() for r in risks if str(r).strip()][:8]
        or ["未识别到显式风险点，请对照落盘产物自行判断。"],
        "suggestions": [str(s).strip() for s in suggestions if str(s).strip()][:8]
        or ["确认规格与下游任务对齐后继续。"],
        "source": "llm",
    }


async def run_ceo_review(
    *,
    nodes: list[RunSpec],
    completed: dict[str, Any],
    llm: Any,
    backend: Any = None,
    model: str | None = None,
    pending: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Force one CEO review pass over the just-completed checkpoint wave.

    Returns a ``{conclusion, risks, suggestions, source}`` dict always
    (``source`` is ``"llm"`` or ``"deterministic"``).
    """
    fallback = deterministic_ceo_review(nodes, completed)
    if llm is None or not hasattr(llm, "complete"):
        logger.info("plan_review.ceo_review_fallback", reason="no_llm")
        return fallback

    artifacts = await _read_wave_artifacts(nodes, completed, backend)
    pending_lines = ""
    if pending:
        pending_lines = "\n待放行下游：\n" + "\n".join(
            f"- {p.get('role') or p.get('run_id')}" for p in pending
        )
    prompt = (
        "你是团队主管。队员刚完成检查点波次并提交了交接；用户即将复核。\n"
        "请阅读下列产出，给出把关摘要。只输出一个 JSON 对象，勿加 markdown 围栏：\n"
        '{"conclusion":"一句话总评","risks":["风险1",...],"suggestions":["建议1",...]}\n'
        "要求：conclusion 必填；risks / suggestions 各 1–5 条，具体可执行；"
        "对照落盘内容找缺口 / 风险，勿空泛夸奖。\n\n"
        f"{artifacts}{pending_lines}"
    )
    profile = get_profile("compaction")
    resolved_model = model or "grok-4.5"
    request = build_request(
        profile,
        [LLMMessage(role="user", content=prompt)],
        stream=False,
        model=resolved_model,
    )
    try:
        response = await llm.complete(request)
        parsed = _parse_review_json(getattr(response, "content", "") or "")
        if parsed is None:
            logger.info("plan_review.ceo_review_fallback", reason="parse_failed")
            return fallback
        logger.info(
            "plan_review.ceo_review_done",
            nodes=[n.run_id for n in nodes],
            risks=len(parsed["risks"]),
            suggestions=len(parsed["suggestions"]),
        )
        return parsed
    except Exception:  # noqa: BLE001 — review must never block the pause path
        logger.exception("plan_review.ceo_review_failed")
        return fallback

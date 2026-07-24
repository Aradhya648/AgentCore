"""质询作答 → 逐条 Q↔A 解析（质询回合 P1）。

主路径：按 markdown 标题确定性切段（``### 质询一`` / ``质询1`` / ``Q1`` / ``1.``），
构造 ``exchanges[]``。切不出标题时：先按空行段落配对；仍失败则首条挂全文、其余挂
「未按标题分段」指针（避免「全文只挂第一题、其余空答」造成的问答错位）。首个标题前的引子
确定性丢弃。JSON 解析路径已退役（辩论发言是给人看的流式文本，与立论同用标题体）。

另提供作答尾部完整性检测（冒号 / 未闭合列表悬垂）与续写合并，供质询 runner 在装配前
自动补全一次。

是否正面回应 / 回避由裁判据 Q↔A 原文裁定（engagement + decisive），本模块只负责问↔答对齐，
不产出任何二元褒贬字段。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agentcore.core.logging import get_logger
from agentcore.runtime.debate.types import CrossExamQa

logger = get_logger(__name__)

# 数字分段要求分隔符后非数字，避免「3.5 倍…」被误当第 3 段。
# 可选 ``### `` 等 markdown 标题前缀（产出端契约：``### 质询一``）。
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:"
    r"质询[一二三四五六七八九十\d]+|"
    r"[Qq]\s*\d+|"
    r"\d+[.、)](?!\d)"
    r")\s*[:：.]?\s*",
    re.MULTILINE,
)

_UNSEGMENTED_POINTER = "（同场作答未按条目标题分段，完整内容见首条）"


def looks_incomplete_cross_exam_answer(content: str) -> bool:
    """作答尾部是否呈生成停写悬垂（冒号收束 / 未闭合列表项）。

    只看文本尾部形态，不推断语义完备性；供质询 runner 决定是否自动续写补全一次。
    典型实例：「理由是：」「但间接证据链完整：」或末行仅 ``-`` / ``1.``。
    """
    text = (content or "").rstrip()
    if not text:
        return False
    if re.search(r"[:：]\s*$", text):
        return True
    last_line = text.rsplit("\n", 1)[-1].strip()
    if re.fullmatch(r"[-*•]", last_line):
        return True
    return bool(re.fullmatch(r"\d+[.、)]", last_line))


def merge_cx_continuation(prior: str, continuation: str) -> str:
    """把一次补全续写并入原作答。

    续写若以质询标题重写全文 → 采用续写；否则视为接在悬垂后的尾巴，直接拼接。
    """
    prior_s = (prior or "").rstrip()
    cont_s = (continuation or "").strip()
    if not cont_s:
        return prior_s
    if not prior_s:
        return cont_s
    head = cont_s.lstrip()[:80]
    if head.startswith("#") or re.match(r"质询[一二三四五六七八九十\d]+", head):
        return cont_s
    # 原文明以冒号悬垂时，续写常从冒号后正文起笔——直接拼，避免双冒号。
    if prior_s.endswith(("：", ":")):
        return f"{prior_s}{cont_s}"
    return f"{prior_s}\n{cont_s}"


def parse_cross_exam_response(
    questions: Sequence[str],
    content: str,
    *,
    side_key: str = "",
) -> list[CrossExamQa]:
    """从辩手质询作答构造与 ``questions`` 等长的逐条交换。

    主路径：标题切段；切不出 → 空行段落配对；仍失败 → 首条挂全文、其余挂指针。
    只对齐 question ↔ answer；空答表示未作答 / 失败兜底。``side_key`` 写入降级日志。
    """
    qs = [q.strip() for q in questions if q and q.strip()]
    if not qs:
        return []

    text = (content or "").strip()
    if not text:
        return [CrossExamQa(question=q, answer="") for q in qs]

    sections = _split_sections(text)
    if sections:
        return _zip_answers(qs, sections)

    paras = _split_paragraphs(text)
    if len(paras) >= 2:
        logger.info(
            "debate.cross_exam_parse.paragraph_fallback",
            side_key=side_key or None,
            question_count=len(qs),
            paragraph_count=len(paras),
            content_len=len(text),
        )
        return _zip_answers(qs, paras)

    logger.info(
        "debate.cross_exam_parse.degraded",
        side_key=side_key or None,
        question_count=len(qs),
        content_len=len(text),
    )
    if len(qs) == 1:
        return [CrossExamQa(question=qs[0], answer=text)]
    # 单团块多题：全文挂首条，其余挂指针——裁判仍能在首条看到完整作答，且不会把后题误判为「未作答」。
    return [CrossExamQa(question=qs[0], answer=text)] + [
        CrossExamQa(question=q, answer=_UNSEGMENTED_POINTER) for q in qs[1:]
    ]


def build_cross_exam_exchanges(
    questions: Sequence[str],
    answer: str,
    *,
    side_key: str = "",
) -> list[CrossExamQa]:
    """与 :func:`parse_cross_exam_response` 同契约（兼容既有调用点）。"""
    return parse_cross_exam_response(questions, answer, side_key=side_key)


def _zip_answers(qs: Sequence[str], parts: Sequence[str]) -> list[CrossExamQa]:
    sections = list(parts)
    if len(sections) > len(qs):
        sections = sections[: len(qs)]
    elif len(sections) < len(qs):
        sections = sections + [""] * (len(qs) - len(sections))
    return [
        CrossExamQa(question=q, answer=sec)
        for q, sec in zip(qs, sections, strict=True)
    ]


def _split_sections(text: str) -> list[str]:
    """按质询标题切段；首个标题前的引子丢弃。无标题 → 空列表（触发段落 / 降级路径）。"""
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return []
    sections: list[str] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[start:end].strip())
    return sections


def _split_paragraphs(text: str) -> list[str]:
    """按空行切段；单段 → 单元素列表（不足以配对多题）。"""
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    return parts

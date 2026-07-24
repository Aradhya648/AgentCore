"""辩手发言 → 结构化论点列表（单一源；前端旧启发式仅作老 journal 回退）。

与桌面 ``parseSpeechArguments`` 同口径：markdown 标题 / 有序·无序列表 / 空行分段；
单段则整段为一个论点。产出进 ``debate_round`` / ``debate_result`` 的 ``sides[*].arguments``。

``title`` 存完整标题（不在数据层截断）；折叠态由前端 CSS 截断展示。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADER_SPLIT = re.compile(r"(?=^#{1,3}\s+)", re.MULTILINE)
_NUMBERED_LINE = re.compile(r"^\d+\.\s+")
_BULLET_LINE = re.compile(r"^[-*•]\s+")


@dataclass(frozen=True)
class SpeechArgument:
    id: str
    title: str
    body: str

    def to_payload(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title, "body": self.body}


def summarize_text(text: str, max_len: int) -> str:
    """截断为一行摘要：优先在句读处断开（质询预览等；论点 title 路径勿用）。"""
    trimmed = re.sub(r"\s+", " ", (text or "").strip())
    if not trimmed:
        return ""
    if len(trimmed) <= max_len:
        return trimmed
    slice_ = trimmed[:max_len]
    last_punct = max(
        slice_.rfind("。"),
        slice_.rfind("；"),
        slice_.rfind("，"),
        slice_.rfind("—"),
        slice_.rfind("–"),
    )
    if last_punct > max_len * 0.45:
        return slice_[: last_punct + 1]
    return f"{slice_}…"


def _normalize_title(text: str) -> str:
    """折叠空白，不截断。"""
    return re.sub(r"\s+", " ", (text or "").strip())


def argument_title(body: str) -> str:
    """从一段发言正文中提取论点标题（首句 / 冒号标签 / 首行）；完整文案入库。"""
    trimmed = (body or "").strip()
    if not trimmed:
        return ""
    colon_match = re.match(r"^([^：:\n]{2,24}[：:])\s*", trimmed)
    if colon_match:
        label = re.sub(r"[：:]$", "", colon_match.group(1))
        after = trimmed[colon_match.end() :]
        clause = re.split(r"[。；—–-]", after, maxsplit=1)[0].strip()
        if clause:
            return _normalize_title(f"{label}：{clause}")
        return _normalize_title(label)
    first_line = trimmed.split("\n", 1)[0]
    first_sentence = re.split(r"[。；]", first_line, maxsplit=1)[0].strip() or first_line.strip()
    return _normalize_title(first_sentence)


def parse_speech_arguments(text: str) -> list[SpeechArgument]:
    """把辩手发言拆成论点列表。"""
    blocks = _split_blocks(text)
    if not blocks:
        return []
    return [_block_to_argument(block, i) for i, block in enumerate(blocks)]


def _split_blocks(text: str) -> list[str]:
    trimmed = (text or "").strip()
    if not trimmed:
        return []
    if _HEADER_SPLIT.search(trimmed):
        return [b.strip() for b in _HEADER_SPLIT.split(trimmed) if b.strip()]
    lines = trimmed.split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    if (
        nonempty
        and len(nonempty) > 1
        and all(_NUMBERED_LINE.match(ln.strip()) for ln in nonempty)
    ):
        return [ln.strip() for ln in nonempty]
    if (
        nonempty
        and len(nonempty) > 1
        and all(_BULLET_LINE.match(ln.strip()) for ln in nonempty)
    ):
        return [ln.strip() for ln in nonempty]
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", trimmed) if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    return [trimmed]


def _title_from_header_block(block: str) -> tuple[str, str]:
    lines = block.split("\n")
    head = re.sub(r"^#{1,3}\s+", "", lines[0] or "").strip()
    body = "\n".join(lines[1:]).strip() or head
    return _normalize_title(head), body or block


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^(?:\d+\.\s+|[-*•]\s+)", "", line).strip()


def _block_to_argument(block: str, i: int) -> SpeechArgument:
    if re.match(r"^#{1,3}\s+", block):
        title, body = _title_from_header_block(block)
        return SpeechArgument(id=f"arg-{i}", title=title, body=body)
    stripped = _strip_list_marker(block)
    return SpeechArgument(
        id=f"arg-{i}",
        title=argument_title(stripped),
        body=stripped,
    )

"""Pre-parse text-like binary attachments at residency time (附件分流预解析).

分流：docx/pdf/pptx 等用 markitdown 抽文本，写出与原件并存的 ``原名.ext.md``；
``.txt`` / ``.md`` / HTML 等可直接 UTF-8 读的格式只内联正文（原件已是可读副本）；
xlsx/csv 跳过，保留运行时 ``code_execute``。扫描版 PDF 首版不做 OCR，写入明确
降级提示。解析失败不阻塞驻留，回落「路径提示 + 委派解析」。

工作区 ``file_read`` 对同一 markitdown 桶做**透明抽取**（读时默认不写 ``*.md``），
复用本模块公开核 ``extract_office_bytes`` / ``convert_with_markitdown`` /
``looks_like_scanned``；``preparse_resident`` 仍只服务附件驻留。

→ 见决策：docs/02-架构/双模式工作区.md §七（Office 云=本地）与附件驻留实现。
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

from agentcore.core.logging import get_logger
from agentcore.workspace.protocol import WorkspaceBackend, WorkspaceError

logger = get_logger(__name__)

# Office / PDF：必须经 markitdown（或等价）才能得到可读正文。
MARKITDOWN_EXTENSIONS = frozenset({".docx", ".pdf", ".pptx", ".odt", ".rtf"})
# 已是文本层：直接 UTF-8 解码；原件本身即工作区可读副本。
PLAIN_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".html", ".htm"})
# 大表 / 计算场景：不预解析全表；``file_read`` 亦不透明抽。
SKIP_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".xls", ".csv", ".tsv"})

# Back-compat aliases (private names used by older call sites / tests).
_MARKITDOWN_EXTENSIONS = MARKITDOWN_EXTENSIONS
_PLAIN_TEXT_EXTENSIONS = PLAIN_TEXT_EXTENSIONS
_SKIP_EXTENSIONS = SKIP_EXTENSIONS

# 扫描件启发式：可打印字母数字过少 → 视为无文本层（不做 OCR）。
_SCAN_MIN_ALNUM = 40
# 大文件仍几乎无字：≥50KB 且 alnum < 200 → 扫描件。
_SCAN_LARGE_BYTES = 50_000
_SCAN_LARGE_MIN_ALNUM = 200

# 首轮 prompt 内联上限（字符）。约 6k tokens，给历史/工具/记忆留预算；
# 全文落在 ``*.md`` 副本，Agent 可用 file_read 续读。多附件时各自独立截断。
ATTACHMENT_INLINE_MAX_CHARS = 24_000

SCAN_NOTICE = (
    "This file appears to be a scanned / image-only document with little or no "
    "extractable text layer. OCR is not available in this build. Tell the user "
    "the file looks like a scan and ask them to provide a text-layer PDF or paste "
    "the relevant passages."
)
_SCAN_NOTICE = SCAN_NOTICE


class ParseStatus(StrEnum):
    OK = "ok"
    SCANNED = "scanned"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExtractResult:
    """In-memory office/PDF extract (no workspace write)."""

    status: ParseStatus
    text: str = ""
    """Full extracted text, or scan/failure note. Empty when skipped."""
    detail: str = ""
    """Short machine-oriented reason for logs / tests."""


@dataclass(frozen=True, slots=True)
class PreparseResult:
    status: ParseStatus
    text: str = ""
    """Full extracted text (or scan/failure note). Empty when skipped."""
    parsed_workspace_path: str | None = None
    """Workspace-relative readable copy (``*.md``) or the original when already text."""
    detail: str = ""
    """Short machine-oriented reason for logs / tests."""


def extension_of(name: str | None, workspace_path: str | None = None) -> str:
    """Lowercase extension from display name, falling back to workspace path."""
    for candidate in (name, workspace_path):
        if not candidate:
            continue
        base = os.path.basename(candidate.replace("\\", "/"))
        _, ext = os.path.splitext(base)
        if ext:
            return ext.lower()
    return ""


def should_preparse(name: str | None, workspace_path: str | None = None) -> bool:
    """True when this binary resident is in the text-document bucket (not xlsx/csv)."""
    ext = extension_of(name, workspace_path)
    if not ext or ext in SKIP_EXTENSIONS:
        return False
    return ext in MARKITDOWN_EXTENSIONS or ext in PLAIN_TEXT_EXTENSIONS


def looks_like_scanned(text: str, raw_size: int) -> bool:
    """Heuristic: almost no alphanumeric content ⇒ image-only / scan PDF."""
    alnum = sum(1 for c in text if c.isalnum())
    if alnum < _SCAN_MIN_ALNUM:
        return True
    return raw_size >= _SCAN_LARGE_BYTES and alnum < _SCAN_LARGE_MIN_ALNUM


def parsed_copy_path(workspace_path: str) -> str:
    """``attachments/report.docx`` → ``attachments/report.docx.md``."""
    return f"{workspace_path}.md"


def truncate_for_prompt(text: str, limit: int = ATTACHMENT_INLINE_MAX_CHARS) -> tuple[str, bool]:
    """Return ``(maybe_truncated_text, was_truncated)`` for first-turn inline context."""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def convert_with_markitdown(data: bytes, ext: str) -> str:
    """Sync markitdown convert (call via ``asyncio.to_thread`` from async paths)."""
    return _convert_with_markitdown(data, ext)


def _convert_with_markitdown(data: bytes, ext: str) -> str:
    from markitdown import MarkItDown

    md = MarkItDown(enable_plugins=False)
    result = md.convert_stream(BytesIO(data), file_extension=ext)
    return (result.text_content or "").strip()


def _decode_plain_text(data: bytes) -> str | None:
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return None


async def extract_office_bytes(data: bytes, *, ext: str) -> ExtractResult:
    """Extract text from office/PDF bytes without writing a workspace ``*.md`` copy.

    Applies to ``MARKITDOWN_EXTENSIONS`` only. Spreadsheets return ``SKIPPED``;
    convert errors return ``FAILED`` (never raises). Scanned / empty text layer
    returns ``SCANNED`` with ``SCAN_NOTICE`` (honest receipt, not empty success).
    """
    normalized = ext.lower() if ext.startswith(".") else (f".{ext.lower()}" if ext else "")
    if normalized in SKIP_EXTENSIONS:
        return ExtractResult(status=ParseStatus.SKIPPED, detail=f"skip_ext:{normalized}")
    if normalized not in MARKITDOWN_EXTENSIONS:
        return ExtractResult(status=ParseStatus.SKIPPED, detail=f"unknown_ext:{normalized or '?'}")

    try:
        text = await asyncio.to_thread(_convert_with_markitdown, data, normalized)
    except Exception as e:
        logger.warning(
            "attachment.extract_failed",
            ext=normalized,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ExtractResult(status=ParseStatus.FAILED, detail=f"convert:{type(e).__name__}")

    if looks_like_scanned(text, len(data)):
        return ExtractResult(
            status=ParseStatus.SCANNED,
            text=SCAN_NOTICE,
            detail="scanned_or_empty_text_layer",
        )

    return ExtractResult(status=ParseStatus.OK, text=text, detail="ok")


async def preparse_resident(
    backend: WorkspaceBackend,
    *,
    workspace_path: str,
    name: str | None,
) -> PreparseResult:
    """Read a resident binary attachment and attempt text extraction.

    Never raises for parse failures — returns ``FAILED`` / ``SKIPPED`` so the
    caller can keep the existing path-hint behaviour.
    """
    ext = extension_of(name, workspace_path)
    if ext in SKIP_EXTENSIONS:
        return PreparseResult(status=ParseStatus.SKIPPED, detail=f"skip_ext:{ext}")
    if ext not in MARKITDOWN_EXTENSIONS and ext not in PLAIN_TEXT_EXTENSIONS:
        return PreparseResult(status=ParseStatus.SKIPPED, detail=f"unknown_ext:{ext or '?'}")

    try:
        data = await backend.read_bytes(workspace_path)
    except WorkspaceError as e:
        logger.warning(
            "attachment.preparse_read_failed",
            path=workspace_path,
            error=str(e),
        )
        return PreparseResult(status=ParseStatus.FAILED, detail=f"read:{e}")

    if ext in PLAIN_TEXT_EXTENSIONS:
        try:
            text = _decode_plain_text(data)
            if text is None:
                # Odd encoding — last resort via markitdown.
                text = await asyncio.to_thread(_convert_with_markitdown, data, ext)
        except Exception as e:
            logger.warning(
                "attachment.preparse_failed",
                path=workspace_path,
                name=name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return PreparseResult(status=ParseStatus.FAILED, detail=f"convert:{type(e).__name__}")
        if not text:
            return PreparseResult(status=ParseStatus.FAILED, detail="empty_plain_text")
        return PreparseResult(
            status=ParseStatus.OK,
            text=text,
            parsed_workspace_path=workspace_path,
            detail="plain_text",
        )

    extracted = await extract_office_bytes(data, ext=ext)

    if extracted.status == ParseStatus.FAILED:
        return PreparseResult(status=ParseStatus.FAILED, detail=extracted.detail)

    if extracted.status == ParseStatus.SCANNED:
        notice = extracted.text or SCAN_NOTICE
        copy_path = parsed_copy_path(workspace_path)
        try:
            await backend.write(copy_path, notice + "\n")
        except WorkspaceError as e:
            logger.warning(
                "attachment.preparse_scan_note_write_failed",
                path=copy_path,
                error=str(e),
            )
            copy_path_out: str | None = None
        else:
            copy_path_out = copy_path
        logger.info(
            "attachment.preparse_scanned",
            path=workspace_path,
            name=name,
            raw_bytes=len(data),
            extracted_chars=len(extracted.text),
        )
        return PreparseResult(
            status=ParseStatus.SCANNED,
            text=notice,
            parsed_workspace_path=copy_path_out,
            detail=extracted.detail or "scanned_or_empty_text_layer",
        )

    text = extracted.text
    copy_path = parsed_copy_path(workspace_path)
    try:
        await backend.write(copy_path, text if text.endswith("\n") else text + "\n")
    except WorkspaceError as e:
        logger.warning(
            "attachment.preparse_copy_write_failed",
            path=copy_path,
            error=str(e),
        )
        # Still expose text inline even if the durable copy failed.
        return PreparseResult(
            status=ParseStatus.OK,
            text=text,
            parsed_workspace_path=None,
            detail="ok_inline_only",
        )

    logger.info(
        "attachment.preparse_ok",
        path=workspace_path,
        parsed_path=copy_path,
        name=name,
        chars=len(text),
    )
    return PreparseResult(
        status=ParseStatus.OK,
        text=text,
        parsed_workspace_path=copy_path,
        detail="ok",
    )

"""Tests for attachment分流预解析 (``attachment_parse`` + persist hook + prompt)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agentcore.runtime.pipeline import _build_attachment_context
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.attachment_parse import (
    ATTACHMENT_INLINE_MAX_CHARS,
    ParseStatus,
    extract_office_bytes,
    looks_like_scanned,
    parsed_copy_path,
    preparse_resident,
    should_preparse,
    truncate_for_prompt,
)
from agentcore.workspace.attachments import persist_attachments
from agentcore.workspace.server import ServerWorkspace


def _ws(root: Path) -> ServerWorkspace:
    return ServerWorkspace(root=root, sandbox=SubprocessSandbox())


def test_should_preparse_routing():
    assert should_preparse("a.docx") is True
    assert should_preparse("a.pdf") is True
    assert should_preparse("a.pptx") is True
    assert should_preparse("notes.txt") is True
    assert should_preparse("a.xlsx") is False
    assert should_preparse("a.csv") is False
    assert should_preparse("a.xls") is False
    assert should_preparse("photo.png") is False


def test_looks_like_scanned_and_truncate():
    assert looks_like_scanned("", 100) is True
    assert looks_like_scanned("hi", 100) is True
    assert looks_like_scanned("a" * 50, 100) is False
    assert looks_like_scanned("a" * 100, 60_000) is True  # large + sparse
    assert looks_like_scanned("a" * 250, 60_000) is False

    body, clipped = truncate_for_prompt("x" * 100, limit=50)
    assert clipped is True
    assert len(body) == 50
    body2, clipped2 = truncate_for_prompt("short", limit=50)
    assert clipped2 is False
    assert body2 == "short"


def test_parsed_copy_path():
    assert parsed_copy_path("attachments/report.docx") == "attachments/report.docx.md"


async def test_extract_office_bytes_ok_and_skip(tmp_path: Path):
    with patch(
        "agentcore.workspace.attachment_parse._convert_with_markitdown",
        return_value="# Title\n\nEnough alphanumeric content for the scan heuristic here.",
    ):
        ok = await extract_office_bytes(b"PK-fake", ext=".docx")
    assert ok.status == ParseStatus.OK
    assert "Enough alphanumeric" in ok.text

    skipped = await extract_office_bytes(b"PK", ext=".xlsx")
    assert skipped.status == ParseStatus.SKIPPED
    assert skipped.detail.startswith("skip_ext")


async def test_preparse_docx_writes_md_copy(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "brief.docx").write_bytes(b"PK-fake-docx")

    with patch(
        "agentcore.workspace.attachment_parse._convert_with_markitdown",
        return_value="# Brief\n\nHello from docx with enough alphanumeric body for the scan heuristic.",
    ):
        result = await preparse_resident(
            ws, workspace_path="attachments/brief.docx", name="brief.docx"
        )

    assert result.status == ParseStatus.OK
    assert result.parsed_workspace_path == "attachments/brief.docx.md"
    assert "Hello from docx" in result.text
    assert (tmp_path / "attachments" / "brief.docx.md").read_text(encoding="utf-8").startswith(
        "# Brief"
    )


async def test_preparse_pdf_success_via_persist(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "paper.pdf").write_bytes(b"%PDF-fake")

    with patch(
        "agentcore.workspace.attachment_parse._convert_with_markitdown",
        return_value="Abstract\n\nThis paper studies agents." + ("x" * 20),
    ):
        out = await persist_attachments(
            ws,
            [
                {
                    "name": "paper.pdf",
                    "path": "attachments/paper.pdf",
                    "text": "",
                    "binary": True,
                    "workspace_path": "attachments/paper.pdf",
                }
            ],
        )

    assert out[0]["parse_status"] == "ok"
    assert out[0]["parsed_workspace_path"] == "attachments/paper.pdf.md"
    assert "This paper studies agents" in out[0]["text"]
    assert (tmp_path / "attachments" / "paper.pdf.md").exists()


async def test_preparse_scanned_pdf_writes_notice(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "scan.pdf").write_bytes(b"%PDF" + b"\x00" * 100)

    with patch(
        "agentcore.workspace.attachment_parse._convert_with_markitdown",
        return_value="   \n",  # empty text layer
    ):
        result = await preparse_resident(
            ws, workspace_path="attachments/scan.pdf", name="scan.pdf"
        )

    assert result.status == ParseStatus.SCANNED
    assert "scanned" in result.text.lower() or "OCR" in result.text
    assert result.parsed_workspace_path == "attachments/scan.pdf.md"
    note = (tmp_path / "attachments" / "scan.pdf.md").read_text(encoding="utf-8")
    assert "OCR" in note


async def test_preparse_xlsx_skipped(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "report.xlsx").write_bytes(b"PK\x03\x04")

    out = await persist_attachments(
        ws,
        [
            {
                "name": "report.xlsx",
                "path": "attachments/report.xlsx",
                "text": "",
                "binary": True,
                "workspace_path": "attachments/report.xlsx",
            }
        ],
    )
    assert out[0]["parse_status"] == "skipped"
    assert "parsed_workspace_path" not in out[0]
    assert not (out[0].get("text") or "").strip()
    assert not (tmp_path / "attachments" / "report.xlsx.md").exists()
    # Original untouched.
    assert (tmp_path / "attachments" / "report.xlsx").read_bytes() == b"PK\x03\x04"


async def test_preparse_failure_falls_back(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "broken.docx").write_bytes(b"not-a-docx")

    with patch(
        "agentcore.workspace.attachment_parse._convert_with_markitdown",
        side_effect=RuntimeError("boom"),
    ):
        out = await persist_attachments(
            ws,
            [
                {
                    "name": "broken.docx",
                    "path": "attachments/broken.docx",
                    "text": "",
                    "binary": True,
                    "workspace_path": "attachments/broken.docx",
                }
            ],
        )

    assert out[0]["parse_status"] == "failed"
    assert not (out[0].get("text") or "").strip()
    assert out[0]["workspace_path"] == "attachments/broken.docx"
    assert not (tmp_path / "attachments" / "broken.docx.md").exists()

    # Prompt steers file_read for office/PDF — not code_execute.
    ctx = await _build_attachment_context(out)
    assert ctx is not None
    assert "[binary / office-pdf]" in ctx
    assert "file_read" in ctx
    assert "do not default to code_execute" in ctx
    assert "openpyxl" not in ctx


async def test_context_preparsed_inline_and_large_truncation():
    small = {
        "name": "a.docx",
        "path": "attachments/a.docx",
        "binary": True,
        "workspace_path": "attachments/a.docx",
        "parsed_workspace_path": "attachments/a.docx.md",
        "parse_status": "ok",
        "text": "Hello world from docx extract.",
    }
    out = await _build_attachment_context([small])
    assert out is not None
    assert "Hello world from docx extract" in out
    assert "pre-parsed → attachments/a.docx.md" in out
    assert "pre-parsed at upload" in out

    huge_text = "Z" * (ATTACHMENT_INLINE_MAX_CHARS + 500)
    large = {
        **small,
        "name": "big.docx",
        "text": huge_text,
        "parsed_workspace_path": "attachments/big.docx.md",
        "workspace_path": "attachments/big.docx",
    }
    out2 = await _build_attachment_context([large])
    assert out2 is not None
    assert "truncated" in out2
    assert "full extracted text is at attachments/big.docx.md" in out2
    # Inline body capped.
    assert "Z" * (ATTACHMENT_INLINE_MAX_CHARS + 1) not in out2


async def test_context_scanned_shows_notice():
    out = await _build_attachment_context(
        [
            {
                "name": "scan.pdf",
                "path": "attachments/scan.pdf",
                "binary": True,
                "workspace_path": "attachments/scan.pdf",
                "parsed_workspace_path": "attachments/scan.pdf.md",
                "parse_status": "scanned",
                "text": "This file appears to be a scanned / image-only document.",
            }
        ]
    )
    assert out is not None
    assert "scanned / no text layer" in out
    assert "image-only" in out


async def test_plain_txt_binary_resident_decodes(tmp_path: Path):
    ws = _ws(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "notes.txt").write_text("plain notes\n", encoding="utf-8")

    result = await preparse_resident(
        ws, workspace_path="attachments/notes.txt", name="notes.txt"
    )
    assert result.status == ParseStatus.OK
    assert result.parsed_workspace_path == "attachments/notes.txt"
    assert "plain notes" in result.text
    # No redundant .md for already-text originals.
    assert not (tmp_path / "attachments" / "notes.txt.md").exists()


async def test_preparse_read_failure_is_failed_not_raise(tmp_path: Path):
    ws = _ws(tmp_path)
    # File missing → read_bytes raises WorkspaceError subclass.
    result = await preparse_resident(
        ws, workspace_path="attachments/missing.docx", name="missing.docx"
    )
    assert result.status == ParseStatus.FAILED
    assert "read" in result.detail

"""Export a workspace Markdown file to a sibling .docx via the shared converter."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentcore.docs_export.md_to_docx import (
    collect_image_srcs,
    convert_markdown_to_docx,
    docx_path_for_markdown,
    is_embeddable_relative_src,
    resolve_workspace_image_path,
)
from agentcore.workspace.protocol import (
    NotAFile,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceBackend,
    WorkspaceError,
)


@dataclass(frozen=True)
class ExportMarkdownResult:
    """Outcome of exporting one Markdown path inside a workspace."""

    source_path: str
    output_path: str
    size_bytes: int
    warnings: list[str] = field(default_factory=list)


class ExportMarkdownError(Exception):
    """User-facing export failure (invalid path / missing source / I/O)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def export_markdown_path(
    backend: WorkspaceBackend,
    md_path: str,
) -> ExportMarkdownResult:
    """Read ``md_path``, convert, write sibling ``.docx``. Raises ``ExportMarkdownError``."""
    rel = (md_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        raise ExportMarkdownError("path 不能为空：请提供工作区内的 .md 相对路径")
    lower = rel.lower()
    if not (lower.endswith(".md") or lower.endswith(".markdown")):
        raise ExportMarkdownError(f"仅支持 Markdown 文件（.md / .markdown）：{rel}")

    try:
        markdown = await backend.read(rel)
    except PathNotFound as e:
        raise ExportMarkdownError(f"源文件不存在：{rel}") from e
    except NotAFile as e:
        raise ExportMarkdownError(f"不是文件：{rel}") from e
    except OutsideWorkspace as e:
        raise ExportMarkdownError("路径非法：超出工作区范围") from e
    except WorkspaceError as e:
        raise ExportMarkdownError(f"读取源文件失败：{e}") from e

    image_bytes: dict[str, bytes | None] = {}
    for src in collect_image_srcs(markdown):
        if not is_embeddable_relative_src(src):
            # Converter will warn; no lookup.
            continue
        ws_img = resolve_workspace_image_path(rel, src)
        if ws_img is None:
            image_bytes[src] = None
            continue
        try:
            image_bytes[src] = await backend.read_bytes(ws_img)
        except (PathNotFound, NotAFile, OutsideWorkspace):
            image_bytes[src] = None
        except WorkspaceError:
            image_bytes[src] = None

    result = convert_markdown_to_docx(markdown, images=image_bytes)
    out_path = docx_path_for_markdown(rel)
    try:
        written = await backend.write_bytes(out_path, result.docx_bytes)
    except OutsideWorkspace as e:
        raise ExportMarkdownError("输出路径非法：超出工作区范围") from e
    except WorkspaceError as e:
        raise ExportMarkdownError(f"写入 Word 失败：{e}") from e

    return ExportMarkdownResult(
        source_path=rel,
        output_path=out_path,
        size_bytes=written,
        warnings=list(result.warnings),
    )

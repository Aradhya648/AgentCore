"""Built-in tool: grep — regex search over workspace file CONTENTS.

Complements the rest of the file family: ``file_list`` finds files by NAME and
``file_read`` opens one file, while ``grep`` finds WHERE a string / symbol /
pattern appears across many files, returning ripgrep-style ``path:line: text``
hits the model can then open with ``file_read``.

Thin shell over ``ToolContext.backend``: this tool validates the regex, builds a
``GrepQuery``, and renders the bounded ``GrepResult`` the backend returns. The
actual walk (ignore-dir pruning, size caps, binary filter, match caps) lives in
the backend so it runs identically against a server or local workspace.
"""

import re
import time
from typing import Any

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    ToolRegistration,
    ToolSurface,
)
from agentcore.workspace.protocol import (
    GrepQuery,
    GrepResult,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceError,
)

_DEFAULT_MAX_RESULTS = 50
_MAX_RESULTS_CAP = 200
# grep output is line-oriented and denser than the 4000-char default; lift it so
# a full (already capped) result set is never truncated into a partial last line.
_OUTPUT_LIMIT = 16000


class GrepTool:
    """Search file CONTENTS across the workspace by regular expression."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep",
            description=(
                "用正则表达式搜索工作区内文件的【内容】（Python `re` 语法，类似 "
                "ripgrep）。用它来定位某个符号、函数、字符串或任意文本【出现在"
                "哪里】——返回形如 `path:line: text` 的匹配行，再用 `file_read` "
                "打开周边代码。要按【文件名】找文件请改用 `file_list`。会跳过"
                "二进制文件与噪音目录（.git、node_modules、缓存）。用 `path` 和/或 "
                "`glob` 收窄范围可更快更准。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "要搜索的正则表达式（Python re 语法）。",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "搜索范围：相对【目录】或【单个文件】（默认：工作区"
                            "根目录）。传目录则递归其下；传单个文件则只搜该文件"
                            "（类似 `rg PATTERN FILE`，此时 glob 被忽略）。"
                        ),
                        "default": ".",
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "可选：按【文件名】过滤，如 '*.py' 或 '*.ts'。开头的 "
                            "'**/' 或目录前缀会被忽略，只匹配文件名。"
                        ),
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "不区分大小写匹配（默认 false）。",
                        "default": False,
                    },
                    "files_only": {
                        "type": "boolean",
                        "description": (
                            "只返回匹配到的文件列表及每个文件的匹配数，而非匹配行（默认 false）。"
                        ),
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "返回的最大匹配行数（files_only 模式下为文件数）。默认 50，最多 200。"
                        ),
                    },
                },
                "required": ["pattern"],
            },
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()

        pattern = arguments.get("pattern") or ""
        if not pattern:
            return _fail("缺少必填参数：pattern", start)

        flags = re.IGNORECASE if arguments.get("case_insensitive") else 0
        try:
            re.compile(pattern, flags)
        except re.error as e:
            return _fail(f"正则表达式无效：{e}", start)

        rel_dir = arguments.get("path") or "."
        files_only = bool(arguments.get("files_only", False))
        try:
            raw = int(arguments.get("max_results", _DEFAULT_MAX_RESULTS))
            max_results = max(1, min(raw, _MAX_RESULTS_CAP))
        except (TypeError, ValueError):
            max_results = _DEFAULT_MAX_RESULTS

        query = GrepQuery(
            pattern=pattern,
            directory=rel_dir,
            glob=arguments.get("glob") or None,
            case_insensitive=bool(arguments.get("case_insensitive")),
            files_only=files_only,
            max_results=max_results,
        )

        try:
            result = await context.backend.grep(query)
        except OutsideWorkspace:
            return _fail(_outside_workspace_msg(rel_dir), start)
        except PathNotFound:
            return _fail(f"路径不存在：{rel_dir}", start)
        except WorkspaceError as e:
            return _fail(f"搜索失败：{e}", start)

        output = _render(
            pattern=pattern,
            rel_dir=rel_dir,
            glob=arguments.get("glob") or "",
            result=result,
            files_only=files_only,
        )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            output_limit=_OUTPUT_LIMIT,
            metadata={
                "match_count": result.total_matches,
                "file_count": len(result.file_counts),
            },
        )


def _fail(error: str, start: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _outside_workspace_msg(path: str) -> str:
    """Actionable OutsideWorkspace text (mirrors ``file_ops``): the usual cause is an
    absolute ``/workspace/...`` path the guard refuses, so point at the relative-path
    fix with a concrete example instead of a bare "out of range"."""
    return (
        f"路径 '{path}' 超出了工作区范围。请改用相对工作区根目录的【相对路径】"
        "（不要用 /workspace/... 这类绝对路径），例如 research/report.md。"
    )


def _render(
    *,
    pattern: str,
    rel_dir: str,
    glob: str,
    result: GrepResult,
    files_only: bool,
) -> str:
    if files_only:
        lines = [f"{rel}: {count}" for rel, count in result.file_counts]
        summary = f"{len(result.file_counts)} 个文件匹配 /{pattern}/"
    else:
        lines = [f"{h.path}:{h.line_no}: {h.text}" for h in result.hits]
        summary = (
            f"{result.total_matches} 处匹配，分布在 "
            f"{len(result.file_counts)} 个文件中（/{pattern}/）"
        )

    if not lines:
        scope = "" if rel_dir in ("", ".") else f"（在 '{rel_dir}' 下）"
        glob_note = f"（文件名匹配 '{glob}'）" if glob else ""
        return f"没有匹配 /{pattern}/{scope}{glob_note}。"

    body = "\n".join(lines)
    if result.truncated:
        body += "\n[结果已截断——请收窄 path/glob 或细化 pattern]"
    return f"{summary}\n{body}"

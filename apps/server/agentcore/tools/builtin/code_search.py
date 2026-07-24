"""Built-in tool: code_search — BM25 symbol-level code search.

Complements ``grep``: ``grep`` finds exact regex matches line-by-line; ``code_search``
indexes functions/classes/methods (tree-sitter) and ranks by BM25 so the model can
locate code by concept or keyword across files.
"""

import time
from typing import Any

from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    ToolRegistration,
    ToolSurface,
)
from agentcore.workspace.protocol import CodeSearchResult, WorkspaceError

_DEFAULT_MAX_RESULTS = 10
_MAX_RESULTS_CAP = 50
_OUTPUT_LIMIT = 16000

CODE_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "自然语言或关键词查询（如「审批门控」「User model」）。",
        },
        "language": {
            "type": "string",
            "description": "可选：按语言过滤，如 python、typescript、tsx。",
        },
        "path_prefix": {
            "type": "string",
            "description": "搜索范围：相对目录前缀（默认工作区根目录）。",
            "default": ".",
        },
        "max_results": {
            "type": "integer",
            "description": (
                f"返回的最大结果数（默认 {_DEFAULT_MAX_RESULTS}，最多 {_MAX_RESULTS_CAP}）。"
            ),
        },
    },
    "required": ["query"],
}


class CodeSearchTool:
    """Search workspace code by intent (BM25 over symbol-level chunks)."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="code_search",
            description=(
                "按意图搜索工作区代码。支持自然语言或关键词查询，返回匹配的代码块"
                "（函数、类、方法）及其位置。用于概念搜索、跨文件定位等场景。"
                "精确正则匹配请用 grep。"
            ),
            parameters=CODE_SEARCH_PARAMETERS,
            category=ToolCategory.FILESYSTEM,
            approval=ToolApproval.NEVER,
            timeout_seconds=30.0,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        query = (arguments.get("query") or "").strip()
        if not query:
            return _fail("缺少必填参数：query", start)

        try:
            raw = int(arguments.get("max_results", _DEFAULT_MAX_RESULTS))
            max_results = max(1, min(raw, _MAX_RESULTS_CAP))
        except (TypeError, ValueError):
            max_results = _DEFAULT_MAX_RESULTS

        language = arguments.get("language") or None
        path_prefix = arguments.get("path_prefix") or "."

        try:
            await context.backend.ensure_code_index()
            result = await context.backend.code_search(
                query,
                language=language,
                path_prefix=path_prefix,
                max_results=max_results,
            )
        except WorkspaceError as e:
            return _fail(f"搜索失败：{e}", start)

        output = _render(result)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            output_limit=_OUTPUT_LIMIT,
            metadata={"match_count": len(result.chunks)},
        )


def _fail(error: str, start: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _render(result: CodeSearchResult) -> str:
    if not result.chunks:
        body = "没有匹配的代码块。"
        if result.index_stale:
            body += "\n⚠️ 索引可能过旧，建议配合 grep 验证。"
        return body

    lines: list[str] = []
    for chunk, score in zip(result.chunks, result.scores, strict=True):
        symbol_part = ""
        if chunk.symbol:
            symbol_part = f"  {chunk.symbol}"
            if chunk.symbol_type:
                symbol_part += f" ({chunk.symbol_type})"
        header = (
            f"{chunk.path}:{chunk.start_line}-{chunk.end_line}{symbol_part} "
            f"({chunk.language})"
        )
        preview = chunk.snippet.replace("\n", "\n  ")
        lines.append(f"{header}\n  {preview}\n  score={score:.2f}")

    summary = (
        f"（共 {len(result.chunks)} 条结果；用 file_read path offset/limit 查看全文）"
    )
    body = "\n\n".join(lines) + f"\n\n{summary}"
    if result.index_stale:
        body += "\n⚠️ 索引可能过旧，建议配合 grep 验证。"
    return body

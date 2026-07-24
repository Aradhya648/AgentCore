"""Tree-sitter symbol-boundary chunking with fixed-line fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_FALLBACK_LINES_PER_CHUNK = 50
_SNIPPET_PREVIEW_LINES = 3

# Phase 2a languages with tree-sitter grammars.
_TS_LANGUAGES: dict[str, tuple[str, ...]] = {
    "python": ("function_definition", "class_definition"),
    "typescript": (
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ),
    "tsx": (
        "function_declaration",
        "class_declaration",
        "method_definition",
        "arrow_function",
        "export_statement",
    ),
}

_SYMBOL_TYPE: dict[str, str] = {
    "function_definition": "function",
    "function_declaration": "function",
    "arrow_function": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "method_definition": "method",
}

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mts": "typescript",
    ".cts": "typescript",
}

_tree_sitter_available: bool | None = None
_parsers: dict[str, object] = {}


@dataclass(frozen=True)
class RawChunk:
    """One indexable code block."""

    path: str
    symbol: str | None
    symbol_type: str | None
    start_line: int
    end_line: int
    language: str
    content: str


def detect_language(path: str) -> str:
    """Map a file path to a chunking language id (or ``unknown``)."""
    lower = path.lower()
    for ext, lang in _EXT_TO_LANGUAGE.items():
        if lower.endswith(ext):
            return lang
    return "unknown"


def snippet_preview(content: str, *, max_lines: int = _SNIPPET_PREVIEW_LINES) -> str:
    """First few lines of ``content`` for search-result previews."""
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines])


async def chunk_file(path: str, content: str, language: str) -> list[RawChunk]:
    """Chunk ``content`` by symbol boundaries (tree-sitter) or fixed lines."""
    if language in _TS_LANGUAGES and _ensure_tree_sitter():
        chunks = _chunk_with_tree_sitter(path, content, language)
        if chunks:
            return chunks
    return _chunk_fixed_lines(path, content, language)


def _ensure_tree_sitter() -> bool:
    global _tree_sitter_available
    if _tree_sitter_available is not None:
        return _tree_sitter_available
    try:
        from tree_sitter import Language, Parser  # noqa: F401

        _tree_sitter_available = True
    except ImportError as exc:
        logger.warning("tree-sitter not available (%s); using fixed-line chunking", exc)
        _tree_sitter_available = False
    return _tree_sitter_available


def _get_parser(language: str):
    if language in _parsers:
        return _parsers[language]
    from tree_sitter import Language, Parser

    if language == "python":
        import tree_sitter_python as tspython

        lang = Language(tspython.language())
    elif language == "typescript":
        from tree_sitter_typescript import language_typescript

        lang = Language(language_typescript())
    elif language == "tsx":
        from tree_sitter_typescript import language_tsx

        lang = Language(language_tsx())
    else:
        return None

    parser = Parser(lang)
    _parsers[language] = parser
    return parser


def _chunk_with_tree_sitter(path: str, content: str, language: str) -> list[RawChunk]:
    parser = _get_parser(language)
    if parser is None:
        return []

    source = content.encode("utf-8")
    try:
        tree = parser.parse(source)
    except Exception:
        logger.debug("tree-sitter parse failed for %s", path, exc_info=True)
        return []

    root = tree.root_node
    if root.has_error:
        return []

    symbol_types = _TS_LANGUAGES[language]
    chunks: list[RawChunk] = []
    seen_spans: set[tuple[int, int]] = set()

    def visit(node) -> None:
        if node.type in symbol_types:
            span = (node.start_byte, node.end_byte)
            if span not in seen_spans:
                seen_spans.add(span)
                symbol = _extract_symbol_name(node, source)
                sym_type = _symbol_type_for(node, language)
                if node.type == "export_statement":
                    inner = _export_inner_symbol(node)
                    if inner is not None:
                        symbol = _extract_symbol_name(inner, source) or symbol
                        sym_type = _symbol_type_for(inner, language) or sym_type
                        span = (inner.start_byte, inner.end_byte)
                start_line = source[: node.start_byte].count(b"\n") + 1
                end_line = source[: node.end_byte].count(b"\n") + 1
                chunk_content = source[node.start_byte : node.end_byte].decode("utf-8")
                if chunk_content.strip():
                    chunks.append(
                        RawChunk(
                            path=path,
                            symbol=symbol,
                            symbol_type=sym_type,
                            start_line=start_line,
                            end_line=end_line,
                            language=language,
                            content=chunk_content,
                        )
                    )
        for child in node.children:
            visit(child)

    visit(root)
    return chunks


def _export_inner_symbol(node):
    for child in node.children:
        if child.type in _SYMBOL_TYPE or child.type in (
            "function_declaration",
            "class_declaration",
            "lexical_declaration",
        ):
            return child
    return None


def _extract_symbol_name(node, source: bytes) -> str | None:
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier"):
            return source[child.start_byte : child.end_byte].decode("utf-8")
        if child.type == "function":
            for sub in child.children:
                if sub.type == "identifier":
                    return source[sub.start_byte : sub.end_byte].decode("utf-8")
    return None


def _symbol_type_for(node, language: str) -> str | None:
    if node.type == "export_statement":
        inner = _export_inner_symbol(node)
        if inner is not None:
            return _SYMBOL_TYPE.get(inner.type)
        return None
    if node.type in _SYMBOL_TYPE:
        return _SYMBOL_TYPE[node.type]
    if node.type == "lexical_declaration":
        return "function"
    return None


def _chunk_fixed_lines(path: str, content: str, language: str) -> list[RawChunk]:
    lines = content.splitlines()
    if not lines:
        return []

    chunks: list[RawChunk] = []
    for start_idx in range(0, len(lines), _FALLBACK_LINES_PER_CHUNK):
        end_idx = min(start_idx + _FALLBACK_LINES_PER_CHUNK, len(lines))
        chunk_content = "\n".join(lines[start_idx:end_idx])
        chunks.append(
            RawChunk(
                path=path,
                symbol=None,
                symbol_type=None,
                start_line=start_idx + 1,
                end_line=end_idx,
                language=language,
                content=chunk_content,
            )
        )
    return chunks

"""Unit tests for the global-search pure helpers (全局搜索 Tier 1).

The snippet windowing (the offsets the client highlights with), the ``types`` CSV
parsing, and the ILIKE wildcard escaping are pure logic — covered here without a
DB. See ``docs/04-前端/前端技术与架构.md`` §9.8.
"""

from agentcore.api.routes.search import _message_snippet, _parse_types
from agentcore.db.repositories import _ilike_pattern


class TestIlikePattern:
    def test_wraps_query_as_substring(self) -> None:
        assert _ilike_pattern("deploy") == "%deploy%"

    def test_escapes_like_wildcards(self) -> None:
        # %, _ and the escape char are neutralized so user input can't act as a
        # wildcard — "50%" must match the literal text, not become match-all.
        assert _ilike_pattern("50%") == "%50\\%%"
        assert _ilike_pattern("a_b") == "%a\\_b%"
        assert _ilike_pattern("a\\b") == "%a\\\\b%"


class TestParseTypes:
    def test_none_returns_all(self) -> None:
        assert _parse_types(None) == {"conversation", "message", "folder"}

    def test_empty_returns_all(self) -> None:
        assert _parse_types("") == {"conversation", "message", "folder"}

    def test_subset(self) -> None:
        assert _parse_types("message,folder") == {"message", "folder"}

    def test_strips_whitespace_and_ignores_unknown(self) -> None:
        assert _parse_types(" message , bogus ") == {"message"}

    def test_all_invalid_falls_back_to_all(self) -> None:
        # A typo shouldn't silently return nothing — lenient fallback to all.
        assert _parse_types("bogus,nope") == {
            "conversation",
            "message",
            "folder",
        }


class TestMessageSnippet:
    def test_short_content_returned_whole_with_offsets(self) -> None:
        snippet, start, end = _message_snippet("hello world", "world")
        assert snippet == "hello world"
        assert start is not None and end is not None
        assert snippet[start:end] == "world"

    def test_centers_window_and_marks_truncation(self) -> None:
        content = "x" * 100 + "needle" + "y" * 100
        snippet, start, end = _message_snippet(content, "needle")
        assert snippet.startswith("…")
        assert snippet.endswith("…")
        assert start is not None and end is not None
        # Offsets index into the returned snippet (ellipses accounted for).
        assert snippet[start:end] == "needle"

    def test_case_insensitive_match_keeps_original_casing(self) -> None:
        snippet, start, end = _message_snippet("The DEPLOY step", "deploy")
        assert start is not None and end is not None
        assert snippet[start:end] == "DEPLOY"

    def test_no_match_falls_back_to_prefix_without_offsets(self) -> None:
        snippet, start, end = _message_snippet("abc", "zzz")
        assert snippet == "abc"
        assert start is None
        assert end is None

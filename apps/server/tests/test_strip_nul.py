"""Unit tests for repository-layer NUL stripping (Postgres text/JSONB)."""

from agentcore.db.repositories._base import strip_nul


def test_strip_nul_removes_null_bytes_from_str():
    assert strip_nul("a\x00b\x00c") == "abc"
    assert strip_nul("clean") == "clean"
    assert strip_nul("") == ""


def test_strip_nul_recurses_dict_list():
    payload = {
        "result": "ok\x00",
        "nested": {"stdout": "line\x00line"},
        "items": ["a\x00", {"x": "\x00y"}],
    }
    assert strip_nul(payload) == {
        "result": "ok",
        "nested": {"stdout": "lineline"},
        "items": ["a", {"x": "y"}],
    }


def test_strip_nul_preserves_non_strings():
    assert strip_nul(None) is None
    assert strip_nul(42) == 42
    assert strip_nul(True) is True
    assert strip_nul(b"\x00") == b"\x00"  # bytes columns are not text/jsonb strings

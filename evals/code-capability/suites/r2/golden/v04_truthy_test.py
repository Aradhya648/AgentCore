"""GOLDEN · flask.truthy（R2 Extend；评测追加，勿改 upstream 测）."""

from flask import truthy


def test_smoke_existing_get_debug_flag():
    from flask.helpers import get_debug_flag

    assert callable(get_debug_flag)


def test_truthy_values():
    assert truthy("1") is True
    assert truthy("yes") is True
    assert truthy("TRUE") is True
    assert truthy("0") is False
    assert truthy("false") is False
    assert truthy("no") is False
    assert truthy(None) is False
    assert truthy("") is False

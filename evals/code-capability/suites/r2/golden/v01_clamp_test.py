"""GOLDEN · click.clamp（R2 Extend；评测追加，勿改 upstream 测）."""

import pytest

from click import clamp


def test_smoke_existing_format_filename():
    from click import format_filename

    assert callable(format_filename)


def test_clamp_in_range():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(99, 0, 10) == 10


def test_clamp_bad_bounds():
    with pytest.raises(ValueError):
        clamp(1, 10, 0)

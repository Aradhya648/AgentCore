"""Tests for hello_cli — covers greet, add, and help."""

import pytest

from hello_cli.cli import build_parser, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(argv, capsys):
    """Run main(argv) and return (exit_code, stdout, stderr)."""
    with pytest.raises(SystemExit) as exc:
        main(argv)
    exc_code = exc.value.code
    out, err = capsys.readouterr()
    return exc_code, out, err


# ---------------------------------------------------------------------------
# greet
# ---------------------------------------------------------------------------

def test_greet_prints_hello(capsys):
    code, out, _ = _run(["greet", "Ada"], capsys)
    assert code == 0
    assert "Hello, Ada" in out


def test_greet_with_spaces_in_name(capsys):
    code, out, _ = _run(["greet", "  Bob  "], capsys)
    assert code == 0
    assert "Hello, Bob" in out


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

def test_add_basic(capsys):
    code, out, _ = _run(["add", "2", "3"], capsys)
    assert code == 0
    assert "5" in out


def test_add_negative_numbers(capsys):
    code, out, _ = _run(["add", "-1", "1"], capsys)
    assert code == 0
    assert "0" in out


# ---------------------------------------------------------------------------
# help / parser
# ---------------------------------------------------------------------------

def test_help_flag(capsys):
    code, out, _ = _run(["--help"], capsys)
    assert code == 0
    assert "usage" in out.lower()
    assert "greet" in out
    assert "add" in out


def test_parser_subcommands():
    parser = build_parser()
    # Should parse without error
    args = parser.parse_args(["greet", "X"])
    assert args.name == "X"
    args = parser.parse_args(["add", "3", "4"])
    assert args.a == 3 and args.b == 4

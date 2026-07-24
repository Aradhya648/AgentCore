"""Tests for hello_cli package."""

import pytest

from hello_cli.__main__ import build_parser, main


class TestGreet:
    def test_greet_prints_hello_name(self, capsys):
        exit_code = main(["greet", "Ada"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Hello, Ada" in captured.out

    def test_greet_with_spaces_in_name(self, capsys):
        exit_code = main(["greet", "Ada Lovelace"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Hello, Ada Lovelace" in captured.out


class TestAdd:
    def test_add_two_positive_integers(self, capsys):
        exit_code = main(["add", "2", "3"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip() == "5"

    def test_add_negative_numbers(self, capsys):
        exit_code = main(["add", "-1", "5"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out.strip() == "4"


class TestRunPlan:
    def test_run_plan_prints_commands(self, capsys):
        exit_code = main(["run_plan"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "greet" in captured.out
        assert "add" in captured.out


class TestHelp:
    def test_help_flag_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_shows_help(self, capsys):
        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "usage" in captured.out.lower()

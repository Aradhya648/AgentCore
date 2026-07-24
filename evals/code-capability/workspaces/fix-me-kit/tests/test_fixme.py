from fixme.cli import main
from fixme.greet import greet
from fixme.mathops import add


def test_add_two_plus_three():
    assert add(2, 3) == 5


def test_greet_title_and_comma():
    assert greet("ada") == "Hello, Ada"


def test_cli_multiply(capsys):
    assert main(["multiply", "4", "5"]) == 0
    assert capsys.readouterr().out.strip() == "20"

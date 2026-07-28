"""GOLDEN · click.snake_case（R2 Extend；评测追加，勿改 upstream 测）."""

from click import snake_case


def test_smoke_existing_echo():
    from click import echo

    assert callable(echo)


def test_snake_case_basic():
    assert snake_case("Hello World") == "hello_world"
    assert snake_case("Already_ok") == "already_ok"
    assert snake_case("  spaced   words ") == "spaced_words"

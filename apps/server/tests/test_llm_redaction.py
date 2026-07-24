"""Secret-redaction tests for the (debug-only) LLM body capture.

The capture is off by default and truncated; this guards the defence-in-depth scrub
(``_redact``) so a key pasted into a prompt never lands in a log line (SEC-001).
"""

from agentcore.llm.observability import _redact

_REDACTED = "[REDACTED]"


def test_redacts_openai_style_key():
    assert _redact("use sk-abcdEFGH1234567890 now") == f"use {_REDACTED} now"


def test_redacts_anthropic_hyphenated_key():
    # sk-ant-… has hyphens inside the body; the widened body class must still catch it.
    assert _redact("key=sk-ant-api03-AbCd1234EfGh") == f"key={_REDACTED}"


def test_redacts_vendor_prefixes():
    for token in (
        "tvly-abcd1234efgh5678",          # Tavily
        "gsk_abcd1234EFGH5678ijkl",       # Groq
        "xai-ABCDabcd12345678",           # xAI
        "AIzaSyA0bCdEfGhIjKlMnOpQr",      # Google
        "ghp_abcdefghij0123456789ABCD",   # GitHub PAT
    ):
        assert _redact(f"token {token} end") == f"token {_REDACTED} end", token


def test_redacts_bearer_token():
    assert _redact("Authorization: Bearer abcDEF123456._-x") == f"Authorization: {_REDACTED}"


def test_leaves_ordinary_prose_untouched():
    text = "The api returns a list of items; see the docs for details."
    assert _redact(text) == text

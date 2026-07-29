"""Unit tests for sandbox browser netns capability-error classification."""

from __future__ import annotations

from agentcore.tools.sandbox.browser.netns import (
    EGRESS_UNAVAILABLE_CODE,
    NetnsError,
    is_netns_capability_error,
)
from agentcore.tools.sandbox.browser.protocol import BrowserSessionError


def test_netns_error_is_capability_failure():
    assert is_netns_capability_error(
        NetnsError("ip netns add acbrw0 failed (1): mkdir /run/netns failed: Permission denied")
    )


def test_wrapped_netns_message_is_capability_failure():
    inner = NetnsError("ip netns add x failed (1): mkdir /run/netns failed: Permission denied")
    outer = BrowserSessionError(f"浏览器会话启动失败：NetnsError: {inner}")
    outer.__cause__ = inner
    assert is_netns_capability_error(outer)


def test_string_only_netns_legacy_wrap_classifies():
    exc = BrowserSessionError(
        "浏览器会话启动失败：NetnsError: ip netns add acbrw0 failed (1): "
        "mkdir /run/netns failed: Permission denied"
    )
    assert is_netns_capability_error(exc)


def test_unrelated_session_error_is_not_capability_failure():
    assert not is_netns_capability_error(BrowserSessionError("浏览器启动失败：timeout"))
    assert not is_netns_capability_error(RuntimeError("connection reset"))


def test_egress_unavailable_code_constant():
    assert EGRESS_UNAVAILABLE_CODE == "egress_unavailable"

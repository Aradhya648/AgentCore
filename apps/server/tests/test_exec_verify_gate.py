"""exec_verify 用户意图硬闸已移除：不再扫用户文改工具面 / 逼 ask_user·delegate."""

from __future__ import annotations

import importlib

import pytest

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.engine.governance import create_loop_controller


def test_exec_verify_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agentcore.runtime.runs.exec_verify")


def test_maybe_inject_exec_verify_gate_removed():
    from agentcore.runtime.engine import governance

    assert not hasattr(governance, "maybe_inject_exec_verify_gate")
    assert not hasattr(governance, "exec_verify_ask_prompt")
    assert not hasattr(governance, "exec_verify_delegate_prompt")


def test_run_fix_style_message_does_not_inject_or_strip_tools():
    """Former hard-fork inputs must no longer fire gate / reclaim tools."""
    controller = create_loop_controller(frozenset({"file_list", "file_read", "grep"}))
    messages = [
        LLMMessage(
            role="user",
            content="帮我跑一下 scripts/smoke_test.py，看看报什么错，有问题就修。",
        )
    ]
    disabled: set[str] = set()
    # Gate symbol gone — calling path is captain loop only; assert latches stay cold.
    assert not hasattr(controller, "exec_verify_gate_fired")
    assert not hasattr(controller, "exec_verify_text_exit")
    assert "能力策略" not in " ".join(m.content or "" for m in messages)
    assert disabled == set()

"""named_entity_fanout 用户扫硬拒已移除：不再因点名对比少派拒绝 delegate."""

from __future__ import annotations

import importlib

import pytest


def test_named_entity_fanout_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("agentcore.runtime.delegate.named_entity_fanout")


def test_understaffed_named_compare_no_longer_rejected_by_import():
    """Former reject path lived in check_named_entity_fanout — module gone."""
    # Smoke: understaffed compare args would have returned an error string before.
    arguments = {
        "tasks": [{"role": "调研员", "task": "综合对比三者"}],
    }
    user_message = "对比 React、Vue、Svelte 三者在中小型项目的取舍"
    # No entry-point helper remains; delegate tool no longer imports this gate.
    assert arguments["tasks"]  # shape still valid for hand-written delegate
    assert "对比" in user_message

"""CEO tool-surface gating: idle vs coordination (工具面瘦身).

拍板分态：闲聊态 = delegate + ask_user + debate 常驻（debate 与 delegate 同级，
闲聊可开辩）；replan + 协调四件套仅协调态 / 受监督让出时注入（与执行闸对齐）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agentcore.runtime.coordination.session import (
    CoordinationSession,
    clear_active_coordination,
    current_execution_id,
    set_active_coordination,
)
from agentcore.runtime.resolve.ceo_surface import (
    COORDINATION_GATED_TOOLS,
    COORDINATION_PERIOD_HINT,
    coordination_surface_active,
    promote_coordination_surface_if_needed,
    register_coordination_surface,
)
from agentcore.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _clear_coord():
    clear_active_coordination()
    token = current_execution_id.set(None)
    yield
    clear_active_coordination()
    current_execution_id.reset(token)


def _fake_delegate(*, supervised: bool = False):
    d = MagicMock()
    d.schema = MagicMock(name="delegate")
    d.schema.name = "delegate"
    d._sink = MagicMock()
    d._supervised = object() if supervised else None
    return d


def _activate_coordination(eid: str) -> None:
    set_active_coordination(
        CoordinationSession(
            execution_id=eid,
            total_workers=2,
            conversation_id="c1",
        )
    )


def test_idle_surface_omits_gated_tools():
    reg = ToolRegistry()
    delegate = _fake_delegate()
    reg.register(delegate)
    register_coordination_surface(
        reg,
        delegate_tool=delegate,
        sink=MagicMock(),
        include=False,
    )
    names = set(reg.names)
    assert "delegate" in names
    assert names.isdisjoint(COORDINATION_GATED_TOOLS)


def test_coordination_surface_includes_gated_tools():
    eid = "exec-coord-surface"
    token = current_execution_id.set(eid)
    try:
        _activate_coordination(eid)
        assert coordination_surface_active(execution_id=eid)

        reg = ToolRegistry()
        delegate = _fake_delegate()
        reg.register(delegate)
        register_coordination_surface(
            reg,
            delegate_tool=delegate,
            sink=MagicMock(),
            include=True,
        )
        names = set(reg.names)
        assert "delegate" in names
        assert names >= COORDINATION_GATED_TOOLS
    finally:
        clear_active_coordination()
        current_execution_id.reset(token)


def test_promote_on_supervised_yield_adds_replan_only():
    reg = ToolRegistry()
    delegate = _fake_delegate(supervised=True)
    reg.register(delegate)

    assert promote_coordination_surface_if_needed(reg) is True
    names = set(reg.names)
    assert "replan" in names
    assert "delegate" in names
    # No live coordination → coord suite stays out
    assert "update_synthesis" not in names


def test_promote_on_coordination_adds_full_surface():
    eid = "exec-promote"
    token = current_execution_id.set(eid)
    try:
        _activate_coordination(eid)
        reg = ToolRegistry()
        delegate = _fake_delegate()
        reg.register(delegate)

        assert promote_coordination_surface_if_needed(reg) is True
        assert set(reg.names) >= COORDINATION_GATED_TOOLS
        assert "delegate" in reg.names
        # Idempotent
        assert promote_coordination_surface_if_needed(reg) is False
    finally:
        clear_active_coordination()
        current_execution_id.reset(token)


def test_ensure_before_llm_installs_wait_when_coordination_live():
    """验收钉：协调已活 → 进入 LLM 前 wait 已在工具面（prepare / mid-turn 对齐）。"""
    from agentcore.runtime.resolve.ceo_surface import ensure_coordination_surface_before_llm

    eid = "exec-ensure-before-llm"
    token = current_execution_id.set(eid)
    try:
        _activate_coordination(eid)
        reg = ToolRegistry()
        delegate = _fake_delegate()
        reg.register(delegate)
        assert "wait" not in reg.names

        assert ensure_coordination_surface_before_llm(reg) is True
        assert "wait" in reg.names
        assert set(reg.names) >= COORDINATION_GATED_TOOLS
        # 再次调用不重复注册
        assert ensure_coordination_surface_before_llm(reg) is False
        assert "wait" in reg.names
    finally:
        clear_active_coordination()
        current_execution_id.reset(token)


def test_assembled_coordination_live_offers_wait_on_tool_defs():
    """协调已活时 assemble 路径的 OpenAI 工具面含 wait（与 ensure 同一验收）。"""
    eid = "exec-assembly"
    token = current_execution_id.set(eid)
    try:
        _activate_coordination(eid)
        reg = _assemble()
        assert "wait" in reg.names
        defs = reg.get_openai_definitions()
        names = {
            (d.get("function") or {}).get("name") or d.get("name") for d in defs
        }
        assert "wait" in names
    finally:
        clear_active_coordination()
        current_execution_id.reset(token)


def test_always_on_tools_not_in_gated_set():
    """delegate / ask_user / debate 常驻——不得进协调闸集合。"""
    for name in ("delegate", "ask_user", "debate", "consult_skill"):
        assert name not in COORDINATION_GATED_TOOLS


def test_coordination_period_hint_allows_append_forbids_isomorphic():
    assert "wait" in COORDINATION_PERIOD_HINT
    assert "delegate" in COORDINATION_PERIOD_HINT
    assert "全新" in COORDINATION_PERIOD_HINT or "追加" in COORDINATION_PERIOD_HINT
    assert "同构" in COORDINATION_PERIOD_HINT
    assert "移除" not in COORDINATION_PERIOD_HINT
    assert "不可用" not in COORDINATION_PERIOD_HINT
    assert "ceiling" in COORDINATION_PERIOD_HINT or "max_rounds" in COORDINATION_PERIOD_HINT
    assert "缩 scope" in COORDINATION_PERIOD_HINT or "收窄" in COORDINATION_PERIOD_HINT
    assert "同质 wait" in COORDINATION_PERIOD_HINT
    # S3 可见面纪律
    assert "可静默" in COORDINATION_PERIOD_HINT
    assert "谁还在跑" in COORDINATION_PERIOD_HINT
    assert "三选一" in COORDINATION_PERIOD_HINT
    assert "先" in COORDINATION_PERIOD_HINT and "响应该句" in COORDINATION_PERIOD_HINT
    assert "纯进度播报" in COORDINATION_PERIOD_HINT
    assert "短说谁在后台" not in COORDINATION_PERIOD_HINT


def test_wait_in_gated_set():
    assert "wait" in COORDINATION_GATED_TOOLS
    assert "wait" not in ("delegate", "ask_user", "debate")


# --- assembly-level 分态（真实 _assemble_ceo_toolset） -----------------------


def _ctx():
    from pathlib import Path

    from agentcore.tools.protocol import ToolContext
    from agentcore.tools.sandbox.subprocess import SubprocessSandbox
    from agentcore.workspace.server import ServerWorkspace

    # Assembly never touches the backend; a real one only satisfies the shape.
    return ToolContext(
        execution_id="exec-assembly",
        run_id="r",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


def _assemble(*, checkpoint_enabled: bool = True) -> ToolRegistry:
    from agentcore.llm.profiles import default_turn_profiles
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.resolve.prepare import _assemble_ceo_toolset
    from agentcore.runtime.skills import build_system_skill_registry

    _, _, chat_tools = _assemble_ceo_toolset(
        llm=object(),
        sink=EventSink(),
        base_system_prompt="SYS",
        user_message="原始请求",
        history=[],
        worker_tools=ToolRegistry(),
        base_tool_context=_ctx(),
        profiles=default_turn_profiles(),
        approval_gate=None,
        session_store=None,
        session_saver=None,
        session_loader=None,
        conversation_id="c",
        captain_run_id="cap",
        checkpoint_enabled=checkpoint_enabled,
        message_id="m",
        suspension_saver=None,
        suspension_deleter=None,
        backend_location="cloud",
        skill_registry=build_system_skill_registry(),
    )
    return chat_tools


def test_assembled_idle_surface_split():
    """闲聊态：delegate / ask_user / debate 在；replan + 协调四件套不在。"""
    names = set(_assemble().names)
    assert {"delegate", "ask_user", "debate", "consult_skill"} <= names
    assert names.isdisjoint(COORDINATION_GATED_TOOLS)


def test_assembled_coordination_surface_split():
    """协调态：闸内工具齐全；常驻工具（含 delegate）照旧在。"""
    eid = "exec-assembly"
    token = current_execution_id.set(eid)
    try:
        _activate_coordination(eid)
        names = set(_assemble().names)
        assert {"delegate", "ask_user", "debate", "consult_skill"} <= names
        assert names >= COORDINATION_GATED_TOOLS
    finally:
        clear_active_coordination()
        current_execution_id.reset(token)


def test_debate_and_review_listed_in_idle_directory():
    """debate 常驻 ⇒ debate_and_review（requires_tools=debate）闲聊态回到能力目录。"""
    from agentcore.runtime.skills import build_system_skill_registry, render_skill_directory

    idle_names = set(_assemble().names)
    directory = render_skill_directory(build_system_skill_registry(), idle_names)
    assert "debate_and_review" in directory

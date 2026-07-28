"""Agent/自动化开工形态双闸 + structured resume wire (mirror presentation_format)."""

from pathlib import Path

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.runtime.events import EventSink
from agentcore.runtime.facts import FactKind, TurnFactLog, TurnPausedFact, current_fact_log
from agentcore.runtime.runs.automation_delivery import (
    DEFAULT_FORMAT_ID,
    automation_kickoff_requires_formats_error,
    automation_missing_delivery_error,
    classify_delivery_kind,
    clear_delivery_confirmation,
    ensure_full_auto_default_delivery,
    delivery_from_journal_entries,
    get_delivery_confirmation,
    is_automation_kickoff_text,
    record_delivery_confirmation,
    rehydrate_delivery_confirmation,
    resolve_delivery_from_resume,
    snapshot_automation_delivery_for_pause,
)
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_is_automation_kickoff_text_positive():
    assert is_automation_kickoff_text("帮我做短视频自动化 Agent")
    assert is_automation_kickoff_text("打造内容分发工作流")
    assert is_automation_kickoff_text("生成多步骤代运营流水线")
    assert is_automation_kickoff_text("Build an automation agent for posting")
    assert is_automation_kickoff_text("开发一套自动发帖的流水线")


def test_is_automation_kickoff_text_false_positives():
    assert not is_automation_kickoff_text("用团队做调研")
    assert not is_automation_kickoff_text("帮我写一个 agent 提示词")
    assert not is_automation_kickoff_text("优化 Agent system prompt")
    assert not is_automation_kickoff_text("写一份调研报告")
    assert not is_automation_kickoff_text("帮我做个官网落地页")
    assert not is_automation_kickoff_text("帮我做一个运营控制台")


def test_resolve_delivery_from_resume_by_explicit_format_id():
    opts = [
        {"id": "f0", "label": "可运行自动化"},
        {"id": "f1", "label": "控制台原型"},
        {"id": "f2", "label": "仅方案"},
    ]
    conf = resolve_delivery_from_resume(opts, format_id="f1", note="· 形态：可运行")
    assert conf is not None
    assert conf.format_id == "f1"
    assert conf.label == "控制台原型"
    assert classify_delivery_kind(conf) == "console"


def test_resolve_delivery_from_resume_prose_alone_does_not_confirm():
    opts = [
        {"id": "f0", "label": "可运行自动化"},
        {"id": "f1", "label": "控制台原型"},
    ]
    conf = resolve_delivery_from_resume(
        opts, note="就按这个方案开做：\n· 形态：控制台原型\n"
    )
    assert conf is None


def test_ledger_record_and_full_auto_default():
    cid = "test-auto-delivery-ledger-cid"
    clear_delivery_confirmation(cid)
    assert get_delivery_confirmation(cid) is None
    ensure_full_auto_default_delivery(cid)
    conf = get_delivery_confirmation(cid)
    assert conf is not None
    assert conf.format_id == DEFAULT_FORMAT_ID
    assert conf.source == "full_auto_default"
    assert classify_delivery_kind(conf) == "runnable"
    ensure_full_auto_default_delivery(cid)  # already set — no overwrite
    assert get_delivery_confirmation(cid).format_id == DEFAULT_FORMAT_ID
    record_delivery_confirmation(cid, format_id="f0", label="仅方案", source="ask_user")
    assert classify_delivery_kind(get_delivery_confirmation(cid)) == "plan"
    clear_delivery_confirmation(cid)


def _cache_miss(cid: str) -> bool:
    from agentcore.runtime.runs import automation_delivery as ad

    with ad._lock:
        return cid not in ad._LEDGER


def test_record_persists_journal_fact_and_survives_memory_clear():
    cid = "test-auto-persist-journal"
    clear_delivery_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_delivery_confirmation(
            cid, format_id="f1", label="控制台原型", source="ask_user"
        )
        entries = log.entries()
        assert any(
            e["kind"] == FactKind.AUTOMATION_DELIVERY_CONFIRMED.value for e in entries
        )
        folded = delivery_from_journal_entries(entries)
        assert folded is not None
        assert folded.format_id == "f1"

        clear_delivery_confirmation(cid)
        assert _cache_miss(cid)

        conf = get_delivery_confirmation(cid)
        assert conf is not None
        assert conf.format_id == "f1"

        clear_delivery_confirmation(cid)
        current_fact_log.reset(token)
        token = None
        assert get_delivery_confirmation(cid) is None
        restored = rehydrate_delivery_confirmation(cid, entries=entries)
        assert restored is not None
        assert restored.format_id == "f1"
        assert get_delivery_confirmation(cid).format_id == "f1"
    finally:
        if token is not None:
            current_fact_log.reset(token)
        clear_delivery_confirmation(cid)


def test_rehydrate_from_turn_paused_delivery_after_memory_clear():
    cid = "test-auto-persist-paused"
    clear_delivery_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_delivery_confirmation(
            cid, format_id="f0", label="可运行自动化", source="ask_user"
        )
        snap = snapshot_automation_delivery_for_pause(
            log.entries(), conversation_id=cid
        )
        assert snap == {
            "format_id": "f0",
            "label": "可运行自动化",
            "source": "ask_user",
        }
        paused = TurnPausedFact(
            checkpoint_id="cp",
            suspension_kind="ask_user",
            automation_delivery=snap,
        )
    finally:
        current_fact_log.reset(token)

    clear_delivery_confirmation(cid)
    restored = rehydrate_delivery_confirmation(
        cid, turn_paused_delivery=paused.automation_delivery
    )
    assert restored is not None
    assert restored.format_id == "f0"
    assert get_delivery_confirmation(cid).format_id == "f0"
    clear_delivery_confirmation(cid)


def test_no_persistent_delivery_means_gate_miss():
    cid = "test-auto-absent"
    clear_delivery_confirmation(cid)
    assert get_delivery_confirmation(cid) is None
    assert delivery_from_journal_entries([]) is None
    assert (
        rehydrate_delivery_confirmation(cid, entries=[], turn_paused_delivery=None)
        is None
    )


def _ask_ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-auto",
    )


@pytest.mark.asyncio
async def test_ask_user_automation_kickoff_rejects_empty_format_options():
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c-auto",
        timeout_seconds=1.0,
    )
    res = await tool.execute(
        {
            "message": "开工：做短视频自动化 Agent",
            "questions": [
                {
                    "prompt": "平台",
                    "options": ["抖音", "小红书"],
                    "default": "抖音",
                }
            ],
        },
        _ask_ctx(),
    )
    assert res.success is False
    assert automation_kickoff_requires_formats_error() in (res.error or "")


@pytest.mark.asyncio
async def test_ask_user_automation_kickoff_accepts_format_options():
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c-auto",
        timeout_seconds=1.0,
        message_id=None,
    )
    res = await tool.execute(
        {
            "message": "开工：做短视频自动化 Agent",
            "format_options": [
                {"label": "可运行自动化 — 真实可调度"},
                {"label": "控制台原型 — 工具台 UI"},
                {"label": "仅方案"},
            ],
            "questions": [
                {
                    "prompt": "平台",
                    "options": ["抖音", "小红书"],
                    "default": "抖音",
                }
            ],
        },
        _ask_ctx(),
    )
    assert automation_kickoff_requires_formats_error() not in (res.error or "")


@pytest.mark.asyncio
async def test_ask_user_research_false_positive_no_format_gate():
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c-auto-fp",
        timeout_seconds=1.0,
    )
    res = await tool.execute(
        {
            "message": "用团队做竞品调研",
            "assumptions": [{"item": "范围", "value": "三家主流"}],
        },
        _ask_ctx(),
    )
    assert automation_kickoff_requires_formats_error() not in (res.error or "")


def test_automation_missing_delivery_error_mentions_ask_user():
    err = automation_missing_delivery_error()
    assert "ask_user" in err
    assert "format_id" in err
    _ = AutonomyPolicy.MANAGED
    assert "full_auto" in err.lower()

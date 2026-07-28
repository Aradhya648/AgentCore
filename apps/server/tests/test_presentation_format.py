"""Presentation delivery-format dual-gate + structured resume wire (mirror website_style)."""

from pathlib import Path

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.runtime.events import EventSink
from agentcore.runtime.facts import FactKind, TurnFactLog, TurnPausedFact, current_fact_log
from agentcore.runtime.runs.presentation_format import (
    DEFAULT_FORMAT_ID,
    clear_format_confirmation,
    ensure_full_auto_default_format,
    format_from_journal_entries,
    get_format_confirmation,
    is_presentation_kickoff_text,
    presentation_kickoff_requires_formats_error,
    presentation_missing_format_error,
    record_format_confirmation,
    rehydrate_format_confirmation,
    resolve_format_from_resume,
    snapshot_presentation_format_for_pause,
)
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_is_presentation_kickoff_text():
    assert is_presentation_kickoff_text("帮我做一份产品发布 PPT")
    assert is_presentation_kickoff_text("写个课件幻灯片")
    assert is_presentation_kickoff_text("Build a presentation deck")
    assert is_presentation_kickoff_text("用 marp 做演示文稿")
    assert not is_presentation_kickoff_text("写一份调研报告")
    assert not is_presentation_kickoff_text("帮我做个官网落地页")


def test_resolve_format_from_resume_by_explicit_format_id():
    opts = [
        {"id": "f0", "label": "PowerPoint（.pptx）"},
        {"id": "f1", "label": "Marp Markdown 幻灯片"},
    ]
    conf = resolve_format_from_resume(
        opts, format_id="f1", note="· 形态：PowerPoint"
    )
    assert conf is not None
    assert conf.format_id == "f1"
    assert conf.label == "Marp Markdown 幻灯片"


def test_resolve_format_from_resume_by_selected_fn():
    opts = [
        {"id": "f0", "label": "PowerPoint（.pptx）"},
        {"id": "f1", "label": "Marp Markdown 幻灯片"},
    ]
    conf = resolve_format_from_resume(
        opts, selected=["受众", "f1"], note="就按这个方案开做："
    )
    assert conf is not None
    assert conf.format_id == "f1"


def test_resolve_format_from_resume_prose_alone_does_not_confirm():
    opts = [
        {"id": "f0", "label": "PowerPoint（.pptx）"},
        {"id": "f1", "label": "Marp Markdown 幻灯片"},
    ]
    conf = resolve_format_from_resume(
        opts, note="就按这个方案开做：\n· 形态：Marp Markdown 幻灯片\n"
    )
    assert conf is None


def test_resolve_format_from_resume_invalid_format_id_rejected():
    opts = [{"id": "f0", "label": "A"}, {"id": "f1", "label": "B"}]
    conf = resolve_format_from_resume(
        opts, format_id="f9", selected=["f0"], note="· 形态：A"
    )
    assert conf is None


def test_resolve_format_from_resume_selected_label_not_enough():
    opts = [
        {"id": "f0", "label": "PowerPoint（.pptx）"},
        {"id": "f1", "label": "Marp Markdown 幻灯片"},
    ]
    conf = resolve_format_from_resume(opts, selected=["Marp Markdown 幻灯片"])
    assert conf is None


def test_ledger_record_and_full_auto_default():
    cid = "test-format-ledger-cid"
    clear_format_confirmation(cid)
    assert get_format_confirmation(cid) is None
    ensure_full_auto_default_format(cid, prefer_pptx=False)
    conf = get_format_confirmation(cid)
    assert conf is not None
    assert conf.format_id == DEFAULT_FORMAT_ID
    assert conf.source == "full_auto_default"
    assert "Marp" in conf.label
    ensure_full_auto_default_format(cid, prefer_pptx=True)  # already set — no overwrite
    assert get_format_confirmation(cid).format_id == DEFAULT_FORMAT_ID
    clear_format_confirmation(cid)
    ensure_full_auto_default_format(cid, prefer_pptx=True)
    assert "PowerPoint" in get_format_confirmation(cid).label
    record_format_confirmation(cid, format_id="f0", label="X", source="ask_user")
    assert get_format_confirmation(cid).format_id == "f0"
    clear_format_confirmation(cid)


def _cache_miss(cid: str) -> bool:
    from agentcore.runtime.runs import presentation_format as pf

    with pf._lock:
        return cid not in pf._LEDGER


def test_record_persists_journal_fact_and_survives_memory_clear():
    """Acceptance: clear hot cache → rehydrate from journal → format still present."""
    cid = "test-format-persist-journal"
    clear_format_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_format_confirmation(
            cid, format_id="f1", label="Marp", source="ask_user"
        )
        entries = log.entries()
        assert any(
            e["kind"] == FactKind.PRESENTATION_FORMAT_CONFIRMED.value for e in entries
        )
        folded = format_from_journal_entries(entries)
        assert folded is not None
        assert folded.format_id == "f1"

        clear_format_confirmation(cid)
        assert _cache_miss(cid)

        conf = get_format_confirmation(cid)
        assert conf is not None
        assert conf.format_id == "f1"
        assert conf.label == "Marp"

        clear_format_confirmation(cid)
        current_fact_log.reset(token)
        token = None
        assert get_format_confirmation(cid) is None
        restored = rehydrate_format_confirmation(cid, entries=entries)
        assert restored is not None
        assert restored.format_id == "f1"
        assert get_format_confirmation(cid).format_id == "f1"
    finally:
        if token is not None:
            current_fact_log.reset(token)
        clear_format_confirmation(cid)


def test_rehydrate_from_turn_paused_format_after_memory_clear():
    """Acceptance: clear hot cache → rehydrate from turn_paused.presentation_format."""
    cid = "test-format-persist-paused"
    clear_format_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_format_confirmation(
            cid, format_id="f0", label="PowerPoint", source="ask_user"
        )
        snap = snapshot_presentation_format_for_pause(
            log.entries(), conversation_id=cid
        )
        assert snap == {
            "format_id": "f0",
            "label": "PowerPoint",
            "source": "ask_user",
        }
        paused = TurnPausedFact(
            checkpoint_id="cp",
            suspension_kind="ask_user",
            presentation_format=snap,
        )
    finally:
        current_fact_log.reset(token)

    clear_format_confirmation(cid)
    restored = rehydrate_format_confirmation(
        cid, turn_paused_format=paused.presentation_format
    )
    assert restored is not None
    assert restored.format_id == "f0"
    assert get_format_confirmation(cid).format_id == "f0"
    clear_format_confirmation(cid)


def test_no_persistent_format_means_gate_miss():
    """Acceptance: no journal/paused/cache → get returns None (delegate gate rejects)."""
    cid = "test-format-absent"
    clear_format_confirmation(cid)
    assert get_format_confirmation(cid) is None
    assert format_from_journal_entries([]) is None
    assert (
        rehydrate_format_confirmation(cid, entries=[], turn_paused_format=None) is None
    )


def _ask_ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-format",
    )


@pytest.mark.asyncio
async def test_ask_user_presentation_kickoff_rejects_empty_format_options():
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c-format",
        timeout_seconds=1.0,
    )
    res = await tool.execute(
        {
            "message": "开工：做一份产品发布 PPT 演示文稿",
            "questions": [
                {
                    "prompt": "时长",
                    "options": ["10 分钟", "20 分钟"],
                    "default": "10 分钟",
                }
            ],
        },
        _ask_ctx(),
    )
    assert res.success is False
    assert presentation_kickoff_requires_formats_error() in (res.error or "")


@pytest.mark.asyncio
async def test_ask_user_presentation_kickoff_accepts_format_options():
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c-format",
        timeout_seconds=1.0,
        message_id=None,
    )
    res = await tool.execute(
        {
            "message": "开工：做一份产品发布 PPT 演示文稿",
            "format_options": [
                {"label": "PowerPoint（.pptx）— 有 code_execute 时推荐"},
                {"label": "Marp Markdown 幻灯片 — 无代码执行时推荐"},
                {"label": "仅讲稿大纲"},
            ],
            "questions": [
                {
                    "prompt": "时长",
                    "options": ["10 分钟", "20 分钟"],
                    "default": "10 分钟",
                }
            ],
        },
        _ask_ctx(),
    )
    assert presentation_kickoff_requires_formats_error() not in (res.error or "")


def test_presentation_missing_format_error_mentions_ask_user():
    err = presentation_missing_format_error()
    assert "ask_user" in err
    assert "format_id" in err
    _ = AutonomyPolicy.MANAGED
    assert "full_auto" in err.lower()

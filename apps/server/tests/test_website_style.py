"""P1a website style dual-gate + DESIGN helpers + structured resume wire."""

from pathlib import Path

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.events import EventSink
from agentcore.runtime.facts import FactKind, TurnFactLog, TurnPausedFact, current_fact_log
from agentcore.runtime.runs.website_style import (
    DEFAULT_STYLE_ID,
    STYLE_ID_HEADING,
    build_website_missing_style_error,
    clear_style_confirmation,
    ensure_full_auto_default_style,
    extract_style_id_from_design,
    get_style_confirmation,
    record_style_confirmation,
    rehydrate_style_confirmation,
    resolve_style_from_resume,
    snapshot_website_style_for_pause,
    style_from_journal_entries,
)
from agentcore.runtime.suspension import captain_transcript
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_is_website_build_intent_construction_vs_audit():
    from agentcore.runtime.runs.website_style import (
        is_site_build_intent,
        is_toolshed_build_intent,
        is_website_build_intent,
        is_website_followup_exempt,
    )

    assert is_website_build_intent("帮我做个官网")
    assert is_website_build_intent("构建一个完整的 GEO 官网")
    assert is_website_build_intent("Build a landing page for GEO")
    assert is_website_build_intent(
        "build_website playbook未在能力目录中确认可用，手写内容+前端两阶段任务构建官网"
    )
    # Bare 官网 in audit framing is NOT greenfield construction.
    assert not is_website_build_intent("对 GEO 官网的两个交付物进行独立审计")
    assert not is_website_build_intent("写一份调研报告")
    assert is_website_followup_exempt("质量敏感成品独立审计，1名审计员")
    assert is_website_followup_exempt("小范围精准修复审计发现的两个问题")

    assert is_toolshed_build_intent("帮我做一个运营控制台")
    assert is_toolshed_build_intent("搭建管理后台")
    assert is_toolshed_build_intent("Build an admin dashboard")
    assert is_toolshed_build_intent("手写构建工具台")
    assert not is_toolshed_build_intent("对控制台做独立审计")
    assert is_site_build_intent("帮我做个官网")
    assert is_site_build_intent("帮我搭一个工具台")
    assert not is_site_build_intent("写一份调研报告")


def test_website_continuation_and_shaped_call():
    from agentcore.runtime.runs.website_style import (
        is_website_continuation_intent,
        is_website_shaped_call,
    )

    # Continuation alone is not enough — needs a site / toolshed anchor.
    assert not is_website_continuation_intent("继续完成")
    assert not is_website_continuation_intent("讨论继续完成项目的开发")
    assert is_website_continuation_intent("继续完成官网剩余分区")
    assert is_website_continuation_intent("把剩下的官网分区补全")
    assert is_website_continuation_intent("接着完成官网")
    assert not is_website_continuation_intent("继续")  # bare 继续 不触发
    assert not is_website_continuation_intent("改一下超时")

    # Strong site signals only — bare HTML/CSS/JS / HTML5 game framing do not count.
    assert is_website_shaped_call("写完官网剩余分区 HTML/CSS/JS")
    assert is_website_shaped_call("playbook=build_website 补全分区")
    assert is_website_shaped_call("落地页 index.html styles.css")
    assert not is_website_shaped_call("前端 HTML5 游戏画布与卡牌逻辑")
    assert not is_website_shaped_call("实现 CSS 动画与 JS 交互")
    assert not is_website_shaped_call("把超时配置从 30s 调到 60s")
    assert not is_website_shaped_call("改一行配置")
    # File-extension paths alone must not look website-shaped.
    assert not is_website_shaped_call("整理 docs/原型打印卡牌.html")
    assert not is_website_shaped_call("更新 原型打印卡牌.html 与 notes.css")


def test_resolve_style_from_resume_by_explicit_style_id():
    opts = [{"id": "s0", "label": "深色科技"}, {"id": "s1", "label": "简约商务"}]
    conf = resolve_style_from_resume(opts, style_id="s1", note="· 风格：深色科技")
    assert conf is not None
    assert conf.style_id == "s1"
    assert conf.label == "简约商务"


def test_resolve_style_from_resume_by_selected_sn():
    opts = [{"id": "s0", "label": "深色科技"}, {"id": "s1", "label": "简约商务"}]
    conf = resolve_style_from_resume(
        opts, selected=["中小商家", "s1"], note="就按这个方案开做："
    )
    assert conf is not None
    assert conf.style_id == "s1"


def test_resolve_style_from_resume_prose_alone_does_not_confirm():
    opts = [{"id": "s0", "label": "深色科技"}, {"id": "s1", "label": "简约商务"}]
    conf = resolve_style_from_resume(
        opts, note="就按这个方案开做：\n· 风格：简约商务\n"
    )
    assert conf is None


def test_resolve_style_from_resume_invalid_style_id_rejected():
    opts = [{"id": "s0", "label": "A"}, {"id": "s1", "label": "B"}]
    # Explicit invalid id must not fall through to selected / note.
    conf = resolve_style_from_resume(
        opts, style_id="s9", selected=["s0"], note="· 风格：A"
    )
    assert conf is None


def test_resolve_style_from_resume_selected_label_not_enough():
    opts = [{"id": "s0", "label": "深色科技"}, {"id": "s1", "label": "简约商务"}]
    conf = resolve_style_from_resume(opts, selected=["简约商务"])
    assert conf is None


def test_ledger_record_and_full_auto_default():
    cid = "test-style-ledger-cid"
    clear_style_confirmation(cid)
    assert get_style_confirmation(cid) is None
    ensure_full_auto_default_style(cid)
    conf = get_style_confirmation(cid)
    assert conf is not None
    assert conf.style_id == DEFAULT_STYLE_ID
    assert conf.source == "full_auto_default"
    record_style_confirmation(cid, style_id="s0", label="X", source="ask_user")
    assert get_style_confirmation(cid).style_id == "s0"
    clear_style_confirmation(cid)


def _cache_miss(cid: str) -> bool:
    """True when hot cache is empty (bypass ambient-log fallback)."""
    from agentcore.runtime.runs import website_style as ws

    with ws._lock:
        return cid not in ws._LEDGER


def test_record_persists_journal_fact_and_survives_memory_clear():
    """Acceptance: clear hot cache → rehydrate from journal → style still present."""
    cid = "test-style-persist-journal"
    clear_style_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_style_confirmation(cid, style_id="s1", label="简约", source="ask_user")
        entries = log.entries()
        assert any(e["kind"] == FactKind.WEBSITE_STYLE_CONFIRMED.value for e in entries)
        folded = style_from_journal_entries(entries)
        assert folded is not None
        assert folded.style_id == "s1"

        clear_style_confirmation(cid)
        assert _cache_miss(cid)

        # Ambient fact log still bound → get_style_confirmation rehydrates.
        conf = get_style_confirmation(cid)
        assert conf is not None
        assert conf.style_id == "s1"
        assert conf.label == "简约"

        clear_style_confirmation(cid)
        # Explicit rehydrate from entries (simulates cold path without ambient log).
        current_fact_log.reset(token)
        token = None
        assert get_style_confirmation(cid) is None
        restored = rehydrate_style_confirmation(cid, entries=entries)
        assert restored is not None
        assert restored.style_id == "s1"
        assert get_style_confirmation(cid).style_id == "s1"
    finally:
        if token is not None:
            current_fact_log.reset(token)
        clear_style_confirmation(cid)


def test_rehydrate_from_turn_paused_style_after_memory_clear():
    """Acceptance: clear hot cache → rehydrate from turn_paused.website_style."""
    cid = "test-style-persist-paused"
    clear_style_confirmation(cid)
    log = TurnFactLog()
    token = current_fact_log.set(log)
    try:
        record_style_confirmation(cid, style_id="s0", label="深色", source="ask_user")
        snap = snapshot_website_style_for_pause(log.entries(), conversation_id=cid)
        assert snap == {"style_id": "s0", "label": "深色", "source": "ask_user"}
        paused = TurnPausedFact(
            checkpoint_id="cp",
            suspension_kind="ask_user",
            website_style=snap,
        )
    finally:
        current_fact_log.reset(token)

    # No ambient log: only turn_paused snapshot.
    clear_style_confirmation(cid)
    restored = rehydrate_style_confirmation(
        cid, turn_paused_style=paused.website_style
    )
    assert restored is not None
    assert restored.style_id == "s0"
    assert get_style_confirmation(cid).style_id == "s0"
    clear_style_confirmation(cid)


def test_no_persistent_style_means_gate_miss():
    """Acceptance: no journal/paused/cache → get returns None (build_website rejects)."""
    cid = "test-style-absent"
    clear_style_confirmation(cid)
    assert get_style_confirmation(cid) is None
    assert style_from_journal_entries([]) is None
    assert rehydrate_style_confirmation(cid, entries=[], turn_paused_style=None) is None


def test_extract_style_id_from_design():
    text = f"# D\n\n## {STYLE_ID_HEADING}\ns0\n\n## Tokens\n#abc\n"
    assert extract_style_id_from_design(text) == "s0"
    assert extract_style_id_from_design("# no style") is None


def _ask_ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-style",
    )


def _ask_tool() -> AskUserTool:
    async def _save(_frame) -> None:
        return None

    async def _drop(_mid: str) -> None:
        return None

    return AskUserTool(
        sink=EventSink(),
        conversation_id="c-style",
        timeout_seconds=1.0,
        message_id="m1",
        suspension_saver=_save,
        suspension_deleter=_drop,
        captain_run_id="cap",
        base_system_prompt="sys",
        user_message="做个官网",
    )


@pytest.mark.asyncio
async def test_ask_user_website_without_style_options_still_succeeds():
    """引擎不因文案像建站而强制 style_options；缺省放行。"""
    tool = _ask_tool()
    token = captain_transcript.set(
        [LLMMessage(role="user", content="为 GEO 做官网落地页")]
    )
    try:
        res = await tool.execute(
            {
                "message": "开工：为 GEO 做官网落地页",
                "questions": [
                    {
                        "prompt": "受众",
                        "options": ["中小商家", "企业"],
                        "default": "中小商家",
                    }
                ],
            },
            _ask_ctx(),
        )
    finally:
        captain_transcript.reset(token)
    assert res.success is True


@pytest.mark.asyncio
async def test_ask_user_website_with_style_options_succeeds():
    tool = _ask_tool()
    token = captain_transcript.set(
        [LLMMessage(role="user", content="为 GEO 做官网落地页")]
    )
    try:
        res = await tool.execute(
            {
                "message": "开工：为 GEO 做官网落地页",
                "style_options": [{"label": "深色科技"}, {"label": "简约商务"}],
                "questions": [
                    {
                        "prompt": "受众",
                        "options": ["中小商家", "企业"],
                        "default": "中小商家",
                    }
                ],
            },
            _ask_ctx(),
        )
    finally:
        captain_transcript.reset(token)
    assert res.success is True


def test_build_website_missing_style_error_mentions_ask_user():
    err = build_website_missing_style_error()
    assert "build_website" in err
    assert "ask_user" in err
    _ = AutonomyPolicy.MANAGED  # keyed exemption exists in product vocabulary
    assert "full_auto" in err.lower()

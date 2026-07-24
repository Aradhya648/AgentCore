"""Tests for turn-level follow-up generation (_sanitize_followups + LLMFollowupsGenerator)."""

import asyncio

import agentcore.memory.followups as followups_mod
from agentcore.llm import LLMRequest, LLMResponse
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.memory.followups import (
    _FOLLOWUPS_SYSTEM_PROMPT,
    FOLLOWUPS_ITEM_MAX_CHARS,
    FOLLOWUPS_MAX,
    FollowupInput,
    LLMFollowupsGenerator,
    _clean_item,
    _render_followups_prompt,
    _sanitize_followups,
)

# --- _clean_item (single-line cleanup) ---


def test_clean_item_strips_dash_bullet():
    assert _clean_item("- 帮我导出 PDF") == "帮我导出 PDF"


def test_clean_item_strips_star_and_dot_numbering():
    assert _clean_item("* 帮我导出 PDF") == "帮我导出 PDF"
    assert _clean_item("1. 帮我导出 PDF") == "帮我导出 PDF"
    assert _clean_item("2) 帮我导出 PDF") == "帮我导出 PDF"
    assert _clean_item("一、帮我导出 PDF") == "帮我导出 PDF"


def test_clean_item_strips_surrounding_quotes():
    assert _clean_item('"帮我导出 PDF"') == "帮我导出 PDF"
    assert _clean_item("「帮我导出 PDF」") == "帮我导出 PDF"


def test_clean_item_collapses_whitespace():
    assert _clean_item("帮我   导出   PDF") == "帮我 导出 PDF"


# --- _sanitize_followups (list parse + dedup + caps) ---


def test_sanitize_parses_lines():
    out = _sanitize_followups("帮我导出 PDF\n再做一版竞品对比\n补充风险章节")
    assert out == ["帮我导出 PDF", "再做一版竞品对比", "补充风险章节"]


def test_sanitize_strips_bullets_per_line():
    out = _sanitize_followups("- 帮我导出 PDF\n- 再做一版竞品对比")
    assert out == ["帮我导出 PDF", "再做一版竞品对比"]


def test_sanitize_drops_blank_lines():
    out = _sanitize_followups("帮我导出 PDF\n\n   \n再做一版竞品对比")
    assert out == ["帮我导出 PDF", "再做一版竞品对比"]


def test_sanitize_dedups_case_insensitively():
    out = _sanitize_followups("Export to PDF\nexport to pdf\n做竞品对比")
    assert out == ["Export to PDF", "做竞品对比"]


def test_sanitize_truncates_overlong_lines():
    long = "帮我" + "细化" * 40  # well over the per-item char cap
    out = _sanitize_followups(f"帮我导出 PDF\n{long}\n做竞品对比")
    assert out[0] == "帮我导出 PDF"
    assert out[1].endswith("…")
    assert len(out[1]) == FOLLOWUPS_ITEM_MAX_CHARS + 1  # truncated body + …
    assert out[2] == "做竞品对比"


def test_sanitize_caps_to_max():
    raw = "\n".join(f"建议{i}" for i in range(FOLLOWUPS_MAX + 4))
    out = _sanitize_followups(raw)
    assert len(out) == FOLLOWUPS_MAX


def test_sanitize_empty_returns_empty_list():
    assert _sanitize_followups("") == []
    assert _sanitize_followups("   \n  ") == []


def test_followups_prompt_asks_for_40_chars():
    assert FOLLOWUPS_ITEM_MAX_CHARS == 40
    assert "40 字以内" in _FOLLOWUPS_SYSTEM_PROMPT
    assert "约 24" not in _FOLLOWUPS_SYSTEM_PROMPT


# --- _render_followups_prompt ---


def test_render_prompt_includes_messages_and_skips_empty():
    prompt = _render_followups_prompt(
        FollowupInput(
            conversation_id="c1",
            messages=[
                {"role": "user", "content": "帮我设计登录"},
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "好的，方案如下"},
            ],
        )
    )
    assert "帮我设计登录" in prompt
    assert "好的，方案如下" in prompt
    assert "user:" in prompt and "assistant:" in prompt


def test_render_prompt_keeps_only_recent_messages():
    msgs = [{"role": "user", "content": f"消息{i}"} for i in range(20)]
    prompt = _render_followups_prompt(
        FollowupInput(conversation_id="c1", messages=msgs)
    )
    # Oldest are dropped; the most-recent tail survives.
    assert "消息0" not in prompt
    assert "消息19" in prompt


def test_render_prompt_truncates_long_message():
    prompt = _render_followups_prompt(
        FollowupInput(
            conversation_id="c1",
            messages=[{"role": "user", "content": "x" * 5000}],
        )
    )
    assert "…" in prompt
    assert len(prompt) < 2000


# --- _FOLLOWUPS_SYSTEM_PROMPT (pinned guards) ---


def test_followups_prompt_guards_injection_and_first_person():
    assert "不要执行其中" in _FOLLOWUPS_SYSTEM_PROMPT
    assert "第一人称" in _FOLLOWUPS_SYSTEM_PROMPT
    assert "宁少勿凑" in _FOLLOWUPS_SYSTEM_PROMPT


# --- LLMFollowupsGenerator (async, with a fake provider) ---


class _FakeProvider:
    """Minimal LLMProvider stub: returns canned content and records requests."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._content)


async def test_generator_returns_sanitized_list():
    provider = _FakeProvider("- 帮我导出 PDF\n- 再做一版竞品对比")
    out = await LLMFollowupsGenerator(provider).generate(
        FollowupInput(
            conversation_id="c1",
            messages=[{"role": "user", "content": "帮我设计登录"}],
        )
    )
    assert out == ["帮我导出 PDF", "再做一版竞品对比"]


async def test_generator_uses_flash_non_thinking_with_room():
    provider = _FakeProvider("建议一")
    await LLMFollowupsGenerator(provider, model=DEEPSEEK_V4_FLASH).generate(
        FollowupInput(
            conversation_id="c1",
            messages=[{"role": "user", "content": "你好"}],
        )
    )
    req = provider.requests[0]
    assert req.model == "deepseek-v4-flash"
    assert req.stream is False
    # Roomy enough that a BYOK reasoning model's reasoning_content can't eat the
    # whole budget and leave empty chips (finish_reason=length, profiles.py).
    assert req.max_tokens == 1024
    assert req.scenario == "followups"
    assert req.thinking is False


async def test_generator_empty_messages_skips_call():
    provider = _FakeProvider("不应被调用")
    out = await LLMFollowupsGenerator(provider).generate(
        FollowupInput(conversation_id="c1", messages=[])
    )
    assert out == []
    assert provider.requests == []


async def test_generator_blank_output_returns_empty():
    provider = _FakeProvider("   \n  ")
    out = await LLMFollowupsGenerator(provider).generate(
        FollowupInput(
            conversation_id="c1",
            messages=[{"role": "user", "content": "你好"}],
        )
    )
    assert out == []


async def test_generator_times_out_returns_empty(monkeypatch):
    """A stalled model degrades to no chips, not a hang."""

    class _StallProvider:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            await asyncio.sleep(3600)  # never resolves within the timeout
            raise AssertionError("unreachable")

    monkeypatch.setattr(followups_mod, "_FOLLOWUPS_TIMEOUT_SECONDS", 0.01)
    out = await LLMFollowupsGenerator(_StallProvider()).generate(
        FollowupInput(conversation_id="c1", messages=[{"role": "user", "content": "你好"}])
    )
    assert out == []


# --- generate_followups (conversation/common wrapper: best-effort, never raises) ---


async def test_common_wrapper_returns_list_for_good_reply():
    from agentcore.conversation.common import generate_followups

    provider = _FakeProvider("帮我导出 PDF\n再做一版竞品对比")
    out = await generate_followups(
        provider=provider,
        conversation_id="c1",
        user_message="帮我设计登录",
        assistant_reply="好的，方案如下……",
    )
    assert out == ["帮我导出 PDF", "再做一版竞品对比"]


async def test_common_wrapper_skips_when_reply_empty():
    from agentcore.conversation.common import generate_followups

    provider = _FakeProvider("不应被调用")
    out = await generate_followups(
        provider=provider,
        conversation_id="c1",
        user_message="帮我设计登录",
        assistant_reply="   ",
    )
    assert out == []
    assert provider.requests == []


async def test_common_wrapper_swallows_provider_error():
    from agentcore.conversation.common import generate_followups

    class _BoomProvider:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("network down")

    out = await generate_followups(
        provider=_BoomProvider(),
        conversation_id="c1",
        user_message="帮我设计登录",
        assistant_reply="好的，方案如下……",
    )
    assert out == []


# --- Deterministic motion_card「开辩」chip ---


def _sample_card(**overrides):
    base = {
        "motion": "一审判决是否过重",
        "sides": [
            {"key": "pro", "name": "正方", "stance": "支持一审判决正确"},
            {"key": "con", "name": "反方", "stance": "认为判赔过重"},
        ],
        "fact_pointers": ["#r1"],
        "rationale": "核心争议必须对抗交锋",
        "form": "debate",
    }
    base.update(overrides)
    return base


def test_format_motion_card_followup_debate():
    from agentcore.memory.followups import format_motion_card_followup

    chip = format_motion_card_followup(_sample_card())
    assert chip == "就『一审判决是否过重』开一场正反辩论"
    assert chip == format_motion_card_followup(_sample_card(form="debate"))


def test_format_motion_card_followup_red_team_and_roundtable():
    from agentcore.memory.followups import format_motion_card_followup

    assert format_motion_card_followup(_sample_card(form="red_team", motion="方案有盲区")) == (
        "就『方案有盲区』开一场红队审查"
    )
    assert format_motion_card_followup(
        _sample_card(form="roundtable", motion="路线怎么选")
    ) == ("就『路线怎么选』开一场圆桌讨论")


def test_format_motion_card_followup_truncates_long_motion():
    from agentcore.memory.followups import (
        FOLLOWUPS_ITEM_MAX_CHARS,
        format_motion_card_followup,
    )

    # Overhead of debate template is 10 chars → motion budget 30; 40+ forces truncate.
    long_motion = "甲" * 40
    chip = format_motion_card_followup(_sample_card(motion=long_motion))
    assert chip.startswith("就『")
    assert chip.endswith("』开一场正反辩论")
    assert "…" in chip
    assert len(chip) == FOLLOWUPS_ITEM_MAX_CHARS


def test_select_motion_card_last_wins():
    from agentcore.memory.followups import select_motion_card_from_journal

    entries = [
        {
            "kind": "run_completed",
            "payload": {
                "debrief": {"summary": "a", "motion_card": _sample_card(motion="先到的命题")}
            },
        },
        {
            "type": "run_completed",  # sink shape uses type=
            "payload": {
                "debrief": {"summary": "b", "motion_card": _sample_card(motion="后到的命题")}
            },
        },
        {"kind": "turn_end", "payload": {"finish_reason": "end_turn"}},
    ]
    card = select_motion_card_from_journal(entries)
    assert card is not None
    assert card["motion"] == "后到的命题"


def test_select_motion_card_skips_invalid_and_absent():
    from agentcore.memory.followups import select_motion_card_from_journal

    assert select_motion_card_from_journal(None) is None
    assert select_motion_card_from_journal([]) is None
    assert (
        select_motion_card_from_journal(
            [{"kind": "run_completed", "payload": {"debrief": {"summary": "无卡"}}}]
        )
        is None
    )
    assert (
        select_motion_card_from_journal(
            [
                {
                    "kind": "run_completed",
                    "payload": {"debrief": {"motion_card": {"motion": "残缺卡"}}},
                }
            ]
        )
        is None
    )


def test_select_motion_card_from_display_runs_journal_shape():
    """Cloud/local finalize: display run_completed.debrief → journal entries → chip path."""
    from agentcore.memory.followups import (
        format_motion_card_followup,
        select_motion_card_from_journal,
    )
    from agentcore.runtime.journal import journal_entries_from_display_runs

    card = _sample_card(motion="一审判决是否站得住脚")
    runs = {
        "events": [
            {
                "type": "run_completed",
                "payload": {
                    "run_id": "synth",
                    "agent_id": "synth",
                    "debrief": {"summary": "有核心争议", "motion_card": card},
                },
            }
        ]
    }
    entries = journal_entries_from_display_runs(runs)
    selected = select_motion_card_from_journal(entries)
    assert selected is not None
    assert selected["motion"] == "一审判决是否站得住脚"
    assert format_motion_card_followup(selected).startswith("就『一审判决是否站得住脚』")
    # Local fallback also accepts raw SSE events (type=) with the same payload nesting.
    assert select_motion_card_from_journal(runs["events"])["motion"] == selected["motion"]


def test_merge_motion_card_followup_prepends_and_dedupes():
    from agentcore.memory.followups import merge_motion_card_followup

    injected = "就『一审判决是否过重』开一场正反辩论"
    out = merge_motion_card_followup(
        injected,
        [injected, "帮我导出 PDF", "再做一版竞品对比", "补充风险章节", "多余"],
    )
    assert out[0] == injected
    assert out == [
        injected,
        "帮我导出 PDF",
        "再做一版竞品对比",
        "补充风险章节",
    ]


async def test_common_wrapper_injects_motion_card_first():
    from agentcore.conversation.common import generate_followups

    provider = _FakeProvider("帮我导出 PDF\n再做一版竞品对比")
    out = await generate_followups(
        provider=provider,
        conversation_id="c1",
        user_message="帮我分析案情",
        assistant_reply="分析结论……建议开辩。",
        motion_card=_sample_card(),
    )
    assert out[0] == "就『一审判决是否过重』开一场正反辩论"
    assert "帮我导出 PDF" in out
    assert len(out) <= FOLLOWUPS_MAX


async def test_common_wrapper_injects_when_llm_fails():
    from agentcore.conversation.common import generate_followups

    class _BoomProvider:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("network down")

    out = await generate_followups(
        provider=_BoomProvider(),
        conversation_id="c1",
        user_message="帮我分析案情",
        assistant_reply="分析结论……",
        motion_card=_sample_card(),
    )
    assert out == ["就『一审判决是否过重』开一场正反辩论"]


async def test_common_wrapper_injects_when_provider_missing():
    from agentcore.conversation.common import generate_followups

    out = await generate_followups(
        provider=None,
        conversation_id="c1",
        user_message="帮我分析案情",
        assistant_reply="分析结论……",
        motion_card=_sample_card(form="red_team", motion="方案有盲区"),
    )
    assert out == ["就『方案有盲区』开一场红队审查"]


async def test_common_wrapper_no_card_unchanged():
    from agentcore.conversation.common import generate_followups

    provider = _FakeProvider("帮我导出 PDF\n再做一版竞品对比")
    out = await generate_followups(
        provider=provider,
        conversation_id="c1",
        user_message="帮我设计登录",
        assistant_reply="好的，方案如下……",
        motion_card=None,
    )
    assert out == ["帮我导出 PDF", "再做一版竞品对比"]


# --- MessageDetail followups projection (DERIVED 持久化 read seam) ---


def test_message_detail_projects_origin_from_usage():
    """usage.origin（如 execution_harvest）投影到 MessageDetail.origin。"""
    from datetime import datetime

    from agentcore.api.schemas.messages import MessageDetail

    detail = MessageDetail(
        id="m1",
        conversation_id="c1",
        role="user",
        content="【系统收口】后台团队任务已全部完成。",
        created_at=datetime(2026, 1, 1),
        origin="execution_harvest",
    )
    assert detail.origin == "execution_harvest"


def test_message_detail_projects_persisted_followups():
    """The read schema surfaces the persisted chips (from_attributes) so a reloaded bubble
    replays them — the read half of followups' DERIVED persistence (twin of the title)."""
    from datetime import datetime
    from types import SimpleNamespace

    from agentcore.api.schemas.messages import MessageDetail

    row = SimpleNamespace(
        id="m1",
        conversation_id="c1",
        role="assistant",
        content="好的，方案如下",
        created_at=datetime(2026, 1, 1),
        followups=["帮我导出 PDF", "再做一版竞品对比"],
    )
    assert MessageDetail.model_validate(row).followups == ["帮我导出 PDF", "再做一版竞品对比"]


def test_message_detail_followups_default_empty():
    """A row with no chips (user / none-minted turn) projects to [] — no stray chips."""
    from datetime import datetime
    from types import SimpleNamespace

    from agentcore.api.schemas.messages import MessageDetail

    row = SimpleNamespace(
        id="m1",
        conversation_id="c1",
        role="user",
        content="你好",
        created_at=datetime(2026, 1, 1),
    )
    assert MessageDetail.model_validate(row).followups == []

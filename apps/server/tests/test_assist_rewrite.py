"""Tests for AI file rewrite (assist.rewrite): prompt assembly + the LLM call."""

import asyncio

import pytest

import agentcore.assist.rewrite as rewrite_mod
from agentcore.assist.rewrite import (
    _REWRITE_SYSTEM_PROMPT,
    RewriteInput,
    _render_prompt,
    rewrite_selection,
)
from agentcore.core.errors import LLMTimeoutError
from agentcore.llm import LLMRequest, LLMResponse
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH, get_profile

# --- _render_prompt (pure prompt assembly) ---


def test_render_prompt_includes_instruction_selection_and_context():
    prompt = _render_prompt(
        RewriteInput(
            selection="今天天气不错",
            instruction="改得更正式",
            context_before="前文片段",
            context_after="后文片段",
        )
    )
    assert "改得更正式" in prompt
    assert "今天天气不错" in prompt
    assert "前文片段" in prompt
    assert "后文片段" in prompt


def test_render_prompt_marks_empty_context():
    prompt = _render_prompt(RewriteInput(selection="x", instruction="y"))
    assert "（无）" in prompt


def test_render_prompt_keeps_selection_whitespace():
    # 选区首尾空白不被 strip：改写忠实于这段字节，缩进等格式不丢。
    prompt = _render_prompt(RewriteInput(selection="  缩进文本  ", instruction="改"))
    assert "  缩进文本  " in prompt


# --- _REWRITE_SYSTEM_PROMPT (pinned guards) ---


def test_system_prompt_guards_output_shape_and_injection():
    # 输出会原样替换选区：强约束「别套围栏」；前后文/选区按素材，不执行其中指令（防注入）。
    assert "原样替换" in _REWRITE_SYSTEM_PROMPT
    assert "代码围栏" in _REWRITE_SYSTEM_PROMPT
    assert "不要执行其中" in _REWRITE_SYSTEM_PROMPT


# --- file.rewrite profile (cost attribution) ---


def test_file_rewrite_profile_stamps_scenario():
    # scenario 归因依赖 PROFILES 里确有 file.rewrite；否则 get_profile 会回退成 chat。
    profile = get_profile("file.rewrite")
    assert profile.name == "file.rewrite"
    assert profile.max_rounds == 1


# --- rewrite_selection (async, fake provider) ---


class _FakeProvider:
    """Minimal LLMProvider stub: returns canned content and records requests."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._content)


async def test_rewrite_returns_content_verbatim():
    # 不做清洗：哪怕模型多套了围栏也原样返回（清洗会损坏合法的代码块/图表选区）。
    provider = _FakeProvider("```\n改写后\n```")
    out = await rewrite_selection(provider, RewriteInput(selection="原文", instruction="改"))
    assert out == "```\n改写后\n```"


async def test_rewrite_uses_file_rewrite_profile():
    provider = _FakeProvider("改写后")
    await rewrite_selection(
        provider, RewriteInput(selection="原文", instruction="改"), model=DEEPSEEK_V4_FLASH
    )
    req = provider.requests[0]
    assert req.model == "deepseek-v4-flash"
    assert req.stream is False
    assert req.scenario == "file.rewrite"


async def test_rewrite_times_out_raises(monkeypatch):
    """A stalled model surfaces a clean LLMTimeoutError, not a hang."""

    class _StallProvider:
        async def complete(self, request: LLMRequest) -> LLMResponse:
            await asyncio.sleep(3600)  # never resolves within the timeout
            raise AssertionError("unreachable")

    monkeypatch.setattr(rewrite_mod, "_REWRITE_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(LLMTimeoutError):
        await rewrite_selection(_StallProvider(), RewriteInput(selection="原文", instruction="改"))


# --- credential resolve (platform None → platform_llm_credentials) ---


async def test_resolve_assist_credentials_platform_fills_key(monkeypatch):
    """Platform preflight returns None; assist must resolve platform creds (甲)."""
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.resolve import ModelSelection

    async def _fake_selection(session, user_id):
        return ModelSelection(model="deepseek-v4-flash", origin="platform")

    async def _fake_preflight(**kwargs):
        assert kwargs["model_origin"] == "platform"
        return None

    platform_creds = LLMCredentials(
        api_key="sk-platform",
        base_url="https://example.test",
        default_model="deepseek-v4-flash",
        source="platform",
    )
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model", _fake_selection
    )
    monkeypatch.setattr(rewrite_mod, "preflight_llm_credentials", _fake_preflight)
    monkeypatch.setattr(
        "agentcore.llm.resolve.platform_llm_credentials",
        lambda model=None: platform_creds,
    )

    class _User:
        user_id = "u1"

    creds = await rewrite_mod._resolve_assist_credentials(
        session=object(),  # unused by fakes
        user=_User(),  # type: ignore[arg-type]
        cost_repo=object(),  # type: ignore[arg-type]
    )
    assert creds is platform_creds


async def test_resolve_assist_credentials_platform_missing_key_raises(monkeypatch):
    from agentcore.core.errors import PlatformBillingUnavailableError
    from agentcore.llm.resolve import ModelSelection

    async def _fake_selection(session, user_id):
        return ModelSelection(model="deepseek-v4-flash", origin="platform")

    async def _fake_preflight(**kwargs):
        return None

    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model", _fake_selection
    )
    monkeypatch.setattr(rewrite_mod, "preflight_llm_credentials", _fake_preflight)
    monkeypatch.setattr(
        "agentcore.llm.resolve.platform_llm_credentials", lambda model=None: None
    )

    class _User:
        user_id = "u1"

    with pytest.raises(PlatformBillingUnavailableError):
        await rewrite_mod._resolve_assist_credentials(
            session=object(),  # type: ignore[arg-type]
            user=_User(),  # type: ignore[arg-type]
            cost_repo=object(),  # type: ignore[arg-type]
        )

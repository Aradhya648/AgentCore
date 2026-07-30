"""Cloud early title mint: schedule after user save, conditional write, fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import agentcore.conversation.common as common
from agentcore.conversation.common import (
    TITLE_MAX_CHARS,
    fallback_title,
    generate_title,
    schedule_title_generation,
)
from agentcore.memory.conversation_title import TitleResult
from agentcore.runtime.events import EventSink, EventType


class _BoomProvider:
    async def complete(self, _request):
        raise RuntimeError("llm down")


class _FakeSessionCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


def test_fallback_title_truncates_to_max():
    long = "题" * (TITLE_MAX_CHARS + 5)
    assert fallback_title(long) == "题" * TITLE_MAX_CHARS + "…"


async def test_generate_title_degrades_to_truncated_on_llm_failure():
    user = "帮我设计一个登录流程和权限模型"
    out = await generate_title(
        provider=_BoomProvider(),  # type: ignore[arg-type]
        conversation_id="c1",
        user_message=user,
        assistant_reply="",
    )
    assert out.title == fallback_title(user)


async def test_generate_title_reraise_llm_auth_error():
    import pytest

    from agentcore.core.errors import LLMAuthError

    class _AuthBoom:
        async def complete(self, _request):
            raise LLMAuthError(provider_name="platform")

    with pytest.raises(LLMAuthError):
        await generate_title(
            provider=_AuthBoom(),  # type: ignore[arg-type]
            conversation_id="c1",
            user_message="帮我设计登录",
            assistant_reply="好的",
        )


async def test_generate_title_falls_back_on_truncated_json_body():
    """Empty/half JSON after length-truncation → user-message prefix, never `{\"title`."""
    from agentcore.llm import LLMResponse

    class _FragProvider:
        async def complete(self, _request):
            return LLMResponse(content='{"title')

    user = "帮我设计一个登录流程和权限模型"
    out = await generate_title(
        provider=_FragProvider(),  # type: ignore[arg-type]
        conversation_id="c1",
        user_message=user,
        assistant_reply="",
    )
    assert out.title == fallback_title(user)
    assert "{" not in out.title


async def test_schedule_title_does_not_block_caller(monkeypatch):
    """schedule returns immediately; the runner runs in parallel (does not await)."""
    gate = asyncio.Event()
    finished = asyncio.Event()
    order: list[str] = []

    async def _slow(**_kwargs):
        try:
            order.append("runner_started")
            await gate.wait()
            order.append("runner_done")
            finished.set()
        finally:
            common._title_inflight.discard("c-early")

    monkeypatch.setattr(common, "_mint_title_background", _slow)
    common._title_inflight.clear()

    schedule_title_generation(
        conversation_id="c-early",
        user_id="u1",
        user_message="你好",
        sink=EventSink(),
    )
    order.append("caller_returned")
    assert "runner_done" not in order
    assert "c-early" in common._title_inflight

    gate.set()
    await asyncio.wait_for(finished.wait(), 1)
    await asyncio.sleep(0)
    assert "caller_returned" in order
    assert "runner_done" in order
    assert "c-early" not in common._title_inflight


async def test_schedule_dedupes_while_inflight(monkeypatch):
    calls: list[str] = []

    async def _rec(**kwargs):
        calls.append(kwargs["conversation_id"])

    monkeypatch.setattr(common, "_mint_title_background", _rec)
    common._title_inflight.add("c1")
    try:
        schedule_title_generation(
            conversation_id="c1",
            user_id="u1",
            user_message="x",
            sink=EventSink(),
        )
        await asyncio.sleep(0.02)
        assert calls == []
    finally:
        common._title_inflight.discard("c1")


async def test_mint_skips_write_when_title_already_set(monkeypatch):
    """User rename race: already-titled conversations must not be overwritten."""
    writes: list[tuple[str, str]] = []
    emits: list[str] = []

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id_unscoped(self, _cid):
            return SimpleNamespace(title="用户手改的标题")

        async def update_title_if_empty(self, conversation_id, title):
            writes.append((conversation_id, title))
            return SimpleNamespace(title=title)

    monkeypatch.setattr(common, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(common, "ConversationRepository", _ConvRepo)
    common._title_inflight.clear()

    sink = EventSink()
    original_emit = sink.emit

    def _spy_emit(event):
        emits.append(event.type.value if hasattr(event.type, "value") else str(event.type))
        return original_emit(event)

    sink.emit = _spy_emit  # type: ignore[method-assign]

    await common._mint_title_background(
        conversation_id="c1",
        user_id="u1",
        user_message="不该覆盖",
        sink=sink,
    )
    assert writes == []
    assert EventType.TITLE_GENERATED.value not in emits
    assert "c1" not in common._title_inflight


async def test_mint_writes_fallback_and_emits_when_llm_fails(monkeypatch):
    """LLM failure → truncated user message written (only if still empty) + SSE."""
    writes: list[tuple[str, str]] = []
    user = "这是一条足够长的首条用户消息用来验证截断降级行为是否正确"

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id_unscoped(self, _cid):
            return SimpleNamespace(title=None)

        async def update_title_if_empty(self, conversation_id, title):
            writes.append((conversation_id, title))
            return SimpleNamespace(title=title)

    monkeypatch.setattr(common, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(common, "ConversationRepository", _ConvRepo)

    async def _run_bg(user_id, *, purpose="title", runner):
        from agentcore.billing.gate import BackgroundLlmResult
        from agentcore.llm.credentials import LLMCredentials

        creds = LLMCredentials(
            api_key="sk", base_url="https://x", default_model="flash", source="platform"
        )
        value = await runner(creds)
        return BackgroundLlmResult(value=value, credentials=creds)

    monkeypatch.setattr(common, "run_background_llm", _run_bg)
    monkeypatch.setattr(common, "resolve_turn_model", lambda _c: "flash")
    monkeypatch.setattr(
        common,
        "build_provider",
        lambda *_a, **_k: SimpleNamespace(close=AsyncMock()),
    )
    monkeypatch.setattr(
        common,
        "generate_title",
        AsyncMock(return_value=TitleResult(title=fallback_title(user))),
    )
    common._title_inflight.add("c-fail")  # simulate schedule having armed it

    sink = EventSink()
    events: list = []
    original_emit = sink.emit

    def _spy_emit(event):
        events.append(event)
        return original_emit(event)

    sink.emit = _spy_emit  # type: ignore[method-assign]

    await common._mint_title_background(
        conversation_id="c-fail",
        user_id="u1",
        user_message=user,
        sink=sink,
    )

    assert writes == [("c-fail", fallback_title(user))]
    assert len(writes[0][1]) <= TITLE_MAX_CHARS + 1  # chars + optional ellipsis
    title_events = [e for e in events if e.type == EventType.TITLE_GENERATED]
    assert len(title_events) == 1
    assert title_events[0].payload["title"] == fallback_title(user)
    assert "c-fail" not in common._title_inflight


async def test_mint_emits_best_effort_when_sink_closed(monkeypatch):
    """Closed sink must not raise; DB write still lands."""
    writes: list[str] = []

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id_unscoped(self, _cid):
            return SimpleNamespace(title=None)

        async def update_title_if_empty(self, conversation_id, title):
            writes.append(title)
            return SimpleNamespace(title=title)

    monkeypatch.setattr(common, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(common, "ConversationRepository", _ConvRepo)

    async def _run_bg(user_id, *, purpose="title", runner):
        from agentcore.billing.gate import BackgroundLlmResult
        from agentcore.llm.credentials import LLMCredentials

        creds = LLMCredentials(
            api_key="sk", base_url="https://x", default_model="flash", source="platform"
        )
        value = await runner(creds)
        return BackgroundLlmResult(value=value, credentials=creds)

    monkeypatch.setattr(common, "run_background_llm", _run_bg)
    monkeypatch.setattr(common, "resolve_turn_model", lambda _c: "flash")
    monkeypatch.setattr(
        common,
        "build_provider",
        lambda *_a, **_k: SimpleNamespace(close=AsyncMock()),
    )
    monkeypatch.setattr(
        common,
        "generate_title",
        AsyncMock(return_value=TitleResult(title="早到标题")),
    )
    common._title_inflight.clear()

    sink = EventSink()
    sink.close()
    await common._mint_title_background(
        conversation_id="c-closed",
        user_id="u1",
        user_message="hi",
        sink=sink,
    )
    assert writes == ["早到标题"]


async def test_stream_chat_schedules_title_before_turn(monkeypatch):
    """After user message persist, title is scheduled before run_and_persist runs."""
    from agentcore.conversation import turns as turns_mod

    order: list[str] = []
    scheduled: list[dict] = []

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id_unscoped(self, _cid):
            return SimpleNamespace(title=None, folder_id=None)

    class _MsgRepo:
        def __init__(self, _session):
            pass

        async def create(self, **_kwargs):
            order.append("user_saved")
            return SimpleNamespace(id="um1")

    class _BoardRepo:
        def __init__(self, _session):
            pass

        async def get_by_conversation_id(self, *_a, **_k):
            return None

    class _Lock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(turns_mod, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(turns_mod, "ConversationRepository", _ConvRepo)
    monkeypatch.setattr(turns_mod, "MessageRepository", _MsgRepo)
    monkeypatch.setattr(turns_mod, "BoardRepository", _BoardRepo)
    monkeypatch.setattr(turns_mod, "resolve_local_binding", AsyncMock(return_value=None))
    monkeypatch.setattr(turns_mod, "resolve_profile_set", AsyncMock(return_value=None))
    monkeypatch.setattr(turns_mod, "resolve_memory_enabled", AsyncMock(return_value=True))
    from agentcore.core.types import AutonomyPolicy, recipe_to_axes

    monkeypatch.setattr(
        turns_mod,
        "resolve_permission_axes",
        AsyncMock(return_value=recipe_to_axes(AutonomyPolicy.LESS_INTERRUPT)),
    )
    monkeypatch.setattr(
        turns_mod,
        "build_turn_backend",
        AsyncMock(return_value=SimpleNamespace(location="server")),
    )
    monkeypatch.setattr(turns_mod, "workspace_lock", lambda *_a, **_k: _Lock())
    monkeypatch.setattr(turns_mod, "workspace_storage_key", lambda **_k: "k")
    monkeypatch.setattr(turns_mod, "persist_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr(turns_mod, "to_stored_metadata", lambda _a: None)
    monkeypatch.setattr(
        turns_mod,
        "load_chat_context",
        AsyncMock(return_value=[{"role": "user", "content": "hi"}]),
    )

    def _schedule(**kwargs):
        order.append("title_scheduled")
        scheduled.append(kwargs)

    async def _run(**_kwargs):
        order.append("turn_started")

    monkeypatch.setattr(turns_mod, "schedule_title_generation", _schedule)
    monkeypatch.setattr(turns_mod, "run_and_persist", _run)

    sink = EventSink()
    await turns_mod.stream_chat(
        conversation_id="c1",
        user_message="帮我写周报",
        user_id="u1",
        sink=sink,
    )

    assert order == ["user_saved", "title_scheduled", "turn_started"]
    assert scheduled[0]["conversation_id"] == "c1"
    assert scheduled[0]["user_message"] == "帮我写周报"


async def test_stream_chat_skips_title_when_already_named(monkeypatch):
    from agentcore.conversation import turns as turns_mod

    scheduled: list[dict] = []

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id_unscoped(self, _cid):
            return SimpleNamespace(title="已命名", folder_id=None)

    class _MsgRepo:
        def __init__(self, _session):
            pass

        async def create(self, **_kwargs):
            return SimpleNamespace(id="um1")

    class _BoardRepo:
        def __init__(self, _session):
            pass

        async def get_by_conversation_id(self, *_a, **_k):
            return None

    class _Lock:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(turns_mod, "async_session_factory", lambda: _FakeSessionCM())
    monkeypatch.setattr(turns_mod, "ConversationRepository", _ConvRepo)
    monkeypatch.setattr(turns_mod, "MessageRepository", _MsgRepo)
    monkeypatch.setattr(turns_mod, "BoardRepository", _BoardRepo)
    monkeypatch.setattr(turns_mod, "resolve_local_binding", AsyncMock(return_value=None))
    monkeypatch.setattr(turns_mod, "resolve_profile_set", AsyncMock(return_value=None))
    monkeypatch.setattr(turns_mod, "resolve_memory_enabled", AsyncMock(return_value=True))
    from agentcore.core.types import AutonomyPolicy, recipe_to_axes

    monkeypatch.setattr(
        turns_mod,
        "resolve_permission_axes",
        AsyncMock(return_value=recipe_to_axes(AutonomyPolicy.LESS_INTERRUPT)),
    )
    monkeypatch.setattr(
        turns_mod,
        "build_turn_backend",
        AsyncMock(return_value=SimpleNamespace(location="server")),
    )
    monkeypatch.setattr(turns_mod, "workspace_lock", lambda *_a, **_k: _Lock())
    monkeypatch.setattr(turns_mod, "workspace_storage_key", lambda **_k: "k")
    monkeypatch.setattr(turns_mod, "persist_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr(turns_mod, "to_stored_metadata", lambda _a: None)
    monkeypatch.setattr(
        turns_mod,
        "load_chat_context",
        AsyncMock(return_value=[{"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(
        turns_mod,
        "schedule_title_generation",
        lambda **kwargs: scheduled.append(kwargs),
    )
    monkeypatch.setattr(turns_mod, "run_and_persist", AsyncMock())

    await turns_mod.stream_chat(
        conversation_id="c1",
        user_message="hi",
        user_id="u1",
        sink=EventSink(),
    )
    assert scheduled == []

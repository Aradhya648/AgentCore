"""Tests for the attachment system-prompt block (`_build_attachment_context`).

Pins what the model sees: nothing injected when there are no usable attachments,
local path for un-resident files, the durable in-workspace path + an edit hint
once an attachment has been persisted (附件驻留), and directory listings shown as
paths only.

Conversation attachments (跨会话对话日志访问定案 P1): server deep-read via
``log_export`` — gate-off / soft-miss / truncation notes; never client shallow text.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentcore.runtime.pipeline import _build_attachment_context
from agentcore.workspace.attachment_parse import ATTACHMENT_INLINE_MAX_CHARS


@pytest.mark.asyncio
async def test_none_and_empty_return_none():
    assert await _build_attachment_context(None) is None
    assert await _build_attachment_context([]) is None
    # A file whose text is blank contributes no block → still None.
    assert await _build_attachment_context([{"name": "x", "text": "   "}]) is None


@pytest.mark.asyncio
async def test_unresident_file_uses_local_path_no_hint():
    out = await _build_attachment_context(
        [{"name": "a.py", "path": "/local/a.py", "text": "print(1)"}]
    )
    assert out is not None
    assert "--- File: a.py (/local/a.py) ---" in out
    assert "print(1)" in out
    assert "saved into your workspace" not in out
    # 定案 A：附件是本轮可开工输入，勿写成「仅参考」。
    assert "actionable inputs" in out
    assert "reference material" not in out
    assert "do not idle" in out or "full repo is missing" in out


@pytest.mark.asyncio
async def test_resident_file_uses_workspace_path_and_hint():
    out = await _build_attachment_context(
        [
            {
                "name": "a.py",
                "path": "/local/a.py",
                "text": "print(1)",
                "workspace_path": "attachments/a.py",
            }
        ]
    )
    assert out is not None
    # The header points at the durable path, not the local one.
    assert "--- File: a.py (attachments/a.py) ---" in out
    assert "saved into your workspace" in out
    assert "edit them with the file tools" in out


@pytest.mark.asyncio
async def test_binary_resident_has_no_inline_body():
    out = await _build_attachment_context(
        [
            {
                "name": "report.xlsx",
                "path": "attachments/report.xlsx",
                "text": "",
                "binary": True,
                "workspace_path": "attachments/report.xlsx",
            }
        ]
    )
    assert out is not None
    assert "--- File: report.xlsx (attachments/report.xlsx) [binary] ---" in out
    assert "code_execute" in out
    assert "Do NOT use an OS absolute path" in out
    assert "Never hard-read an OS absolute path" in out
    assert "saved into your workspace" in out
    # Prompt must not leak a client OS absolute path for binary residents.
    assert "C:\\" not in out
    assert "/Users/" not in out


@pytest.mark.asyncio
async def test_truncated_note_and_directory_listing():
    out = await _build_attachment_context(
        [
            {"name": "big.txt", "path": "/big.txt", "text": "partial", "truncated": True},
            {"name": "src", "path": "/src", "text": "a.py\nb.py", "kind": "dir"},
        ]
    )
    assert "--- File: big.txt (/big.txt) (truncated) ---" in out
    assert "--- Directory: src (/src) ---" in out
    assert "File paths (contents not included):" in out


class _AsyncCm:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *a):
        return False


def _patch_deep_read(monkeypatch, *, conv, messages, journal_map=None):
    """Stub session + repos for conversation attachment deep-read."""

    class FakeConvRepo:
        def __init__(self, session):
            pass

        async def get_by_id(self, cid, *, user_id):
            if conv is None:
                return None
            if conv.id != cid:
                return None
            if user_id and getattr(conv, "user_id", user_id) != user_id:
                return None
            return conv

    class FakeMsgRepo:
        def __init__(self, session):
            pass

        async def list_all_for_conversation(self, cid):
            return messages

    class FakeJournalRepo:
        def __init__(self, session):
            pass

        async def load_map(self, ids):
            return journal_map or {}

    # Lazy imports inside ``_deep_read_conversation_attachment`` — patch sources.
    monkeypatch.setattr(
        "agentcore.db.base.async_session_factory",
        lambda: _AsyncCm(),
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.ConversationRepository",
        FakeConvRepo,
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.MessageRepository",
        FakeMsgRepo,
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.TurnJournalRepository",
        FakeJournalRepo,
    )


@pytest.mark.asyncio
async def test_conversation_deep_read_success(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    conv = SimpleNamespace(
        id="conv-1",
        title="讨论 X 方案",
        mode="chat",
        user_id="u1",
        created_at=now,
        updated_at=now,
    )
    messages = [
        SimpleNamespace(
            id="m1",
            role="user",
            content="你好",
            reasoning_content=None,
            attachments=None,
            evidence_ledger=None,
            citations=None,
            usage=None,
            created_at=now,
        ),
        SimpleNamespace(
            id="m2",
            role="assistant",
            content="在的",
            reasoning_content=None,
            attachments=None,
            evidence_ledger=None,
            citations=None,
            usage=None,
            created_at=now,
        ),
    ]
    _patch_deep_read(monkeypatch, conv=conv, messages=messages)

    out = await _build_attachment_context(
        [
            {
                "name": "讨论 X 方案",
                "path": "对话",
                # Client shallow text MUST be ignored.
                "text": "CLIENT_SHALLOW_SHOULD_NOT_APPEAR",
                "kind": "conversation",
                "conversation_id": "conv-1",
            }
        ],
        user_id="u1",
        host_conversation_id="host-now",
        conversation_history_access=True,
    )
    assert out is not None
    assert "--- Conversation: 讨论 X 方案 ---" in out
    assert "### User" in out
    assert "你好" in out
    assert "### Assistant" in out
    assert "在的" in out
    assert "CLIENT_SHALLOW_SHOULD_NOT_APPEAR" not in out
    assert "read_conversation" in out  # guidance mentions continuation path
    assert "saved into your workspace" not in out


@pytest.mark.asyncio
async def test_conversation_gate_off_rejects_without_client_text(monkeypatch):
    out = await _build_attachment_context(
        [
            {
                "name": "旧场",
                "text": "CLIENT_SHALLOW",
                "kind": "conversation",
                "conversation_id": "conv-1",
            }
        ],
        user_id="u1",
        conversation_history_access=False,
    )
    assert out is not None
    assert "deep-read denied" in out
    assert "conversation_history_access=off" in out
    assert "CLIENT_SHALLOW" not in out
    # Must not hit the DB when gate is off.
    assert "### User" not in out


@pytest.mark.asyncio
async def test_conversation_missing_id_soft_miss():
    out = await _build_attachment_context(
        [
            {
                "name": "无 id",
                "text": "CLIENT_SHALLOW",
                "kind": "conversation",
            }
        ],
        user_id="u1",
        conversation_history_access=True,
    )
    assert out is not None
    assert "缺少 conversation_id" in out
    assert "CLIENT_SHALLOW" not in out


@pytest.mark.asyncio
async def test_conversation_soft_miss_wrong_owner(monkeypatch):
    _patch_deep_read(monkeypatch, conv=None, messages=[])
    out = await _build_attachment_context(
        [
            {
                "name": "他人场",
                "text": "CLIENT_SHALLOW",
                "kind": "conversation",
                "conversation_id": "other-1",
            }
        ],
        user_id="u1",
        conversation_history_access=True,
    )
    assert out is not None
    assert "无法打开该对话" in out
    assert "CLIENT_SHALLOW" not in out


@pytest.mark.asyncio
async def test_conversation_soft_miss_handoff(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    conv = SimpleNamespace(
        id="h1",
        title="handoff host",
        mode="handoff",
        user_id="u1",
        created_at=now,
        updated_at=now,
    )
    _patch_deep_read(monkeypatch, conv=conv, messages=[])
    out = await _build_attachment_context(
        [
            {
                "name": "h",
                "text": "CLIENT",
                "kind": "conversation",
                "conversation_id": "h1",
            }
        ],
        user_id="u1",
        conversation_history_access=True,
    )
    assert "无法打开该对话" in out
    assert "CLIENT" not in out


@pytest.mark.asyncio
async def test_conversation_truncated_note(monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    conv = SimpleNamespace(
        id="long-1",
        title="长对话",
        mode="chat",
        user_id="u1",
        created_at=now,
        updated_at=now,
    )
    huge = "X" * (ATTACHMENT_INLINE_MAX_CHARS + 500)
    messages = [
        SimpleNamespace(
            id="m1",
            role="user",
            content=huge,
            reasoning_content=None,
            attachments=None,
            evidence_ledger=None,
            citations=None,
            usage=None,
            created_at=now,
        ),
    ]
    _patch_deep_read(monkeypatch, conv=conv, messages=messages)

    out = await _build_attachment_context(
        [
            {
                "name": "长对话",
                "text": "CLIENT_SHALLOW",
                "kind": "conversation",
                "conversation_id": "long-1",
            }
        ],
        user_id="u1",
        conversation_history_access=True,
    )
    assert out is not None
    assert "truncated" in out
    assert "read_conversation" in out
    assert "conversation_id=long-1" in out
    assert "CLIENT_SHALLOW" not in out
    # Cap: full huge body must not appear inline.
    assert huge not in out

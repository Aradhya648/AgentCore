"""协调中用户插话：注入事件队列 + CEO queue_user_message 转对话级排队。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentcore.runtime.coordination.inject import format_coordination_events
from agentcore.runtime.coordination.session import (
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
    active_coordination_for_conversation,
    clear_active_coordination,
    set_active_coordination,
)
from agentcore.runtime.coordination.tools import QueueUserMessageTool
from agentcore.runtime.events import EventSink, user_interjection
from agentcore.runtime.turn_queue import turn_queue
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.attachments import (
    interjection_attachment_meta,
    persist_attachments,
)
from agentcore.workspace.server import ServerWorkspace


@pytest.fixture(autouse=True)
def _clean_coord():
    clear_active_coordination()
    turn_queue.clear("conv-inj")
    yield
    clear_active_coordination()
    turn_queue.clear("conv-inj")


def test_active_coordination_for_conversation_index():
    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    assert active_coordination_for_conversation("conv-inj") is session
    clear_active_coordination("exec-inj")
    assert active_coordination_for_conversation("conv-inj") is None


def test_user_interjection_is_necessary_decision():
    session = CoordinationSession(execution_id="e", total_workers=2)
    ev = CoordinationEvent(
        kind=CoordinationEventKind.USER_INTERJECTION,
        payload={"interjection_id": "i1", "content": "加一句成本"},
    )
    assert session.is_necessary_decision([ev]) is True


def test_user_interjection_sse_carries_attachments():
    meta = [
        {
            "name": "成本表.xlsx",
            "workspace_path": "attachments/成本表.xlsx",
            "binary": True,
        }
    ]
    ev = user_interjection(
        interjection_id="inj-a",
        execution_id="exec-a",
        content="对照附件",
        status="received",
        attachments=meta,
    )
    assert ev.payload["attachments"] == meta
    assert ev.payload["status"] == "received"


def test_interjection_attachment_meta_drops_text():
    meta = interjection_attachment_meta(
        [
            {
                "name": "notes.md",
                "path": "/tmp/notes.md",
                "text": "secret body",
                "workspace_path": "attachments/notes.md",
                "binary": False,
            }
        ]
    )
    assert meta == [
        {
            "name": "notes.md",
            "workspace_path": "attachments/notes.md",
            "binary": False,
        }
    ]
    assert "text" not in meta[0]


def test_inject_brief_lists_attachment_paths():
    session = CoordinationSession(execution_id="e", total_workers=2)
    brief = format_coordination_events(
        session,
        [
            CoordinationEvent(
                kind=CoordinationEventKind.USER_INTERJECTION,
                payload={
                    "interjection_id": "inj-1",
                    "content": "对照附件",
                    "attachments": [
                        {
                            "name": "成本表.xlsx",
                            "workspace_path": "attachments/成本表.xlsx",
                            "binary": True,
                        }
                    ],
                },
            )
        ],
    )
    assert "成本表.xlsx" in brief
    assert "attachments/成本表.xlsx" in brief
    assert "（二进制）" in brief
    assert "secret" not in brief


@pytest.mark.asyncio
async def test_persist_then_repersist_keeps_text_and_skips_rewrite(tmp_path: Path):
    """Delivered persist → stash → drain re-pass must not rewrite or drop inline text."""
    root = tmp_path / "ws"
    root.mkdir()
    ws = ServerWorkspace(root=root, sandbox=SubprocessSandbox())

    first = await persist_attachments(
        ws,
        [{"name": "notes.md", "path": "/local/notes.md", "text": "hello body"}],
    )
    assert first[0]["workspace_path"] == "attachments/notes.md"
    assert first[0]["text"] == "hello body"
    assert (root / "attachments" / "notes.md").read_text(encoding="utf-8") == "hello body"

    # Simulate a later drain: mutate disk so a rewrite would be visible.
    (root / "attachments" / "notes.md").write_text("SHOULD_NOT_OVERWRITE", encoding="utf-8")
    second = await persist_attachments(ws, first)
    assert second[0]["workspace_path"] == "attachments/notes.md"
    assert second[0]["text"] == "hello body"
    assert (root / "attachments" / "notes.md").read_text(encoding="utf-8") == (
        "SHOULD_NOT_OVERWRITE"
    )


@pytest.mark.asyncio
async def test_queue_user_message_enqueues_and_emits_queued():
    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    session.stash_interjection(
        "inj-1",
        {
            "content": "无关的贺卡请求",
            "user_id": "u1",
            "conversation_id": "conv-inj",
            "attachments": [],
            "requires_tools": False,
        },
    )
    session.post(
        CoordinationEvent(
            kind=CoordinationEventKind.USER_INTERJECTION,
            payload={"interjection_id": "inj-1", "content": "无关的贺卡请求"},
        )
    )

    sink = EventSink()
    tool = QueueUserMessageTool(sink=sink)
    ctx = ToolContext(
        execution_id="exec-inj",
        run_id="ceo",
        agent_id="ceo",
        backend=MagicMock(),
        user_id="u1",
        conversation_id="conv-inj",
    )
    result = await tool.execute(
        {"interjection_id": "inj-1", "reason": "无关"},
        ctx,
    )
    assert result.success is True
    assert turn_queue.depth("conv-inj") == 1
    assert session.get_interjection("inj-1") is None

    hist = list(sink._history)
    types = [e.type.value for e in hist]
    assert "user_interjection" in types
    last = next(e for e in reversed(hist) if e.type.value == "user_interjection")
    assert last.payload["status"] == "queued"
    assert last.payload["interjection_id"] == "inj-1"


@pytest.mark.asyncio
async def test_queue_user_message_works_after_session_closed():
    """收口后 queue 不再死路——仍可升格 FIFO（或幂等确认已处置）。"""
    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    session.stash_interjection(
        "inj-late",
        {
            "content": "收口瞬间插话",
            "user_id": "u1",
            "conversation_id": "conv-inj",
            "attachments": [],
            "requires_tools": False,
        },
    )
    session.close()
    # close 已自动 promote → FIFO；再调 queue 应幂等成功，不报「不在协调模式」。
    assert turn_queue.depth("conv-inj") == 1
    assert "inj-late" in session.dispositioned_interjections

    sink = EventSink()
    tool = QueueUserMessageTool(sink=sink)
    ctx = ToolContext(
        execution_id="exec-inj",
        run_id="ceo",
        agent_id="ceo",
        backend=MagicMock(),
        user_id="u1",
        conversation_id="conv-inj",
    )
    result = await tool.execute({"interjection_id": "inj-late", "reason": "无关"}, ctx)
    assert result.success is True
    assert "已转入" in (result.output or "") or "已消化" in (result.output or "")


@pytest.mark.asyncio
async def test_close_promotes_unseen_pending_to_fifo():
    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    sink = EventSink()
    session.event_sink = sink
    session.stash_interjection(
        "inj-auto",
        {
            "content": "未消化短讯",
            "user_id": "u1",
            "conversation_id": "conv-inj",
            "attachments": [],
            "requires_tools": False,
        },
    )
    session.close()
    assert turn_queue.depth("conv-inj") == 1
    assert session.get_interjection("inj-auto") is None
    last = next(e for e in reversed(list(sink._history)) if e.type.value == "user_interjection")
    assert last.payload["status"] == "queued"


@pytest.mark.asyncio
async def test_update_synthesis_addresses_awaiting_interjection():
    from agentcore.runtime.coordination.interjections import note_interjections_injected
    from agentcore.runtime.coordination.tools import UpdateSynthesisTool

    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    session.stash_interjection(
        "inj-rel",
        {
            "content": "请点明成本",
            "user_id": "u1",
            "conversation_id": "conv-inj",
            "attachments": [],
            "requires_tools": False,
        },
    )
    note_interjections_injected(
        session,
        [
            CoordinationEvent(
                kind=CoordinationEventKind.USER_INTERJECTION,
                payload={"interjection_id": "inj-rel", "content": "请点明成本"},
            )
        ],
    )
    sink = EventSink()
    tool = UpdateSynthesisTool(sink=sink)
    ctx = ToolContext(
        execution_id="exec-inj",
        run_id="ceo",
        agent_id="ceo",
        backend=MagicMock(),
        user_id="u1",
        conversation_id="conv-inj",
    )
    result = await tool.execute({"draft": "已收到：成品会点明成本。"}, ctx)
    assert result.success is True
    assert session.get_interjection("inj-rel") is None
    last = next(e for e in reversed(list(sink._history)) if e.type.value == "user_interjection")
    assert last.payload["status"] == "addressed"


@pytest.mark.asyncio
async def test_queue_user_message_preserves_resident_attachments():
    session = CoordinationSession(
        execution_id="exec-inj",
        total_workers=2,
        conversation_id="conv-inj",
    )
    set_active_coordination(session)
    resident = [
        {
            "name": "notes.md",
            "path": "/x/notes.md",
            "text": "inline kept",
            "workspace_path": "attachments/notes.md",
            "binary": False,
        }
    ]
    session.stash_interjection(
        "inj-att",
        {
            "content": "无关但带附件",
            "user_id": "u1",
            "conversation_id": "conv-inj",
            "attachments": resident,
            "requires_tools": False,
        },
    )

    sink = EventSink()
    tool = QueueUserMessageTool(sink=sink)
    ctx = ToolContext(
        execution_id="exec-inj",
        run_id="ceo",
        agent_id="ceo",
        backend=MagicMock(),
        user_id="u1",
        conversation_id="conv-inj",
    )
    result = await tool.execute({"interjection_id": "inj-att", "reason": "无关"}, ctx)
    assert result.success is True

    queued = turn_queue.pop_next("conv-inj")
    assert queued is not None
    assert queued.attachments == resident
    assert queued.attachments[0]["text"] == "inline kept"
    assert queued.attachments[0]["workspace_path"] == "attachments/notes.md"

    hist = list(sink._history)
    last = next(e for e in reversed(hist) if e.type.value == "user_interjection")
    assert last.payload["status"] == "queued"
    assert last.payload["attachments"] == [
        {
            "name": "notes.md",
            "workspace_path": "attachments/notes.md",
            "binary": False,
        }
    ]


@pytest.mark.asyncio
async def test_wait_events_surfaces_user_interjection():
    session = CoordinationSession(execution_id="e2", total_workers=2)

    async def _post_soon() -> None:
        await asyncio.sleep(0.01)
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.USER_INTERJECTION,
                payload={"interjection_id": "i", "content": "hi"},
            )
        )

    asyncio.create_task(_post_soon())
    batch = await session.wait_events(timeout=1.0)
    assert len(batch) == 1
    assert batch[0].kind is CoordinationEventKind.USER_INTERJECTION

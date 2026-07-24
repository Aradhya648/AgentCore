"""Sidecar local-turn recording assembly (DEMO_TAPE_RECORD_ENABLED symmetry)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agentcore.demo_tape.schema import RECORDING_FORMAT_VERSION
from agentcore.runtime.events import (
    EventSink,
    EventType,
    FinishReason,
    message_end,
    message_start,
)
from agentcore.runtime.events import sink as sink_module
from agentcore.runtime.events.types import SSEEvent
from agentcore.sidecar.server import SidecarServer


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    sent: list[dict[str, Any]] = []

    async def write_line(line: str) -> None:
        sent.append(json.loads(line))

    return sent, write_line


async def _initialize(
    server: SidecarServer, tmp_path: Path, *, data_dir: str | None
) -> None:
    params: dict[str, Any] = {
        "userId": "u",
        "workspaceRoot": str(tmp_path),
        "approvalsEnabled": True,
    }
    if data_dir is not None:
        params["dataDir"] = data_dir
    await server.handle_line(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})
    )


def test_sidecar_initialize_installs_recorder_when_enabled(monkeypatch, tmp_path):
    from agentcore.config import settings
    from agentcore.demo_tape import recorder

    monkeypatch.setattr(settings, "demo_tape_record_enabled", True)
    data = tmp_path / "sidecar-data"
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    asyncio.run(_initialize(server, tmp_path, data_dir=str(data)))

    assert sink_module._emit_tap is not None
    assert recorder.recordings_dir() == data / "recordings"
    assert (data / "recordings").is_dir()

    sink = EventSink(conversation_id="conv-sc", message_id="msg-sc")
    sink.emit(message_start("msg-sc", conversation_id="conv-sc"))
    sink.emit(SSEEvent(type=EventType.CONTENT_DELTA, payload={"delta": "本地回合"}))
    sink.emit(message_end(FinishReason.END_TURN))

    path = data / "recordings" / "msg-sc.json"
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == RECORDING_FORMAT_VERSION
    assert raw["kind"] == "demo_tape_recording"
    events = raw["segments"][0]["events"]
    assert [e["type"] for e in events] == [
        "message_start",
        "content_delta",
        "message_end",
    ]
    assert all("type" in e and "timestamp" in e and "t_ms" in e for e in events)
    assert all("kind" not in e for e in events)


def test_sidecar_initialize_skips_recorder_when_disabled(monkeypatch, tmp_path):
    from agentcore.config import settings

    monkeypatch.setattr(settings, "demo_tape_record_enabled", False)
    data = tmp_path / "sidecar-data"
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    asyncio.run(_initialize(server, tmp_path, data_dir=str(data)))

    assert sink_module._emit_tap is None
    assert not (data / "recordings").exists()


def test_sidecar_initialize_skips_recorder_without_data_dir(monkeypatch, tmp_path):
    from agentcore.config import settings

    monkeypatch.setattr(settings, "demo_tape_record_enabled", True)
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    asyncio.run(_initialize(server, tmp_path, data_dir=None))

    assert sink_module._emit_tap is None

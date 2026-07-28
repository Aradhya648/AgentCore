"""Sidecar Slice 1 walking-skeleton tests (双模式工作区 / 远期规划 §一.1).

Two layers, both zero-LLM (a scripted provider stands in for DeepSeek, mirroring
``test_evals_smoke``):

- **protocol** — line framing round-trips and rejects garbage (pure).
- **server** — a full turn driven over ``handle_line``: ``initialize`` binds a real
  local directory, ``startTurn`` runs ``run_chat_pipeline`` against it, the engine's
  events surface as ``turn/event`` notifications, and the deferred startTurn
  response carries the final answer. The turn issues a ``file_list`` against the
  bound temp dir, proving the engine touches the REAL local disk (not a channel).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentcore.config import settings
from agentcore.llm.credentials import (
    INFERENCE_CONVERSATION_HEADER,
    INFERENCE_MESSAGE_HEADER,
    INFERENCE_TRACE_HEADER,
    LLMCredentials,
)
from agentcore.llm.provider.protocol import LLMChunk, TokenUsage, ToolCallDelta
from agentcore.runtime.approvals import ApprovalDecision
from agentcore.runtime.interaction import InteractionKind, default_interaction_registry
from agentcore.sidecar import protocol
from agentcore.sidecar.server import SidecarServer


class _ScriptedProvider:
    """Yields one pre-scripted round of chunks per ``stream`` call (duck-typed)."""

    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0

    async def stream(self, request):  # noqa: ANN001 - duck-typed stand-in
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk

    async def close(self) -> None:  # pipeline calls this in its finally
        return None


# --- protocol (pure) ---------------------------------------------------------


def test_protocol_round_trip_keeps_one_physical_line():
    line = protocol.encode_line(
        protocol.make_notification("turn/event", {"x": "中文\nwith newline"})
    )
    assert line.endswith("\n")
    # The newline INSIDE the string must be JSON-escaped, so the only raw newline
    # is the trailing frame terminator — one message is always one readline.
    assert "\n" not in line[:-1]

    message = protocol.decode_line(line)
    assert message["method"] == "turn/event"
    assert message["params"]["x"] == "中文\nwith newline"


def test_protocol_rejects_non_object():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_line("[1, 2, 3]")
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_line("{not json}")


def test_protocol_tolerates_leading_bom():
    # A stray UTF-8 BOM on the first line (some text producers prepend one) must
    # not break the decode — json.loads alone would reject it.
    message = protocol.decode_line('\ufeff{"jsonrpc":"2.0","id":1,"method":"x"}')
    assert message["method"] == "x"


# --- server ------------------------------------------------------------------


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    sent: list[dict[str, Any]] = []

    async def write_line(line: str) -> None:
        sent.append(json.loads(line))

    return sent, write_line


def _response(sent: list[dict[str, Any]], request_id: Any) -> dict[str, Any]:
    return next(m for m in sent if m.get("id") == request_id)


def _events(sent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"]["event"] for m in sent if m.get("method") == "turn/event"]


def test_initialize_rejects_missing_root(tmp_path):
    sent, write_line = _recorder()
    server = SidecarServer(write_line)
    missing = tmp_path / "does-not-exist"

    asyncio.run(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"userId": "u", "workspaceRoot": str(missing)},
                }
            )
        )
    )

    resp = _response(sent, 1)
    assert "error" in resp
    assert resp["error"]["code"] == protocol.INVALID_PARAMS


def test_start_turn_before_initialize_is_refused(tmp_path):
    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    asyncio.run(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "startTurn",
                    "params": {"turnId": "t", "conversationId": "c", "userMessage": "hi"},
                }
            )
        )
    )

    resp = _response(sent, 9)
    assert resp["error"]["code"] == protocol.NOT_INITIALIZED


def test_sidecar_runs_a_turn_on_the_local_dir(tmp_path, monkeypatch):
    # Seed a real file in the directory the sidecar will be bound to.
    (tmp_path / "hello.txt").write_text("hi from disk", encoding="utf-8")

    # Round 0: the CEO calls file_list against the bound dir. Round 1: it answers.
    provider = _ScriptedProvider(
        [
            [
                LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="call_ls",
                            function_name="file_list",
                            arguments_delta='{"directory": ".", "pattern": "*"}',
                        )
                    ]
                ),
                LLMChunk(
                    finish_reason="tool_calls",
                    usage=TokenUsage(input_tokens=10, output_tokens=4),
                ),
            ],
            [
                LLMChunk(delta_content="已列出本地文件。"),
                LLMChunk(
                    finish_reason="stop",
                    usage=TokenUsage(input_tokens=5, output_tokens=3),
                ),
            ],
        ]
    )
    # The engine builds its provider via build_turn_router — swap that seam for the
    # scripted one (mirrors the eval harness note: team path has no provider injection seam).
    async def _fake_build_turn_router(*_a, **_k):
        return provider

    monkeypatch.setattr(
        "agentcore.runtime.pipeline.build_turn_router", _fake_build_turn_router
    )

    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def drive() -> None:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": "u",
                        "workspaceRoot": str(tmp_path),
                        "approvalsEnabled": False,
                    },
                }
            )
        )
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "startTurn",
                    "params": {
                        "turnId": "t1",
                        "conversationId": "c1",
                        "userMessage": "列出本地文件",
                    },
                }
            )
        )
        # The startTurn response is deferred to turn completion — await the task.
        await asyncio.gather(*list(server._turns.values()))

    asyncio.run(drive())

    # initialize acknowledged.
    init = _response(sent, 1)
    assert init["result"]["ok"] is True
    assert init["result"]["protocolVersion"] == protocol.PROTOCOL_VERSION

    # The turn streamed events, ran the tool against the REAL dir, and answered.
    events = _events(sent)
    types = [e["type"] for e in events]
    assert "tool_use_start" in types
    assert "content_delta" in types
    assert "message_end" in types

    tool_start = next(e for e in events if e["type"] == "tool_use_start")
    assert tool_start["payload"]["tool_name"] == "file_list"

    tool_end = next(e for e in events if e["type"] == "tool_use_end")
    # The engine listed the bound temp dir → it saw the seeded file (real disk).
    assert "hello.txt" in tool_end["payload"]["result"]

    # The deferred startTurn response carries the final answer.
    done = _response(sent, 2)
    assert done["result"]["content"] == "已列出本地文件。"
    assert done["result"]["finishReason"] == "end_turn"
    assert done["result"]["turnId"] == "t1"
    # No inference at initialize ⇒ the turn ran on the dev platform-model fallback, and the
    # result honestly reports it (resolve_turn_model over None creds). The desktop badge
    # reads this to show the model the turn ACTUALLY ran on, not just the account config.
    assert done["result"]["model"] == settings.platform_model


# --- respond (审批 / 交互结算回 sidecar) -------------------------------------


def test_respond_settles_approval_with_enum_decision():
    """respond builds the SAME typed result the cloud route does: an approval settles
    with an ApprovalDecision *enum*, not a bare string. The gate's grant check uses
    identity (``decision is ApprovalDecision.APPROVE_ALWAYS``), so a raw string would
    silently fail it — this guards that the sidecar/cloud construction stays shared.
    """
    registry = default_interaction_registry()
    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def drive() -> Any:
        fut = registry.create("call_1", "c1", kind=InteractionKind.APPROVAL)
        try:
            await server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "respond",
                        "params": {
                            "requestId": "call_1",
                            "conversationId": "c1",
                            "result": {
                                "kind": "approval",
                                "decision": "approve_always",
                            },
                        },
                    }
                )
            )
            return fut.result() if fut.done() else None
        finally:
            registry.discard("call_1")

    decision = asyncio.run(drive())
    assert _response(sent, 1)["result"]["resolved"] is True
    assert decision is ApprovalDecision.APPROVE_ALWAYS


def test_respond_refuses_kind_mismatch():
    """A respond whose kind ≠ the pending interaction's kind is refused
    (``resolved: false``) and leaves the Future pending — mirrors the cloud route's
    kind guard, so a stray approval can't settle a plan_review (or vice versa)."""
    registry = default_interaction_registry()
    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def drive() -> bool:
        fut = registry.create("cp_1", "c1", kind=InteractionKind.PLAN_REVIEW)
        try:
            await server.handle_line(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "respond",
                        "params": {
                            "requestId": "cp_1",
                            "conversationId": "c1",
                            "result": {"kind": "approval", "decision": "approve"},
                        },
                    }
                )
            )
            return fut.done()
        finally:
            registry.discard("cp_1")

    settled = asyncio.run(drive())
    assert _response(sent, 1)["result"]["resolved"] is False
    assert settled is False


def test_respond_rejects_malformed_result():
    """A respond whose result fails validation (the kind's required field missing)
    returns INVALID_PARAMS, not a silent no-op."""
    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    asyncio.run(
        server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "respond",
                    "params": {
                        "requestId": "x",
                        "conversationId": "c1",
                        "result": {"kind": "approval"},  # missing `decision`
                    },
                }
            )
        )
    )

    resp = _response(sent, 1)
    assert resp["error"]["code"] == protocol.INVALID_PARAMS


def test_sidecar_binds_local_backend_with_approvals(tmp_path, monkeypatch):
    """The sidecar binds a ``location="local"`` workspace (root = the user's real disk)
    and runs the turn with approvals on — so the engine forwards the gate to a worker's
    machine-touching tools (delegate keys off ``backend.location == "local"``). A default
    ``"server"`` backend would leave workers un-gated even with approvals enabled.
    """
    captured: dict[str, Any] = {}

    async def fake_pipeline(**kwargs: Any) -> dict[str, Any]:
        captured["location"] = kwargs["backend"].location
        captured["approvals_enabled"] = kwargs["approvals_enabled"]
        kwargs["sink"].close()  # let the event pump drain and the turn finish
        return {"finish_reason": "end_turn", "content": "ok", "rounds": 1}

    monkeypatch.setattr("agentcore.sidecar.server.run_chat_pipeline", fake_pipeline)

    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def drive() -> None:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": "u",
                        "workspaceRoot": str(tmp_path),
                        "approvalsEnabled": True,
                    },
                }
            )
        )
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "startTurn",
                    "params": {
                        "turnId": "t1",
                        "conversationId": "c1",
                        "userMessage": "改个文件",
                    },
                }
            )
        )
        await asyncio.gather(*list(server._turns.values()))

    asyncio.run(drive())
    assert captured["location"] == "local"
    assert captured["approvals_enabled"] is True


def test_sidecar_threads_permission_preset_per_turn(tmp_path, monkeypatch):
    """Conversation permission mode reaches the local engine: initialize seeds it,
    a per-turn ``permissionPreset`` refreshes it, and an absent param keeps the
    current value — never a silent reset to the default.
    """
    from agentcore.core.types import AutonomyPolicy

    captured: list[tuple[AutonomyPolicy]] = []

    async def fake_pipeline(**kwargs: Any) -> dict[str, Any]:
        captured.append((kwargs["permission_axes"], kwargs["permission_preset"]))
        kwargs["sink"].close()
        return {"finish_reason": "end_turn", "content": "ok", "rounds": 1}

    monkeypatch.setattr("agentcore.sidecar.server.run_chat_pipeline", fake_pipeline)

    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def start_turn(turn_id: str, extra: dict[str, Any]) -> None:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": turn_id,
                    "method": "startTurn",
                    "params": {
                        "turnId": turn_id,
                        "conversationId": "c1",
                        "userMessage": "跑点代码",
                        **extra,
                    },
                }
            )
        )
        await asyncio.gather(*list(server._turns.values()))

    async def drive() -> None:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": "u",
                        "workspaceRoot": str(tmp_path),
                        "permissionPreset": "full_trust",
                    },
                }
            )
        )
        await start_turn("t1", {})  # no per-turn value → the initialize seed applies
        await start_turn("t2", {"permissionPreset": "observe"})  # per-turn refresh
        await start_turn("t3", {})  # absent again → keeps the refreshed value

    asyncio.run(drive())
    assert captured == [
        (AutonomyPolicy.MANAGED.FULL_TRUST),
        (AutonomyPolicy.CAUTIOUS.OBSERVE),
        (AutonomyPolicy.CAUTIOUS.OBSERVE),
    ]


def test_creds_for_stamps_conversation_and_trace_headers():
    """Each turn's proxy creds carry the conversation header (spend attribution) AND the
    trace header (so every proxied LLM call joins the turn's trace, 打通气泡↔日志). An
    empty trace_id (untraced caller) omits the header rather than sending a blank."""
    server = SidecarServer(_recorder()[1])
    server._creds = LLMCredentials(api_key="tok", base_url="https://x/v1/inference")

    traced = server._creds_for("conv-1", "0123456789abcdef0123456789abcdef")
    assert traced.extra_headers[INFERENCE_CONVERSATION_HEADER] == "conv-1"
    assert traced.extra_headers[INFERENCE_TRACE_HEADER] == ("0123456789abcdef0123456789abcdef")

    untraced = server._creds_for("conv-1")
    assert untraced.extra_headers[INFERENCE_CONVERSATION_HEADER] == "conv-1"
    assert INFERENCE_TRACE_HEADER not in untraced.extra_headers

    with_message = server._creds_for("conv-1", "trace-1", "msg-42")
    assert with_message.extra_headers[INFERENCE_MESSAGE_HEADER] == "msg-42"


def test_creds_for_none_when_no_session_creds():
    """No session creds (dev platform-fallback, no proxy) ⇒ no per-turn creds to stamp."""
    server = SidecarServer(_recorder()[1])
    assert server._creds is None
    assert server._creds_for("conv-1", "trace-1") is None


def test_parse_inference_carries_server_resolved_model():
    creds = SidecarServer._parse_inference(
        {
            "baseUrl": "http://localhost:8000/v1/inference/v1",
            "apiKey": "tok",
            "model": "deepseek-v4-flash",
        }
    )
    assert creds is not None
    assert creds.default_model == "deepseek-v4-flash"
    assert creds.base_url.endswith("/v1/inference/v1")


def test_start_turn_result_reports_cloud_proxy_model(tmp_path, monkeypatch):
    """With inference creds (cloud proxy present), the turn result reports the
    server-resolved account model (resolve_turn_model over the creds), NOT the platform
    fallback — this is the signal the desktop badge shows so it reflects the model the
    turn ACTUALLY ran on. Pairs with the no-inference fallback assertion above."""

    async def fake_pipeline(**kwargs: Any) -> dict[str, Any]:
        # The turn must run on the cloud-proxy creds, not the dev platform fallback.
        assert kwargs["llm_credentials"] is not None
        kwargs["sink"].close()  # let the pump drain so the turn finishes
        return {"finish_reason": "end_turn", "content": "ok", "rounds": 1}

    monkeypatch.setattr("agentcore.sidecar.server.run_chat_pipeline", fake_pipeline)

    sent, write_line = _recorder()
    server = SidecarServer(write_line)

    async def drive() -> None:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": "u",
                        "workspaceRoot": str(tmp_path),
                        "approvalsEnabled": False,
                        "inference": {
                            "baseUrl": "http://localhost:8000/v1/inference/v1",
                            "apiKey": "tok",
                            "model": "deepseek-v4-flash",
                        },
                    },
                }
            )
        )
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "startTurn",
                    "params": {"turnId": "t1", "conversationId": "c1", "userMessage": "hi"},
                }
            )
        )
        await asyncio.gather(*list(server._turns.values()))

    asyncio.run(drive())

    done = _response(sent, 2)
    assert done["result"]["model"] == "deepseek-v4-flash"

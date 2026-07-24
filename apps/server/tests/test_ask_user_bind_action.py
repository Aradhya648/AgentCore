"""ask_user option ``action`` normalize + schema advertising."""

import json

import pytest

from agentcore.runtime.events import EventSink
from agentcore.tools.builtin.ask_user.schema import (
    ListArgError,
    normalize_options,
    normalize_questions,
)
from agentcore.tools.builtin.ask_user.tool import AskUserTool


def test_normalize_options_preserves_bind_local_folder_action():
    out = normalize_options(
        [
            {"label": "绑定本地文件夹", "action": "bind_local_folder", "recommended": True},
            {"label": "继续用云端", "detail": "无法打开本机应用"},
            {"label": "坏动作", "action": "hack_the_planet"},
            {"label": "授权只读目录", "action": "grant_readonly_folder"},
            {"label": "授权整理目录", "action": "grant_organize_folder"},
        ]
    )
    assert out[0]["action"] == "bind_local_folder"
    assert out[0]["recommended"] is True
    assert "action" not in out[1]
    assert "action" not in out[2]  # unknown actions drop
    assert out[3]["action"] == "grant_readonly_folder"
    assert out[4]["action"] == "grant_organize_folder"


def test_normalize_questions_passthrough_to_checkpoint_shape():
    qs = normalize_questions(
        [
            {
                "prompt": "如何对齐工作区？",
                "kind": "choice",
                "options": [
                    {"label": "绑定本地文件夹", "action": "bind_local_folder"},
                    {"label": "先用云端"},
                ],
            }
        ]
    )
    assert qs[0]["options"][0]["action"] == "bind_local_folder"
    assert "action" not in qs[0]["options"][1]


def test_normalize_questions_accepts_json_encoded_array_string():
    """Model double-encoding: questions arrives as a JSON array string, not a list."""
    payload = [
        {
            "prompt": "篇幅？",
            "kind": "choice",
            "options": [{"label": "短"}, {"label": "中"}, {"label": "长"}],
        },
        {"prompt": "受众？", "kind": "text"},
    ]
    qs = normalize_questions(json.dumps(payload, ensure_ascii=False))
    assert len(qs) == 2
    assert qs[0]["prompt"] == "篇幅？"
    assert len(qs[0]["options"]) == 3
    assert qs[1]["kind"] == "text"


def test_normalize_options_accepts_json_encoded_array_string():
    opts = normalize_options(json.dumps([{"label": "A"}, {"label": "B"}], ensure_ascii=False))
    assert [o["label"] for o in opts] == ["A", "B"]


def test_normalize_questions_rejects_non_array_json_string():
    with pytest.raises(ListArgError, match="questions"):
        normalize_questions('{"prompt": "不是数组"}')


def test_normalize_questions_rejects_garbage_string():
    with pytest.raises(ListArgError, match="questions"):
        normalize_questions("[{broken")


async def test_ask_user_rejects_unparseable_questions_string():
    """Garbage string must fail the tool — not open an empty-option kickoff card."""
    tool = AskUserTool(
        sink=EventSink(),
        conversation_id="c1",
        timeout_seconds=1.0,
    )
    from pathlib import Path

    from agentcore.tools.protocol import ToolContext
    from agentcore.tools.sandbox.subprocess import SubprocessSandbox
    from agentcore.workspace.server import ServerWorkspace

    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c1",
    )
    res = await tool.execute(
        {"message": "对齐一下方向", "questions": "[{broken"},
        ctx,
    )
    assert res.success is False
    assert res.error and "questions" in res.error
    assert "数组" in (res.error or "")


def test_ask_user_schema_advertises_action_only_when_flagged():
    sink = EventSink()
    base = dict(
        sink=sink,
        conversation_id="c1",
        timeout_seconds=30.0,
    )
    plain = AskUserTool(**base, advertise_bind_local_folder=False)
    props = plain.schema.parameters["properties"]["questions"]["items"]["properties"]["options"][
        "items"
    ]["properties"]
    assert "action" not in props
    assert "bind_local_folder" not in plain.schema.description

    advertised = AskUserTool(**base, advertise_bind_local_folder=True)
    props2 = advertised.schema.parameters["properties"]["questions"]["items"]["properties"][
        "options"
    ]["items"]["properties"]
    assert props2["action"]["enum"] == [
        "bind_local_folder",
        "grant_readonly_folder",
        "grant_organize_folder",
    ]
    assert "bind_local_folder" in advertised.schema.description
    assert "grant_readonly_folder" in advertised.schema.description
    assert "grant_organize_folder" in advertised.schema.description

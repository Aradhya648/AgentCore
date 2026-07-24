"""Tests for the attachment system-prompt block (`_build_attachment_context`).

Pins what the model sees: nothing injected when there are no usable attachments,
local path for un-resident files, the durable in-workspace path + an edit hint
once an attachment has been persisted (附件驻留), and directory listings shown as
paths only.
"""

from agentcore.runtime.pipeline import _build_attachment_context


def test_none_and_empty_return_none():
    assert _build_attachment_context(None) is None
    assert _build_attachment_context([]) is None
    # A file whose text is blank contributes no block → still None.
    assert _build_attachment_context([{"name": "x", "text": "   "}]) is None


def test_unresident_file_uses_local_path_no_hint():
    out = _build_attachment_context([{"name": "a.py", "path": "/local/a.py", "text": "print(1)"}])
    assert out is not None
    assert "--- File: a.py (/local/a.py) ---" in out
    assert "print(1)" in out
    assert "saved into your workspace" not in out


def test_resident_file_uses_workspace_path_and_hint():
    out = _build_attachment_context(
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


def test_binary_resident_has_no_inline_body():
    out = _build_attachment_context(
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


def test_truncated_note_and_directory_listing():
    out = _build_attachment_context(
        [
            {"name": "big.txt", "path": "/big.txt", "text": "partial", "truncated": True},
            {"name": "src", "path": "/src", "text": "a.py\nb.py", "kind": "dir"},
        ]
    )
    assert "--- File: big.txt (/big.txt) (truncated) ---" in out
    assert "--- Directory: src (/src) ---" in out
    assert "File paths (contents not included):" in out


def test_conversation_reference_rendered():
    out = _build_attachment_context(
        [
            {
                "name": "讨论 X 方案",
                "path": "对话",
                "text": "用户: 你好\n\n助手: 在的",
                "kind": "conversation",
                "conversation_id": "conv-1",
            }
        ]
    )
    assert out is not None
    # A conversation renders as its own block — no path, no residency hint.
    assert "--- Conversation: 讨论 X 方案 ---" in out
    assert "用户: 你好" in out
    assert "助手: 在的" in out
    # The guidance now mentions past conversations as a reference kind.
    assert "past" in out
    assert "saved into your workspace" not in out


def test_conversation_reference_truncated_note():
    out = _build_attachment_context(
        [
            {
                "name": "长对话",
                "text": "用户: 一些内容",
                "kind": "conversation",
                "truncated": True,
            }
        ]
    )
    assert "--- Conversation: 长对话 (recent messages only) ---" in out

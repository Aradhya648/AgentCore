"""Failed-turn history notes for next-turn prompt attribution."""

from types import SimpleNamespace

from agentcore.conversation.history import (
    _failure_note,
    _fold_history_messages,
    _is_failed_empty_assistant,
)
from agentcore.core.error_codes import ErrorCode


def _msg(role, content="", *, status=None, error_code=None, finish_reason=None):
    usage = {}
    if status is not None:
        usage["status"] = status
    if error_code is not None:
        usage["error_code"] = error_code
    if finish_reason is not None:
        usage["finish_reason"] = finish_reason
    return SimpleNamespace(role=role, content=content, usage=usage or None)


def test_failed_empty_assistant_detection():
    assert _is_failed_empty_assistant(
        _msg("assistant", "", status="failed", error_code=ErrorCode.LLM_TIMEOUT)
    )
    assert not _is_failed_empty_assistant(_msg("assistant", "ok", status="failed"))
    assert not _is_failed_empty_assistant(_msg("user", "hi"))


def test_fold_merges_consecutive_failures_into_one_note():
    rows = [
        _msg("user", "第一问"),
        _msg("assistant", "", status="failed", error_code=ErrorCode.LLM_TIMEOUT),
        _msg("user", "再试"),
        _msg("assistant", "", status="failed", error_code=ErrorCode.LLM_TIMEOUT),
        _msg("assistant", "", status="failed", error_code=ErrorCode.LLM_KEY_INVALID),
        _msg("user", "换个说法"),
        _msg("assistant", "正常回答"),
    ]
    out = _fold_history_messages(rows)
    assert out[0] == {"role": "user", "content": "第一问"}
    assert "连接超时" in out[1]["content"]
    assert out[1]["role"] == "assistant"
    assert out[2] == {"role": "user", "content": "再试"}
    # Two consecutive failures → one note mentioning both categories.
    note = out[3]["content"]
    assert "连续 2 轮" in note
    assert "连接超时" in note
    assert "鉴权失败" in note
    assert out[4] == {"role": "user", "content": "换个说法"}
    assert out[5] == {"role": "assistant", "content": "正常回答"}


def test_failure_note_single():
    note = _failure_note(["连接超时"])
    assert "上一轮" in note["content"]
    assert "连接超时" in note["content"]
    assert "不要编造" in note["content"]

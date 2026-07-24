"""Empty-response diagnosis helpers."""

import json

from agentcore.llm.errors import (
    EmptyResponseDiagnosis,
    diagnose_empty_response,
    empty_response_event_message,
)


def test_diagnose_content_filtered():
    body = json.dumps(
        {
            "choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}],
        }
    )
    assert (
        diagnose_empty_response(raw_body=body, finish_reason="content_filter")
        is EmptyResponseDiagnosis.CONTENT_FILTERED
    )


def test_diagnose_oauth_html():
    body = "<html><body>Please sign in to continue</body></html>"
    assert (
        diagnose_empty_response(raw_body=body)
        is EmptyResponseDiagnosis.OAUTH_EXPIRED
    )


def test_diagnose_model_unknown():
    body = json.dumps({"error": {"message": "model not found: foo"}})
    assert (
        diagnose_empty_response(raw_body=body)
        is EmptyResponseDiagnosis.MODEL_UNKNOWN
    )


def test_diagnose_silent_empty():
    body = json.dumps(
        {
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
        }
    )
    assert (
        diagnose_empty_response(raw_body=body, finish_reason="stop")
        is EmptyResponseDiagnosis.SILENT_EMPTY
    )


def test_diagnose_format_mismatch():
    assert (
        diagnose_empty_response(raw_body="not-json {{{", format_mismatch=True)
        is EmptyResponseDiagnosis.FORMAT_MISMATCH
    )


def test_diagnose_streaming_empty_tail_is_silent_not_format_mismatch():
    """A clean tool_calls/stop finish with empty deltas is silent-empty, not a
    format error — the SSE tail (many ``data:`` lines) isn't valid JSON but that
    alone must not be misread as 上游响应格式异常 (only ``format_mismatch=True`` is)."""
    sse_tail = (
        'data: {"choices": [{"index": 0, "delta": {}, "finish_reason": null}]}\n\n'
        'data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}], '
        '"usage": {"prompt_tokens": 12161, "completion_tokens": 600}}\n\n'
        "data: [DONE]"
    )
    assert (
        diagnose_empty_response(raw_body=sse_tail, finish_reason="tool_calls")
        is EmptyResponseDiagnosis.SILENT_EMPTY
    )


def test_empty_response_event_message_appends_diagnosis():
    msg = empty_response_event_message(EmptyResponseDiagnosis.SILENT_EMPTY)
    assert msg.startswith("模型多次空响应")
    assert "模型返回空内容" in msg

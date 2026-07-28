from agentcore.core.errors import LLMRateLimitError
from agentcore.core.error_codes import ErrorCode
from agentcore.llm.errors import error_context_from

def test_rate_limit_error_zh_message_short_retry():
    e = LLMRateLimitError(retry_after=12)
    assert e.code == ErrorCode.LLM_RATE_LIMIT
    assert "上游限流" in e.message
    assert "12" in e.message
    ctx = error_context_from(e)
    assert ctx is not None
    assert ctx.get("retry_after") == 12.0


def test_rate_limit_error_zh_message_long_retry_no_hour_promise():
    e = LLMRateLimitError(retry_after=3600)
    assert "上游限流" in e.message
    assert "3600" not in e.message
    assert "一小时" not in e.message
    ctx = error_context_from(e)
    assert ctx is not None
    assert ctx.get("retry_after") == 3600.0
"""Unit tests for side-path LLM failure reason buckets."""

from agentcore.core.errors import LLMAuthError, LLMTimeoutError, LLMUpstreamError
from agentcore.llm.background_failure import classify_background_llm_failure


def test_classify_auth():
    assert classify_background_llm_failure(LLMAuthError()) == "auth"


def test_classify_timeout():
    assert classify_background_llm_failure(TimeoutError()) == "timeout"
    assert classify_background_llm_failure(LLMTimeoutError("t")) == "timeout"


def test_classify_upstream():
    assert (
        classify_background_llm_failure(LLMUpstreamError("503", upstream_status=503))
        == "upstream_unstable"
    )


def test_classify_provider_unavailable_message():
    assert (
        classify_background_llm_failure(RuntimeError("background credentials unavailable"))
        == "provider_unavailable"
    )


def test_classify_other():
    assert classify_background_llm_failure(RuntimeError("network down")) == "other"

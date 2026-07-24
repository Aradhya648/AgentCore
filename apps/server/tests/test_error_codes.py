"""Error-code catalog + classifier contract (统一错误码共享目录).

Guards the single ``ErrorCode`` directory: every ``AgentCoreError`` uses a
catalogued code, the wire value equals the member name (so the frontend mirror
``contract-types/errorCodes.ts`` and the logs match on the same string), and
``error_fields_for`` preserves a coded error's code/message while only collapsing
an unrecognized crash to the fallback (避免 pipeline 把多种错误压成 PIPELINE_ERROR).
"""

import inspect

from agentcore.core import errors as errors_module
from agentcore.core.error_codes import ErrorCode
from agentcore.core.errors import (
    AgentCoreError,
    LLMAuthError,
    LLMInsufficientBalanceError,
    error_fields_for,
)


def _all_error_classes() -> list[type[AgentCoreError]]:
    return [
        obj
        for _, obj in inspect.getmembers(errors_module, inspect.isclass)
        if issubclass(obj, AgentCoreError)
    ]


def test_every_error_class_code_is_catalogued():
    catalog = set(ErrorCode)
    for cls in _all_error_classes():
        assert cls.code in catalog, (
            f"{cls.__name__}.code={cls.code!r} is not in the ErrorCode catalog — "
            "add it to core/error_codes.py then run `pnpm gen:types`."
        )


def test_error_code_value_equals_name():
    # The wire value is the member name verbatim (UPPER_SNAKE); the frontend mirror
    # and the structured logs key off this exact string.
    for member in ErrorCode:
        assert member.value == member.name


def test_error_fields_for_preserves_agentcore_code_and_message():
    code, message, err_ctx = error_fields_for(
        LLMAuthError(),
        fallback_code=ErrorCode.PIPELINE_ERROR,
        fallback_message="fallback should be ignored",
    )
    assert code == ErrorCode.LLM_KEY_INVALID
    assert "无效" in message  # the curated zh message, not the fallback


def test_error_fields_for_fills_empty_coded_message_from_fallback():
    code, message, err_ctx = error_fields_for(
        AgentCoreError(""),  # coded (base INTERNAL_ERROR) but no message
        fallback_code=ErrorCode.STREAM_ERROR,
        fallback_message="服务出错了",
    )
    assert code == ErrorCode.INTERNAL_ERROR
    assert message == "服务出错了"


def test_error_fields_for_collapses_unknown_exception_to_fallback():
    code, message, err_ctx = error_fields_for(
        ValueError("raw technical boom"),
        fallback_code=ErrorCode.PIPELINE_ERROR,
        fallback_message="raw technical boom",
    )
    assert code == ErrorCode.PIPELINE_ERROR
    assert message == "raw technical boom"


def test_insufficient_balance_backend_flag_matches_frontend_policy():
    # The desktop now marks LLM_INSUFFICIENT_BALANCE non-retriable via the shared
    # catalog; assert the backend's own retryable flag agrees so the two can't drift.
    assert LLMInsufficientBalanceError().retryable is False
    assert LLMAuthError().retryable is False

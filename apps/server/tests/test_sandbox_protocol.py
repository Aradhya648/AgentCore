"""ExecutionResult output cap (05 P3-3: HEAD+TAIL, so the tail survives).

The sandbox caps stdout/stderr at ``_MAX_OUTPUT_LEN`` before ``code_execute`` hands
the text to ``ToolResult`` (which caps again, head+tail). A head-only cut here would
drop the tail — traceback last line / exit summary — before ToolResult could preserve
it, so this cap must itself keep both ends.
"""

from __future__ import annotations

from agentcore.tools.sandbox.protocol import ExecutionResult


def _result(stdout: str = "", stderr: str = "") -> ExecutionResult:
    return ExecutionResult(
        success=True, stdout=stdout, stderr=stderr, exit_code=0, duration_ms=1
    )


def test_short_output_is_not_truncated():
    r = _result(stdout="hello\n")
    assert r.truncated is False
    assert r.stdout == "hello\n"


def test_long_stdout_keeps_head_and_tail():
    cap = ExecutionResult._MAX_OUTPUT_LEN
    tail = "Traceback (most recent call last): FATAL exit 42"
    r = _result(stdout="H" * (cap * 2) + "\n" + tail)
    assert r.truncated is True
    assert len(r.stdout) <= cap
    assert r.stdout.startswith("H")  # head survives
    assert "FATAL exit 42" in r.stdout  # tail survives — the P3-3 fix


def test_long_stderr_flags_truncated_and_keeps_tail():
    cap = ExecutionResult._MAX_OUTPUT_LEN
    tail = "LAST_STDERR_LINE_MARKER"
    r = _result(stderr="E" * (cap * 2) + "\n" + tail)
    assert r.truncated is True
    assert len(r.stderr) <= cap
    assert tail in r.stderr

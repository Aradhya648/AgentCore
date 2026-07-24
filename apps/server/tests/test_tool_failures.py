"""Tool-failure aggregation + finalize / CEO injection (honest soft-landing)."""

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.loop_controller import LoopController, ToolAttempt
from agentcore.runtime.tool_failures import (
    ToolFailureFact,
    format_hard_constraint,
    format_team_tool_failures_block,
    format_tool_failures_section,
    outstanding_facts,
    sync_tool_failure_constraint_in_system,
    team_outstanding_constraint_from_messages,
)


def _fail(name: str, err: str = "boom", fp: str = "a") -> ToolAttempt:
    return ToolAttempt(
        fingerprint=fp, tool_name=name, success=False, error_summary=err
    )


def _ok(name: str, fp: str = "b") -> ToolAttempt:
    return ToolAttempt(fingerprint=fp, tool_name=name, success=True)


def test_aggregate_outstanding_until_same_tool_succeeds():
    c = LoopController()
    c.record([_fail("code_execute", "crash 1", "1")])
    c.record([_fail("code_execute", "crash 2", "2")])
    facts = c.tool_failure_facts()
    assert len(facts) == 1
    assert facts[0].tool_name == "code_execute"
    assert facts[0].failure_count == 2
    assert facts[0].last_error == "crash 2"
    assert facts[0].succeeded_after is False
    assert facts[0].outstanding is True
    assert len(c.outstanding_tool_failures()) == 1

    c.record([_ok("code_execute", "3")])
    facts2 = c.tool_failure_facts()
    assert facts2[0].failure_count == 2
    assert facts2[0].succeeded_after is True
    assert facts2[0].outstanding is False
    assert c.outstanding_tool_failures() == []


def test_aggregate_ignores_policy_failures_like_circuit_breaker():
    c = LoopController()
    c.record(
        [
            ToolAttempt(
                "a", "file_write", success=False, policy_failure=True, error_summary="denied"
            )
        ]
    )
    assert c.tool_failure_facts() == []
    assert c.tool_failure_count("file_write") == 0


def test_fail_after_success_reopens_outstanding():
    c = LoopController()
    c.record([_fail("t", "e1"), _ok("t"), _fail("t", "e2", fp="z")])
    facts = c.outstanding_tool_failures()
    assert len(facts) == 1
    assert facts[0].failure_count == 2
    assert facts[0].last_error == "e2"
    assert facts[0].succeeded_after is False


def test_format_section_and_hard_constraint():
    facts = [
        ToolFailureFact(
            tool_name="code_execute",
            failure_count=2,
            last_error="Sandbox crash",
            succeeded_after=False,
        )
    ]
    section = format_tool_failures_section(facts)
    assert "### tool_failures" in section
    assert "code_execute" in section
    assert "failures=2" in section
    assert "succeeded_after=false" in section
    assert "Sandbox crash" in section
    assert "必须如实告知" in format_hard_constraint(facts)


def test_compensated_facts_skip_hard_constraint_injection():
    messages = [LLMMessage(role="system", content="base prompt")]
    compensated = [
        ToolFailureFact(
            tool_name="code_execute",
            failure_count=2,
            last_error="old",
            succeeded_after=True,
        )
    ]
    assert outstanding_facts(compensated) == []
    assert sync_tool_failure_constraint_in_system(messages, outstanding_facts(compensated)) is False
    assert "tool_failure_hard_constraint" not in (messages[0].content or "")


def test_system_prompt_inject_and_clear():
    messages = [LLMMessage(role="system", content="base prompt")]
    outstanding = [
        ToolFailureFact(
            tool_name="code_execute",
            failure_count=1,
            last_error="crash",
            succeeded_after=False,
        )
    ]
    assert sync_tool_failure_constraint_in_system(messages, outstanding) is True
    body = messages[0].content or ""
    assert "<tool_failure_hard_constraint>" in body
    assert "code_execute" in body
    assert "禁止宣称已完成" in body

    assert sync_tool_failure_constraint_in_system(messages, []) is True
    assert "tool_failure_hard_constraint" not in (messages[0].content or "")
    assert (messages[0].content or "").startswith("base prompt")


def test_team_block_and_ceo_message_scan():
    products = [
        {
            "role": "工程师",
            "run_id": "w1",
            "tool_failures": [
                {
                    "tool_name": "code_execute",
                    "failure_count": 2,
                    "last_error": "crash",
                    "succeeded_after": False,
                }
            ],
        }
    ]
    block = format_team_tool_failures_block(products)
    assert "### tool_failures" in block
    assert "code_execute" in block
    assert "【工具失败硬约束】" in block
    assert "succeeded_after=false" in block

    messages = [
        LLMMessage(role="system", content="ceo"),
        LLMMessage(role="tool", content=block),
    ]
    text = team_outstanding_constraint_from_messages(messages)
    assert text is not None
    assert "禁止宣称已完成" in text
    assert sync_tool_failure_constraint_in_system(
        messages, [], constraint_text=text
    )
    assert "tool_failure_hard_constraint" in (messages[0].content or "")


def test_team_block_omitted_when_only_compensated():
    products = [
        {
            "role": "工程师",
            "run_id": "w1",
            "tool_failures": [
                {
                    "tool_name": "code_execute",
                    "failure_count": 1,
                    "last_error": "tmp",
                    "succeeded_after": True,
                }
            ],
        }
    ]
    block = format_team_tool_failures_block(products)
    assert "### tool_failures" in block
    assert "succeeded_after=true" in block
    assert "【工具失败硬约束】" not in block
    assert team_outstanding_constraint_from_messages(
        [LLMMessage(role="tool", content=block)]
    ) is None

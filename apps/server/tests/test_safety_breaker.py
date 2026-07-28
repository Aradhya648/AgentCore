"""Unit tests for the P3 safety circuit breaker (heuristic last line).

Honest positioning: these assert the blacklist heuristics we chose to ship —
they do not prove every dangerous command is intercepted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agentcore.core.types import AutonomyPolicy, recipe_to_axes, ToolApproval, ToolCategory
from agentcore.llm.provider.protocol import ToolCall, ToolCallFunction
from agentcore.runtime.approvals import ApprovalDecision, ApprovalGate
from agentcore.runtime.engine import tool_exec as tool_exec_mod
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.runtime.safety_breaker import (
    BreakerVerdict,
    evaluate_tool_call,
    git_forbidden_subcommands,
    is_sensitive_path,
    scan_destructive_text,
)
from agentcore.runtime.sandbox_approval import execution_tool_auto_passes
from agentcore.tools.builtin.git_ops import _FORBIDDEN_PATTERNS
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

pytestmark = pytest.mark.anyio


# ── Pure rule module ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "rm -rf /",
        "sudo rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        "rm -rf ${HOME}/",
        "rm -fr /",
        "rm --force --recursive /",
    ],
)
def test_scan_destructive_rm_root_hits(text: str):
    hit = scan_destructive_text(text)
    assert hit is not None
    assert hit.verdict is BreakerVerdict.FORCE_APPROVAL
    assert hit.rule_id == "destructive.rm_root"
    assert "并非完整拦截" in hit.reason


def test_scan_destructive_rm_workspace_paths_pass():
    assert scan_destructive_text("rm -rf /tmp/build") is None
    assert scan_destructive_text("rm -rf ./dist") is None
    assert scan_destructive_text("rm -rf node_modules") is None
    assert scan_destructive_text("rm file.txt") is None


@pytest.mark.parametrize(
    "text,rule_id",
    [
        ("mkfs.ext4 /dev/sda1", "destructive.format_device"),
        ("dd if=/dev/zero of=/dev/sda bs=1M", "destructive.format_device"),
        ("format C:", "destructive.format_device"),
        ("git push --force origin main", "destructive.git_force_push_protected"),
        ("git push -f origin master", "destructive.git_force_push_protected"),
        ("git push origin main --force-with-lease", "destructive.git_force_push_protected"),
        ("shutdown -h now", "destructive.shutdown"),
        ("Restart-Computer", "destructive.shutdown"),
    ],
)
def test_scan_destructive_other_rules(text: str, rule_id: str):
    hit = scan_destructive_text(text)
    assert hit is not None
    assert hit.rule_id == rule_id
    assert hit.verdict is BreakerVerdict.FORCE_APPROVAL


def test_scan_git_push_feature_branch_ok():
    assert scan_destructive_text("git push origin feature/foo") is None
    assert scan_destructive_text("git push --force origin feature/foo") is None


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "config/.env",
        "apps/server/.env",
        "id_rsa",
        ".ssh/id_ed25519",
        "certs/server.pem",
        "secrets/app.key",
        "credentials.json",
        ".aws/credentials",
        ".npmrc",
    ],
)
def test_sensitive_paths(path: str):
    assert is_sensitive_path(path) is True


def test_sensitive_globs():
    assert is_sensitive_path(".env*") is True
    assert is_sensitive_path("*.pem") is True
    assert is_sensitive_path("config/.env.*") is True


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "src/main.py",
        ".gitignore",
        "env.example",
        "packages/contract-types/src/events.generated.ts",
        ".",
        "",
    ],
)
def test_non_sensitive_paths(path: str):
    assert is_sensitive_path(path) is False


def test_evaluate_file_read_sensitive_denies():
    hit = evaluate_tool_call("file_read", {"path": ".env.local"})
    assert hit is not None
    assert hit.verdict is BreakerVerdict.DENY
    assert hit.rule_id == "sensitive.path_read"


def test_evaluate_file_read_normal_passes():
    assert evaluate_tool_call("file_read", {"path": "src/app.py"}) is None


def test_evaluate_terminal_start_destructive_forces():
    hit = evaluate_tool_call(
        "terminal", {"subcommand": "start", "command": "rm -rf /"}
    )
    assert hit is not None
    assert hit.verdict is BreakerVerdict.FORCE_APPROVAL


def test_evaluate_terminal_read_skips():
    assert (
        evaluate_tool_call(
            "terminal", {"subcommand": "read", "command": "rm -rf /"}
        )
        is None
    )


def test_evaluate_code_execute_destructive_forces():
    hit = evaluate_tool_call(
        "code_execute",
        {"language": "bash", "code": "rm -rf /\n"},
    )
    assert hit is not None
    assert hit.verdict is BreakerVerdict.FORCE_APPROVAL


def test_evaluate_code_execute_benign_passes():
    assert (
        evaluate_tool_call(
            "code_execute",
            {"language": "python", "code": "print(1+1)\n"},
        )
        is None
    )


def test_git_forbidden_list_shared_with_git_ops():
    assert git_forbidden_subcommands() == _FORBIDDEN_PATTERNS
    assert "push" in git_forbidden_subcommands()


def test_evaluate_git_forbidden_denies():
    hit = evaluate_tool_call("git", {"subcommand": "push"})
    assert hit is not None
    assert hit.verdict is BreakerVerdict.DENY
    assert hit.rule_id == "git.forbidden_subcommand"


# ── Gate + full_trust: force still prompts ───────────────────────────────────


def _drain(sink: EventSink):
    events = []
    while not sink._queue.empty():  # noqa: SLF001
        events.append(sink._queue.get_nowait())
    return events


async def _resolve_when_ready(
    registry: InteractionRegistry,
    approval_id: str,
    decision: ApprovalDecision,
    conversation_id: str,
) -> None:
    for _ in range(2000):
        if registry.resolve(approval_id, decision, conversation_id=conversation_id):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"approval {approval_id!r} never became pending")


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c",
    )


async def test_force_authorize_ignores_turn_grant_and_delegation():
    """Circuit-breaker force=True must not honor kickoff / turn grants."""
    sink = EventSink()
    registry = InteractionRegistry()
    gate = ApprovalGate(
        sink=sink,
        conversation_id="conv-cb",
        registry=registry,
        timeout_seconds=5.0,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
        delegation_grantable_tools=frozenset({"code_execute", "terminal"}),
    )
    gate.grant_delegation("exec-1")
    gate._granted.add("code_execute")  # noqa: SLF001 — simulate 本轮放行

    task = asyncio.create_task(
        gate.authorize(
            tool_name="code_execute",
            tool_call_id="tc-force-1",
            arguments={"code": "rm -rf /", "circuit_breaker_hint": "hint"},
            execution_id="exec-1",
            force=True,
        )
    )
    await _resolve_when_ready(
        registry, "tc-force-1", ApprovalDecision.APPROVE, "conv-cb"
    )
    assert await task is ApprovalDecision.APPROVE
    types = [e.type for e in _drain(sink)]
    assert EventType.APPROVAL_REQUIRED in types


async def test_force_authorize_refuses_approve_always_grant():
    sink = EventSink()
    registry = InteractionRegistry()
    gate = ApprovalGate(
        sink=sink,
        conversation_id="conv-cb2",
        registry=registry,
        timeout_seconds=5.0,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
    )
    task = asyncio.create_task(
        gate.authorize(
            tool_name="code_execute",
            tool_call_id="tc-force-2",
            arguments={"code": "rm -rf /"},
            force=True,
        )
    )
    await _resolve_when_ready(
        registry, "tc-force-2", ApprovalDecision.APPROVE_ALWAYS, "conv-cb2"
    )
    decision = await task
    assert decision is ApprovalDecision.APPROVE  # downgraded
    assert "code_execute" not in gate._granted  # noqa: SLF001


async def test_full_trust_auto_pass_bypassed_for_destructive_via_tool_exec():
    """Even when sandbox_approval would auto-pass under FULL_AUTO, destructive
    shapes still suspend on the gate."""
    sink = EventSink()
    registry = InteractionRegistry()
    gate = ApprovalGate(
        sink=sink,
        conversation_id="conv-ft",
        registry=registry,
        timeout_seconds=5.0,
        permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED),
        delegation_grantable_tools=frozenset({"code_execute"}),
    )

    class _Local:
        location = "local"

    class _ExecTool:
        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="code_execute",
                description="t",
                parameters={"type": "object", "properties": {}},
                category=ToolCategory.EXECUTION,
                approval=ToolApproval.GRANTABLE,
            )

        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            return ToolResult(tool_call_id="", success=True, output="ran")

    registry_tools = ToolRegistry()
    registry_tools.register(_ExecTool())
    ctx = ToolContext(
        execution_id="exec-ft",
        run_id="run-ft",
        agent_id="a",
        backend=_Local(),  # type: ignore[arg-type]
        user_id="u",
        conversation_id="conv-ft",
    )

    assert (
        execution_tool_auto_passes(
            _Local(), "code_execute", permission_axes=recipe_to_axes(AutonomyPolicy.MANAGED)
        )
        is True
    )

    tc = ToolCall(
        id="tc-ft-1",
        function=ToolCallFunction(
            name="code_execute", arguments='{"code": "rm -rf /"}'
        ),
    )

    async def _approve() -> None:
        await _resolve_when_ready(
            registry, "tc-ft-1", ApprovalDecision.APPROVE, "conv-ft"
        )

    approve_task = asyncio.create_task(_approve())
    messages, terminal, attempts = await tool_exec_mod.execute_tools(
        [tc],
        registry_tools,
        ctx,
        sink,
        approval_gate=gate,
        run_id="run-ft",
    )
    await approve_task
    assert terminal is None
    assert attempts[0].success is True
    assert messages[0].content == "ran"
    required = [e for e in _drain(sink) if e.type is EventType.APPROVAL_REQUIRED]
    assert len(required) == 1
    assert "circuit_breaker_hint" in required[0].payload["arguments"]


async def test_sensitive_file_read_denied_as_policy_failure():
    sink = EventSink()

    class _ReadTool:
        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="file_read",
                description="t",
                parameters={"type": "object", "properties": {}},
                category=ToolCategory.FILESYSTEM,
                approval=ToolApproval.NEVER,
            )

        async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
            raise AssertionError("must not execute sensitive read")

    tools = ToolRegistry()
    tools.register(_ReadTool())
    ctx = _ctx()
    tc = ToolCall(
        id="tc-read-1",
        function=ToolCallFunction(name="file_read", arguments='{"path": ".env"}'),
    )
    messages, _, attempts = await tool_exec_mod.execute_tools(
        [tc], tools, ctx, sink, approval_gate=None, run_id="run-r"
    )
    assert attempts[0].success is False
    assert attempts[0].policy_failure is True
    assert "敏感" in messages[0].content or "凭据" in messages[0].content

"""Sandbox subsystem for isolated code execution."""

from __future__ import annotations

from agentcore.tools.sandbox.gvisor import GVisorSandbox
from agentcore.tools.sandbox.protocol import (
    ExecutionRequest,
    ExecutionResult,
    SandboxCapabilities,
    SandboxProvider,
)
from agentcore.tools.sandbox.subprocess import SubprocessSandbox


def create_sandbox(
    *,
    workspace_root: str | None = None,
    location: str,
    gvisor_enabled: bool = False,
    runsc_path: str = "runsc",
    runtime_root: str | None = None,
) -> SandboxProvider:
    """Pick a sandbox backend for the given deployment location."""
    if location == "server" and gvisor_enabled:
        return GVisorSandbox(
            runsc_path=runsc_path,
            workspace_root=workspace_root,
            runtime_root=runtime_root,
        )
    return SubprocessSandbox()


__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "GVisorSandbox",
    "SandboxCapabilities",
    "SandboxProvider",
    "SubprocessSandbox",
    "create_sandbox",
]

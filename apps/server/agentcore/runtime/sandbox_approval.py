"""Sandbox → approval policy table (安全权限与治理 §三 / §五).

Maps the workspace execution environment to whether GRANTABLE *execution-class*
tools still need a human approval prompt. File-mutation tools keep their own
gate posture (local: gated; cloud workers historically ungated via no gate —
or via tool_exec narrowing when the gate is shared only for MCP/Host).

Desktop Client Tools (MCP stdio / Host face) touch the user's machine even when
the workspace is cloud — they still share the turn ApprovalGate.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from agentcore.config import settings
from agentcore.core.types import PermissionAxes

if TYPE_CHECKING:
    from agentcore.workspace.protocol import WorkspaceBackend


class ExecutionApprovalPosture(StrEnum):
    """Whether execution-class tools need approval (sandbox → posture table)."""

    REQUIRES_AUTH = "requires_auth"  # local subprocess — user must authorize
    AUTO_PASS = "auto_pass"  # cloud gVisor true isolation — auto-approve
    UNAVAILABLE = "unavailable"  # cloud without sandbox — tools not registered


def execution_approval_posture(backend: WorkspaceBackend | None) -> ExecutionApprovalPosture:
    """Resolve the sandbox → execution-approval cell for this workspace."""
    if backend is None:
        return ExecutionApprovalPosture.REQUIRES_AUTH
    if backend.location == "local":
        return ExecutionApprovalPosture.REQUIRES_AUTH
    # Cloud (location=server): no real sandbox → tools withheld at registry;
    # gVisor on → true isolation, execution auto-passes.
    # Dev escape hatch (CODE_EXECUTE_CLOUD_ENABLED, 安全权限与治理 §5.4): tools ARE
    # registered despite UNAVAILABLE here — the posture only feeds auto-pass, and cloud
    # workers carry no per-call gate anyway (worker_gate_applies is False), so the
    # escape hatch executes ungated without touching this table.
    if settings.gvisor_enabled:
        return ExecutionApprovalPosture.AUTO_PASS
    return ExecutionApprovalPosture.UNAVAILABLE


def worker_gate_applies(backend: WorkspaceBackend | None) -> bool:
    """Whether delegated workers share the turn ApprovalGate for *all* GRANTABLE tools.

    Local subprocess: yes (real machine). Cloud: no for server-sandbox tools —
    either tools are withheld (no sandbox) or gVisor isolates execution (AUTO_PASS);
    file ops run in the per-user cloud workspace without a per-call gate.

    Desktop-touch tools (MCP / Host) still need the gate on cloud+desktop — see
    :func:`is_desktop_touch_tool`. CEO / captain always gate GRANTABLE regardless
    of backend location (tool_exec only narrows when ``role=="worker"``).
    """
    return backend is not None and backend.location == "local"


def is_desktop_touch_tool(tool_name: str) -> bool:
    """True when the tool side-effects the user's machine via desktop Client Tools.

    MCP dynamic tools are named ``mcp_<server>_<tool>``. Host face tools are the
    closed ``host_class`` roster.
    """
    name = (tool_name or "").strip()
    if name.startswith("mcp_"):
        return True
    from agentcore.tools.registration import host_class_tool_names

    return name in host_class_tool_names()


def execution_tool_auto_passes(
    backend: WorkspaceBackend | None,
    tool_name: str,
    *,
    permission_axes: PermissionAxes | None = None,
) -> bool:
    """True when the tool should skip the approval prompt via sandbox / command=auto.

    Covers the whole ``execution_class`` roster (``code_execute`` / ``test_run`` /
    ``terminal`` / ``browser_*``) plus low-risk ``desktop_notify`` under
    ``command=auto``. Host / MCP never enter here.

    Cloud gVisor → auto-pass execution_class (sandbox isolation).
    ``command=auto`` → auto-pass execution_class + ``desktop_notify`` even on local.
    FORCE / circuit-breaker still bypass this in ``tool_exec`` (``force_breaker``).
    """
    from agentcore.tools.builtin.desktop_notify import DESKTOP_NOTIFY_TOOL_NAME
    from agentcore.tools.registration import execution_class_tool_names

    name = (tool_name or "").strip()
    is_execution = name in execution_class_tool_names()
    is_desktop_notify = name == DESKTOP_NOTIFY_TOOL_NAME
    if not is_execution and not is_desktop_notify:
        return False
    if permission_axes is not None and permission_axes.auto_executes:
        return True
    # gVisor AUTO_PASS is execution_class only (desktop_notify is a local client tool).
    if is_execution:
        return execution_approval_posture(backend) is ExecutionApprovalPosture.AUTO_PASS
    return False

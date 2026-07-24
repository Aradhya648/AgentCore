"""Session permission_preset behaviour (会话级权限模式 P1)."""

from __future__ import annotations

from agentcore.core.types import (
    AutonomyPolicy,
    PermissionPreset,
    autonomy_to_preset,
    preset_to_autonomy,
)
from agentcore.runtime.kickoff.gate import needs_capability_auth, should_kickoff
from agentcore.runtime.sandbox_approval import execution_tool_auto_passes
from agentcore.tools.builtin import build_worker_registry


class _LocalBackend:
    location = "local"


def test_autonomy_preset_roundtrip_mapping():
    assert autonomy_to_preset(AutonomyPolicy.ALWAYS_ASK) is PermissionPreset.OBSERVE
    assert autonomy_to_preset(AutonomyPolicy.FIRST_GRANT) is PermissionPreset.WORKSPACE
    assert autonomy_to_preset(AutonomyPolicy.FULL_AUTO) is PermissionPreset.FULL_TRUST
    assert preset_to_autonomy(PermissionPreset.OBSERVE) is AutonomyPolicy.ALWAYS_ASK
    assert preset_to_autonomy(PermissionPreset.WORKSPACE) is AutonomyPolicy.FIRST_GRANT
    assert preset_to_autonomy(PermissionPreset.FULL_TRUST) is AutonomyPolicy.FULL_AUTO


def test_observe_withholds_execution_tools():
    """observe: code_execute / test_run / terminal are not registered."""
    names = {s.name for s in build_worker_registry(backend=_LocalBackend()).list_all()}
    assert "code_execute" in names
    assert "test_run" in names
    assert "terminal" in names

    observe_names = {
        s.name
        for s in build_worker_registry(
            backend=_LocalBackend(), permission_preset=PermissionPreset.OBSERVE
        ).list_all()
    }
    assert "code_execute" not in observe_names
    assert "test_run" not in observe_names
    assert "terminal" not in observe_names
    # Read-only retrieval stays on.
    assert "web_search" in observe_names
    assert "file_read" in observe_names
    assert "file_write" in observe_names  # still registered; gated per-call


def test_workspace_keeps_kickoff_capability_auth():
    """workspace ≈ first_grant: local gate shows capability half on kickoff."""
    autonomy = preset_to_autonomy(PermissionPreset.WORKSPACE)
    assert needs_capability_auth(local_gate=True, autonomy=autonomy) is True
    assert should_kickoff(plan_preview=False, local_gate=True, autonomy=autonomy) is True


def test_full_trust_skips_kickoff_and_local_exec_auto_pass():
    """full_trust ≈ full_auto: no kickoff; local execution tools auto-pass."""
    autonomy = preset_to_autonomy(PermissionPreset.FULL_TRUST)
    assert should_kickoff(plan_preview=True, local_gate=True, autonomy=autonomy) is False
    assert (
        execution_tool_auto_passes(
            _LocalBackend(), "code_execute", autonomy_policy=autonomy
        )
        is True
    )
    assert (
        execution_tool_auto_passes(
            _LocalBackend(), "test_run", autonomy_policy=autonomy
        )
        is True
    )
    # Non-full-trust local still requires auth.
    assert (
        execution_tool_auto_passes(
            _LocalBackend(),
            "code_execute",
            autonomy_policy=AutonomyPolicy.FIRST_GRANT,
        )
        is False
    )

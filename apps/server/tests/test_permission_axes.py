"""Three-axis permission model (会话级权限 · file_write / command / team_kickoff)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentcore.api.schemas.conversations import PermissionAxesModel, PermissionAxesUpdate
from agentcore.core.types import (
    AutonomyPolicy,
    CommandAxis,
    DEFAULT_PERMISSION_AXES,
    FileWriteAxis,
    PermissionAxes,
    TeamKickoffAxis,
    recipe_to_axes,
    validate_permission_axes,
)
from agentcore.runtime.kickoff.gate import needs_capability_auth, should_kickoff
from agentcore.runtime.sandbox_approval import execution_tool_auto_passes
from agentcore.tools.builtin import build_worker_registry


class _LocalBackend:
    location = "local"


def test_default_axes_are_write_code():
    assert DEFAULT_PERMISSION_AXES == PermissionAxes(
        FileWriteAxis.SESSION, CommandAxis.KICKOFF, TeamKickoffAxis.RULES
    )
    assert recipe_to_axes(AutonomyPolicy.WRITE_CODE) == DEFAULT_PERMISSION_AXES


def test_builtin_recipes():
    assert recipe_to_axes(AutonomyPolicy.CAUTIOUS) == PermissionAxes(
        FileWriteAxis.ASK, CommandAxis.ASK, TeamKickoffAxis.RULES
    )
    assert recipe_to_axes(AutonomyPolicy.LESS_INTERRUPT) == PermissionAxes(
        FileWriteAxis.SESSION, CommandAxis.KICKOFF, TeamKickoffAxis.SKIP
    )
    assert recipe_to_axes(AutonomyPolicy.MANAGED) == PermissionAxes(
        FileWriteAxis.SESSION, CommandAxis.AUTO, TeamKickoffAxis.SKIP
    )


def test_illegal_command_auto_with_file_write_ask():
    with pytest.raises(ValueError, match="illegal"):
        PermissionAxes(
            file_write=FileWriteAxis.ASK,
            command=CommandAxis.AUTO,
            team_kickoff=TeamKickoffAxis.SKIP,
        )
    with pytest.raises(ValueError, match="illegal"):
        validate_permission_axes(
            file_write="ask", command="auto", team_kickoff="skip"
        )
    with pytest.raises(ValidationError):
        PermissionAxesModel(file_write="ask", command="auto", team_kickoff="rules")
    with pytest.raises(ValidationError):
        PermissionAxesUpdate(
            permission_axes={"file_write": "ask", "command": "auto", "team_kickoff": "skip"}
        )


def test_command_ask_withholds_execution_tools():
    axes = recipe_to_axes(AutonomyPolicy.CAUTIOUS)
    names = {
        s.name
        for s in build_worker_registry(
            backend=_LocalBackend(), permission_axes=axes
        ).list_all()
    }
    assert "code_execute" not in names
    assert "test_run" not in names
    assert "terminal" not in names
    assert "file_write" in names
    assert "web_search" in names


def test_write_code_keeps_kickoff_capability_auth():
    axes = DEFAULT_PERMISSION_AXES
    assert needs_capability_auth(local_gate=True, axes=axes) is True
    assert should_kickoff(plan_preview=False, local_gate=True, axes=axes) is True
    assert should_kickoff(plan_preview=True, local_gate=False, axes=axes) is True


def test_team_kickoff_skip_releases_card():
    axes = recipe_to_axes(AutonomyPolicy.LESS_INTERRUPT)
    assert should_kickoff(plan_preview=True, local_gate=True, axes=axes) is False
    # command still kickoff — capability auth would apply if card were shown
    assert needs_capability_auth(local_gate=True, axes=axes) is True


def test_team_kickoff_always_forces_plan_half():
    axes = PermissionAxes(
        FileWriteAxis.SESSION, CommandAxis.KICKOFF, TeamKickoffAxis.ALWAYS
    )
    assert should_kickoff(plan_preview=False, local_gate=False, axes=axes) is True


def test_command_auto_skips_kickoff_and_local_exec_auto_pass():
    axes = recipe_to_axes(AutonomyPolicy.MANAGED)
    assert should_kickoff(plan_preview=True, local_gate=True, axes=axes) is False
    assert (
        execution_tool_auto_passes(
            _LocalBackend(), "code_execute", permission_axes=axes
        )
        is True
    )
    assert (
        execution_tool_auto_passes(
            _LocalBackend(),
            "code_execute",
            permission_axes=DEFAULT_PERMISSION_AXES,
        )
        is False
    )


def test_less_interrupt_skips_card_but_keeps_kickoff_grant_semantics():
    """少打断: team_kickoff=skip releases card; command=kickoff still wants grant."""
    axes = recipe_to_axes(AutonomyPolicy.LESS_INTERRUPT)
    assert should_kickoff(plan_preview=True, local_gate=True, axes=axes) is False
    assert needs_capability_auth(local_gate=True, axes=axes) is True
    assert axes.honors_kickoff_grant is True
    assert axes.auto_executes is False


def test_command_ask_no_capability_auth():
    axes = recipe_to_axes(AutonomyPolicy.CAUTIOUS)
    assert needs_capability_auth(local_gate=True, axes=axes) is False
    # rules + plan_preview still hangs team card (组团按 rules)
    assert should_kickoff(plan_preview=True, local_gate=True, axes=axes) is True

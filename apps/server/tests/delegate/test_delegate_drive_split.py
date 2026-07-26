"""Smoke tests for drive.py phase split (behavior-preserving refactor)."""

from __future__ import annotations

import importlib
import inspect

import pytest

from agentcore.runtime.delegate.drive_preview import team_preview_before_workers
from agentcore.runtime.delegate.drive_redirect import RedirectController
from agentcore.runtime.delegate.drive_terminal import post_session_all_completed
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.redirect_queue import RunRedirectRequest
from agentcore.runtime.runs.types import RunSpec


def _drive_mod():
    # Package ``__init__`` re-exports ``drive`` the function, shadowing the submodule
    # name on ``agentcore.runtime.delegate`` — load by absolute module path.
    return importlib.import_module("agentcore.runtime.delegate.drive")


def test_drive_public_exports_stable():
    drive_mod = _drive_mod()
    assert callable(drive_mod.drive)
    assert callable(drive_mod.drive_coordinated)
    # Private helpers remain importable from drive (existing tests rely on this).
    assert drive_mod._team_preview_before_workers is team_preview_before_workers
    assert drive_mod._post_session_all_completed is post_session_all_completed


def test_drive_signature_unchanged():
    sig = inspect.signature(_drive_mod().drive)
    params = list(sig.parameters)
    assert params[:2] == ["tool", "plan"]
    assert {
        "execution_id",
        "seed_completed",
        "finalize",
        "seed_notes",
        "complexity_hint",
        "coordination",
        "call_idx",
        "completion_criteria",
        "coordinate",
        "session",
    }.issubset(sig.parameters)


def test_cold_fallback_mints_unique_redir_ids():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="w1", agent_id="w1", role="researcher", task="find facts"),
        ]
    )
    ctrl = RedirectController(
        tool=object(),
        plan=plan,
        execution_id="exec-1",
        worker_gate=None,
        session=None,
        total=1,
    )
    redir = RunRedirectRequest(
        execution_id="exec-1",
        run_id="w1",
        feedback="try another angle",
        conversation_id="c1",
    )
    first = ctrl.cold_fallback(plan.by_id("w1"), redir)
    assert first == "w1_redir"
    assert plan.by_id(first) is not None
    assert plan.by_id(first).replaces_run_id == "w1"
    assert plan.by_id(first).steer == "try another angle"
    second = ctrl.cold_fallback(plan.by_id("w1"), redir)
    assert second == "w1_redir2"


@pytest.mark.asyncio
async def test_team_preview_skips_when_seeded():
    class _Tool:
        _depth = 0

    plan = RunPlan(nodes=[RunSpec(run_id="a", agent_id="a", role="r", task="t")])
    result = await team_preview_before_workers(
        _Tool(),
        plan,
        finalize=False,
        complexity_hint="standard",
        seed_completed={"a": object()},  # type: ignore[dict-item]
        call_idx=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_team_preview_skips_light_handwritten():
    """普通 light 手写任务仍跳过开工卡（早返回，不进 kickoff）。"""
    class _Tool:
        _depth = 0
        _active_playbook = None

    plan = RunPlan(nodes=[RunSpec(run_id="a", agent_id="a", role="r", task="t")])
    result = await team_preview_before_workers(
        _Tool(),
        plan,
        finalize=False,
        complexity_hint="light",
        seed_completed=None,
        call_idx=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_team_preview_light_organize_folder_does_not_skip(monkeypatch):
    """organize_folder 即使 light 也要进 team_preview（kickoff grant → GRANTABLE）。"""
    from agentcore.core.types import AutonomyPolicy
    from agentcore.runtime.checkpoints import CheckpointDecision
    from agentcore.runtime.delegate import preview as preview_mod

    await_calls = {"n": 0}

    async def _fake_await(*_a, **_k):
        await_calls["n"] += 1
        return CheckpointDecision.CONTINUE

    monkeypatch.setattr(preview_mod, "await_team_preview", _fake_await)
    monkeypatch.setattr(preview_mod, "should_kickoff", lambda *a, **k: True)
    monkeypatch.setattr(preview_mod, "should_preview_plan", lambda *a, **k: True)
    monkeypatch.setattr(preview_mod, "skip_after_confirmed_ask", lambda *_a, **_k: False)
    monkeypatch.setattr(preview_mod, "needs_capability_auth", lambda *a, **k: False)
    monkeypatch.setattr(
        "agentcore.runtime.sandbox_approval.worker_gate_applies", lambda *_a, **_k: False
    )

    class _Tool:
        _depth = 0
        _autonomy_policy = AutonomyPolicy.FIRST_GRANT
        _active_playbook = "organize_folder"
        _pending_pause = False
        _base_tool_context = type("C", (), {"backend": None})()
        _approval_gate = None

    plan = RunPlan(nodes=[RunSpec(run_id="a", agent_id="a", role="r", task="t")])
    result = await team_preview_before_workers(
        _Tool(),
        plan,
        finalize=True,
        complexity_hint="light",
        seed_completed=None,
        call_idx=0,
    )
    assert result is None
    assert await_calls["n"] == 1

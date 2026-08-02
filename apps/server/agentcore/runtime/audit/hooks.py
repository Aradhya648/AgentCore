"""Narrow runtime hooks wiring audit projection into engine / runs / approvals."""

from __future__ import annotations

from typing import Any

from agentcore.runtime.audit.projector import (
    project_approval_resolved,
    project_approval_swept,
    project_approval_timeout,
    project_circuit_breaker,
    project_delegate_plan,
    project_journal_entry,
    project_permission_effective,
    project_replan,
    project_run_deterministic_failure,
    project_run_redirect_ignored,
    project_run_retry,
    project_tool_disabled,
    project_write_conflict,
)
from agentcore.runtime.audit.recorder import AuditRecorder, current_audit_recorder


def on_journal_fact_appended(entry: dict[str, Any]) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    draft = project_journal_entry(recorder, entry)
    if draft is not None:
        recorder.schedule(draft)


def on_delegate_plan(*, execution_id: str, plan, captain_run_id: str | None) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None:
        return
    recorder.activate_delegation()
    recorder.schedule(
        project_delegate_plan(
            recorder,
            execution_id=execution_id,
            plan=plan,
            captain_run_id=captain_run_id,
        )
    )


def on_replan(
    *,
    execution_id: str,
    binds: list[Any],
    steers: list[Any],
    adds: int,
    stop: bool,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None:
        return
    recorder.activate_delegation()
    recorder.schedule(
        project_replan(
            recorder,
            execution_id=execution_id,
            binds=binds,
            steers=steers,
            adds=adds,
            stop=stop,
        )
    )


def on_permission_effective(
    *,
    execution_id: str | None,
    run_id: str,
    parent_run_id: str | None,
    declared_tools: list[str] | None,
    effective_tools: list[str] | None,
    depth: int,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_permission_effective(
            recorder,
            execution_id=execution_id,
            run_id=run_id,
            parent_run_id=parent_run_id,
            declared_tools=declared_tools,
            effective_tools=effective_tools,
            depth=depth,
        )
    )


def on_circuit_breaker(
    *,
    tool_name: str,
    tool_call_id: str,
    rule_id: str,
    verdict: str,
    reason: str,
    run_id: str | None = None,
) -> None:
    """Force-schedule safety-breaker hits (incl. solo / full_trust turns)."""
    recorder = current_audit_recorder.get()
    if recorder is None:
        return
    recorder.schedule(
        project_circuit_breaker(
            recorder,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            rule_id=rule_id,
            verdict=verdict,
            reason=reason,
            run_id=run_id,
        ),
        force=True,
    )


def on_approval_resolved(
    *,
    tool_name: str,
    tool_call_id: str,
    decision: str,
    arguments: dict[str, Any],
    run_id: str | None = None,
) -> None:
    """Always force-schedule — approvals must persist even on non-delegated turns."""
    recorder = current_audit_recorder.get()
    if recorder is None:
        return
    recorder.schedule(
        project_approval_resolved(
            recorder,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            decision=decision,
            arguments=arguments,
            run_id=run_id,
        ),
        force=True,
    )


def on_approval_timeout(
    *,
    tool_name: str,
    tool_call_id: str,
    run_id: str | None = None,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None:
        return
    recorder.schedule(
        project_approval_timeout(
            recorder,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            run_id=run_id,
        ),
        force=True,
    )


def on_tool_disabled(*, tool_name: str, run_id: str, failure_count: int) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_tool_disabled(
            recorder,
            tool_name=tool_name,
            run_id=run_id,
            failure_count=failure_count,
        )
    )


def on_write_conflict(*, path: str, run_id: str, owner_run_id: str) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_write_conflict(
            recorder,
            path=path,
            run_id=run_id,
            owner_run_id=owner_run_id,
        )
    )


def on_approval_swept(*, tool_names: list[str], swept: list[dict[str, str]]) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    if not swept:
        return
    recorder.schedule(
        project_approval_swept(
            recorder,
            tool_names=tool_names,
            swept=swept,
        ),
        force=True,
    )


def on_run_retry(
    *,
    run_id: str,
    attempt: int,
    source: str,
    error: str | None = None,
    execution_id: str | None = None,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_run_retry(
            recorder,
            run_id=run_id,
            attempt=attempt,
            source=source,
            error=error,
            execution_id=execution_id,
        )
    )


def on_run_deterministic_failure(
    *,
    run_id: str,
    error: str | None = None,
    execution_id: str | None = None,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_run_deterministic_failure(
            recorder,
            run_id=run_id,
            error=error,
            execution_id=execution_id,
        )
    )


def on_run_redirect_ignored(
    *,
    run_id: str,
    feedback: str | None = None,
    execution_id: str | None = None,
) -> None:
    recorder = current_audit_recorder.get()
    if recorder is None or not recorder.active:
        return
    recorder.schedule(
        project_run_redirect_ignored(
            recorder,
            run_id=run_id,
            feedback=feedback,
            execution_id=execution_id,
        )
    )


def bind_recorder(
    *,
    user_id: str,
    conversation_id: str,
    turn_id: str,
    trace_id: str | None,
    captain_run_id: str | None = None,
    delegated: bool = False,
    permission_axes: str | None = None,
) -> tuple[AuditRecorder, Any]:
    recorder = AuditRecorder(
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        trace_id=trace_id,
        captain_run_id=captain_run_id,
        delegated=delegated,
        permission_axes=permission_axes,
    )
    if delegated:
        recorder.activate()
    token = current_audit_recorder.set(recorder)
    return recorder, token

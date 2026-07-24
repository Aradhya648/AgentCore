"""Shared projections, helpers and constants for the admin console routes.

Split out of the former single ``admin.py`` so each surface (overview / users /
usage / system / audit / conversations / observability) lives in its own module
while reusing one definition of the cross-surface projections (so e.g. the
overview dashboard and the observability page can never disagree on how a turn's
health rollup maps to the wire).
"""

from __future__ import annotations

from agentcore.api.schemas import (
    AdminUserListItem,
    AdminUserResponse,
    ReplaySpan,
    TurnHealthWindow,
)
from agentcore.db.models import User

# 全站看板 windows: the 7-day trend length (matches /v1/usage/summary), shared by
# every surface that renders a「近 7 日」series so they span identical UTC days.
_TREND_DAYS = 7
# 复盘 span preview cap: a tool call's args/result are truncated to a triage-sized
# snippet (the full text lives in turn_journal / the client replay, not this ops view).
_SPAN_PREVIEW = 200


def _preview(text: str | None) -> str | None:
    """Truncate a tool arg/result to a triage-sized snippet (``None`` stays ``None``)."""
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= _SPAN_PREVIEW else text[:_SPAN_PREVIEW] + "…"


def _project_spans(entries: list[dict]) -> list[ReplaySpan]:
    """Project a turn's journal entries to the compact tool/LLM span list (会话复盘).

    Reads only the execution facts that triage a turn — ``llm_call`` (round /
    finish_reason / tokens) and ``tool_call`` (name / ok? / arg·result preview) — in
    emission (``seq``) order, skipping the heavy/display kinds (system prompt, team
    graph, full results). The full fidelity stays in turn_journal for client replay;
    this is the operator's at-a-glance "what did the turn actually do".
    """
    spans: list[ReplaySpan] = []
    for entry in entries:
        kind = entry.get("kind")
        payload = entry.get("payload") or {}
        if kind == "llm_call":
            usage = payload.get("usage") or {}
            spans.append(
                ReplaySpan(
                    kind="llm",
                    run_id=payload.get("run_id"),
                    round_idx=payload.get("round_idx"),
                    finish_reason=payload.get("finish_reason"),
                    input_tokens=int(usage.get("input", 0) or 0),
                    output_tokens=int(usage.get("output", 0) or 0),
                )
            )
        elif kind == "tool_call":
            spans.append(
                ReplaySpan(
                    kind="tool",
                    run_id=payload.get("run_id"),
                    name=payload.get("name"),
                    success=bool(payload.get("success", True)),
                    args_preview=_preview(payload.get("arguments")),
                    result_preview=_preview(payload.get("result")),
                )
            )
    return spans


def _health_window(agg: dict) -> TurnHealthWindow:
    """Map a turn_metrics health rollup → the wire schema, deriving the rates.

    The repository returns raw counts (turns / errors / delegated); the rates
    (errors-per-turn, delegated-per-turn) are computed here so the schema carries
    ready-to-render fractions and a zero-turn window is a clean 0.0 (no /0).
    """
    turns = agg["turns"]
    delegated = agg["delegated"]
    return TurnHealthWindow(
        turns=turns,
        errors=agg["errors"],
        error_rate=(agg["errors"] / turns) if turns else 0.0,
        avg_duration_ms=agg["avg_duration_ms"],
        p95_duration_ms=agg["p95_duration_ms"],
        avg_rounds=agg["avg_rounds"],
        delegated_turns=delegated,
        delegated_rate=(delegated / turns) if turns else 0.0,
        input_tokens=agg["input_tokens"],
        output_tokens=agg["output_tokens"],
        # 协作质量 (学·度量 §2.5): 首计划存活率 over delegated turns + raw window sums.
        first_plan_survival_rate=(
            (agg["first_plan_survived"] / delegated) if delegated else 0.0
        ),
        scope_signals=agg["scope_signals"],
        revises=agg["revises"],
        escalations=agg["escalations"],
    )


def _admin_user_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        is_unlimited=user.is_unlimited,
        quota_daily_tokens=user.quota_daily_tokens,
        quota_monthly_cost_usd=user.quota_monthly_cost_usd,
        quota_daily_cost_usd=user.quota_daily_cost_usd,
        quota_daily_requests=user.quota_daily_requests,
        created_at=user.created_at,
        deleted_at=user.deleted_at,
    )


def _admin_user_list_item(user: User, cost_total: int) -> AdminUserListItem:
    """A roster row = the account record + its all-time cumulative spend (nano-USD)."""
    return AdminUserListItem(**_admin_user_response(user).model_dump(), cost_total=cost_total)

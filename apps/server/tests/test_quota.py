"""Unit tests for quota enforcement (成本配额与计费.md §一).

The fake repo stands in for ``CostEventRepository``: ``enforce_quota`` only needs
``aggregate_for_window``. ``_NOW`` is mid-month so the day window (15th 00:00) and
month window (1st 00:00) have distinct ``since.day`` values, letting the fake tell
them apart and letting us assert *which* window was queried.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.core.errors import QuotaExceededError
from agentcore.llm.pricing import NANO_PER_CNY

_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _agg(*, input_: int = 0, output: int = 0, turns: int = 0, cost_total: int = 0) -> dict:
    return {
        "usage": {
            "input": input_,
            "output": output,
            "reasoning": 0,
            "cache_hit": 0,
            "cache_miss": 0,
        },
        "cost": {"input": 0, "cached": 0, "output": 0, "total": cost_total},
        "rounds": 0,
        "turns": turns,
    }


class _FakeRepo:
    """Returns the month rollup for the month-start window, else the day rollup."""

    def __init__(self, *, today: dict | None = None, month: dict | None = None):
        self._today = today or _agg()
        self._month = month or _agg()
        self.windows: list[datetime] = []

    async def aggregate_for_window(self, *, user_id: str, since: datetime) -> dict:
        self.windows.append(since)
        return self._month if since.day == 1 else self._today


async def test_all_unlimited_skips_db():
    repo = _FakeRepo(today=_agg(input_=10**9, output=10**9, turns=10**6))
    await enforce_quota(repo, "u1", now=_NOW, limits=QuotaLimits(0, 0, 0, 0))
    assert repo.windows == []  # no DB read when every dimension is unlimited


async def test_under_all_limits_passes():
    repo = _FakeRepo(
        today=_agg(input_=400, output=100, turns=5),
        month=_agg(cost_total=NANO_PER_CNY),  # ¥1 of ¥5
    )
    limits = QuotaLimits(daily_tokens=1000, monthly_cost_nano=5 * NANO_PER_CNY, daily_requests=10)
    await enforce_quota(repo, "u1", now=_NOW, limits=limits)


async def test_daily_tokens_exceeded():
    repo = _FakeRepo(today=_agg(input_=600, output=500, turns=1))  # 1100 > 1000
    limits = QuotaLimits(daily_tokens=1000, monthly_cost_nano=0, daily_requests=0)
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "daily_tokens"
    assert ei.value.status_code == 429
    assert ei.value.used == 1100


async def test_daily_requests_exceeded():
    repo = _FakeRepo(today=_agg(input_=1, output=1, turns=200))
    limits = QuotaLimits(daily_tokens=0, monthly_cost_nano=0, daily_requests=200)
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "daily_requests"


async def test_monthly_cost_exceeded():
    repo = _FakeRepo(
        today=_agg(input_=1, output=1, turns=1),
        month=_agg(cost_total=6 * NANO_PER_CNY),  # ¥6 > ¥5
    )
    limits = QuotaLimits(daily_tokens=0, monthly_cost_nano=5 * NANO_PER_CNY, daily_requests=0)
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "monthly_cost"


async def test_daily_cost_exceeded():
    repo = _FakeRepo(today=_agg(cost_total=3 * NANO_PER_CNY))
    limits = QuotaLimits(
        daily_tokens=0, monthly_cost_nano=0, daily_requests=0, daily_cost_nano=2 * NANO_PER_CNY
    )
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "daily_cost"
    assert ei.value.status_code == 429
    assert ei.value.used == 3 * NANO_PER_CNY
    assert "接入自己的 key" in ei.value.message


async def test_daily_cost_reads_day_window_not_month():
    repo = _FakeRepo(today=_agg(cost_total=5 * NANO_PER_CNY), month=_agg(cost_total=0))
    limits = QuotaLimits(0, 0, 0, daily_cost_nano=4 * NANO_PER_CNY)
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "daily_cost"
    assert all(since.day != 1 for since in repo.windows)


async def test_monthly_message_carries_admin_and_byok_exit():
    repo = _FakeRepo(month=_agg(cost_total=200 * NANO_PER_CNY))
    limits = QuotaLimits(0, monthly_cost_nano=10 * NANO_PER_CNY, daily_requests=0)
    with pytest.raises(QuotaExceededError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert ei.value.dimension == "monthly_cost"
    assert "管理员" in ei.value.message
    assert "接入自己的 key" in ei.value.message


async def test_zero_dimension_is_unlimited():
    repo = _FakeRepo(today=_agg(input_=10**9, output=10**9, turns=1))
    limits = QuotaLimits(daily_tokens=0, monthly_cost_nano=0, daily_requests=10)
    await enforce_quota(repo, "u1", now=_NOW, limits=limits)


async def test_at_limit_counts_as_exceeded():
    repo = _FakeRepo(today=_agg(input_=1000, output=0, turns=0))
    limits = QuotaLimits(daily_tokens=1000, monthly_cost_nano=0, daily_requests=0)
    with pytest.raises(QuotaExceededError):
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)


async def test_month_window_not_queried_when_daily_fails():
    repo = _FakeRepo(today=_agg(input_=2000, output=0, turns=1))
    limits = QuotaLimits(daily_tokens=1000, monthly_cost_nano=5 * NANO_PER_CNY, daily_requests=0)
    with pytest.raises(QuotaExceededError):
        await enforce_quota(repo, "u1", now=_NOW, limits=limits)
    assert all(since.day != 1 for since in repo.windows)


def test_all_unlimited_property():
    assert QuotaLimits(0, 0, 0, 0).all_unlimited
    assert not QuotaLimits(1, 0, 0, 0).all_unlimited
    assert not QuotaLimits(0, 1, 0, 0).all_unlimited
    assert not QuotaLimits(0, 0, 1, 0).all_unlimited
    assert not QuotaLimits(0, 0, 0, 1).all_unlimited


def test_from_settings_converts_costs_to_nano():
    limits = QuotaLimits.from_settings()
    assert limits.daily_tokens == settings.quota_daily_tokens
    assert limits.daily_requests == settings.quota_daily_requests
    assert limits.monthly_cost_nano == int(settings.quota_monthly_cost_cny * NANO_PER_CNY)
    assert limits.daily_cost_nano == int(settings.quota_daily_cost_cny * NANO_PER_CNY)
    assert limits.monthly_cost_nano == 10 * NANO_PER_CNY
    assert limits.daily_cost_nano == 10 * NANO_PER_CNY


# --- per-user resolution (QuotaLimits.for_user) ---


def _user(
    *,
    is_unlimited: bool = False,
    daily_tokens: int | None = None,
    monthly_cost_cny: float | None = None,
    daily_cost_cny: float | None = None,
    daily_requests: int | None = None,
) -> SimpleNamespace:
    """A stand-in for the User ORM row: for_user only reads these override columns."""
    return SimpleNamespace(
        is_unlimited=is_unlimited,
        quota_daily_tokens=daily_tokens,
        quota_monthly_cost_cny=monthly_cost_cny,
        quota_daily_cost_cny=daily_cost_cny,
        quota_daily_requests=daily_requests,
    )


def test_for_user_is_unlimited_collapses_to_all_unlimited():
    limits = QuotaLimits.for_user(
        _user(is_unlimited=True, daily_tokens=1, monthly_cost_cny=1, daily_requests=1)
    )
    assert limits == QuotaLimits(0, 0, 0)
    assert limits.all_unlimited


def test_for_user_none_overrides_inherit_config():
    assert QuotaLimits.for_user(_user()) == QuotaLimits.from_settings()


def test_for_user_per_dimension_override_is_isolated():
    limits = QuotaLimits.for_user(_user(daily_tokens=50))
    assert limits.daily_tokens == 50
    assert limits.daily_requests == settings.quota_daily_requests
    assert limits.monthly_cost_nano == int(settings.quota_monthly_cost_cny * NANO_PER_CNY)


def test_for_user_explicit_zero_unlimits_that_dimension():
    limits = QuotaLimits.for_user(
        _user(daily_tokens=0, monthly_cost_cny=0, daily_cost_cny=0, daily_requests=0)
    )
    assert limits == QuotaLimits(0, 0, 0, 0)


def test_for_user_monthly_cny_override_converted_to_nano():
    limits = QuotaLimits.for_user(_user(monthly_cost_cny=20.0))
    assert limits.monthly_cost_nano == 20 * NANO_PER_CNY


def test_for_user_daily_cost_override_converted_to_nano():
    limits = QuotaLimits.for_user(_user(daily_cost_cny=10.0))
    assert limits.daily_cost_nano == 10 * NANO_PER_CNY
    assert limits.monthly_cost_nano == int(settings.quota_monthly_cost_cny * NANO_PER_CNY)


def test_for_user_daily_cost_inherits_config_when_unset():
    assert QuotaLimits.for_user(_user()).daily_cost_nano == int(
        settings.quota_daily_cost_cny * NANO_PER_CNY
    )

"""Quota enforcement — the「总量」防线 that refuses a new turn once a user has
exhausted a configured usage window (成本配额与计费.md §一).

Four independent dimensions, each with its own rolling window:

| 维度          | 窗口         | 阈值 (config)               |
|---------------|--------------|-----------------------------|
| 日 token      | 当日 0 点起  | ``quota_daily_tokens`` |
| 月成本 (CNY)  | 当月 1 号起  | ``quota_monthly_cost_cny`` |
| 日请求数      | 当日 0 点起  | ``quota_daily_requests`` |
| 日成本 (CNY)  | 当日 0 点起  | ``quota_daily_cost_cny`` |

A ``0`` threshold means that dimension is unlimited (fail-safe 宽松默认); when
*every* dimension is unlimited the check skips the DB read entirely. The check is
turn-granular and runs **before** a turn starts — an exhausted account is refused
its *next* turn rather than having an in-flight reply cut off (不腰斩进行中回合).
Spend is read from the ``cost_events`` ledger (the money truth source, 不变量
#1), so the limit reflects 真实记账 rather than an estimate.

Limits resolve per user: ``QuotaLimits.for_user`` reads the override columns on
the ``users`` row (NULL = inherit global ``quota_*``; an explicit ``0`` =
unlimited for that dimension). ``is_unlimited`` collapses to all-unlimited so a
trusted/operator account is never gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentcore.config import settings
from agentcore.core.errors import QuotaExceededError
from agentcore.db.repositories import CostEventRepository
from agentcore.llm.pricing import NANO_PER_CNY, nano_to_yuan

if TYPE_CHECKING:
    from agentcore.db.models import User


# Secondary weakened exit appended to platform-quota refusals (成本配额与计费 §〇·六
# F6): platform额度耗尽 = 等重置 / 联系管理员为主, 「接入自己的 key」为次级出口 (byok
# 回合不查配额, 是真正的绕过路径). The client maps QUOTA_EXCEEDED → 设置·模型配置 CTA.
_BYOK_EXIT = "或接入自己的 key 继续（设置 · 模型配置）"


@dataclass(frozen=True)
class QuotaLimits:
    """Resolved quota thresholds (``0`` = that dimension is unlimited).

    Cost dimensions are pre-converted from the CNY config to the ledger's integer
    nano-CNY unit so the comparison stays in one currency口径. ``daily_cost_nano``
    is the 单日成本 backstop (防单日打爆); it rides last for positional back-compat.
    """

    daily_tokens: int
    monthly_cost_nano: int
    daily_requests: int
    daily_cost_nano: int = 0

    @classmethod
    def from_settings(cls) -> QuotaLimits:
        return cls(
            daily_tokens=settings.quota_daily_tokens,
            monthly_cost_nano=int(settings.quota_monthly_cost_cny * NANO_PER_CNY),
            daily_requests=settings.quota_daily_requests,
            daily_cost_nano=int(settings.quota_daily_cost_cny * NANO_PER_CNY),
        )

    @classmethod
    def for_user(cls, user: User) -> QuotaLimits:
        """Resolve limits for ``user``: override columns, else global ``quota_*``.

        ``is_unlimited`` short-circuits to all-unlimited. For every dimension a
        ``None`` override inherits the global defaults, while an explicit ``0``
        means that dimension is unlimited *for this user*.
        """
        if user.is_unlimited:
            return cls(0, 0, 0, 0)
        defaults = cls.from_settings()
        monthly_cny = (
            user.quota_monthly_cost_cny
            if user.quota_monthly_cost_cny is not None
            else settings.quota_monthly_cost_cny
        )
        daily_cny = (
            user.quota_daily_cost_cny
            if getattr(user, "quota_daily_cost_cny", None) is not None
            else settings.quota_daily_cost_cny
        )
        return cls(
            daily_tokens=(
                user.quota_daily_tokens
                if user.quota_daily_tokens is not None
                else defaults.daily_tokens
            ),
            monthly_cost_nano=int(monthly_cny * NANO_PER_CNY),
            daily_requests=(
                user.quota_daily_requests
                if user.quota_daily_requests is not None
                else defaults.daily_requests
            ),
            daily_cost_nano=int(daily_cny * NANO_PER_CNY),
        )

    @property
    def all_unlimited(self) -> bool:
        return (
            self.daily_tokens <= 0
            and self.monthly_cost_nano <= 0
            and self.daily_requests <= 0
            and self.daily_cost_nano <= 0
        )


async def enforce_quota(
    repo: CostEventRepository,
    user_id: str,
    *,
    now: datetime | None = None,
    limits: QuotaLimits | None = None,
) -> None:
    """Raise ``QuotaExceededError`` if ``user_id`` has hit any quota.

    No-op (and no DB read) when every dimension is unlimited. Otherwise sums the
    user's ledger over the day window (daily tokens + requests + daily cost);
    only if those pass *and* a monthly cap is configured does it read the month
    window (monthly cost). That is 1–2 indexed aggregates on
    ``ix_cost_events_user_created`` — light enough for the turn hot path.
    """
    limits = limits or QuotaLimits.from_settings()
    if limits.all_unlimited:
        return

    now = now or datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    today = await repo.aggregate_for_window(user_id=user_id, since=day_start)

    if limits.daily_tokens > 0:
        # Canonical "total tokens" = input + output (output already includes
        # reasoning), matching TokenUsage.total_tokens.
        used = int(today["usage"]["input"]) + int(today["usage"]["output"])
        if used >= limits.daily_tokens:
            raise QuotaExceededError(
                f"已达每日 token 上限（{used:,} / {limits.daily_tokens:,}），"
                f"明日 0 点（UTC）重置；{_BYOK_EXIT}。",
                dimension="daily_tokens",
                used=used,
                limit=limits.daily_tokens,
            )

    if limits.daily_requests > 0:
        # 一回合 = 一个 assistant message_id（与对话累计 / 仪表盘的「请求」口径一致）。
        used = int(today["turns"])
        if used >= limits.daily_requests:
            raise QuotaExceededError(
                f"已达每日请求上限（{used} / {limits.daily_requests}），"
                f"明日 0 点（UTC）重置；{_BYOK_EXIT}。",
                dimension="daily_requests",
                used=used,
                limit=limits.daily_requests,
            )

    # 日成本 backstop: reuses the day window already fetched — no extra DB read.
    if limits.daily_cost_nano > 0:
        used = int(today["cost"]["total"])
        if used >= limits.daily_cost_nano:
            spent_cny = nano_to_yuan(used)
            cap_cny = nano_to_yuan(limits.daily_cost_nano)
            raise QuotaExceededError(
                f"已达今日额度上限（约 ¥{spent_cny:.2f} / ¥{cap_cny:.2f}），"
                f"明日 0 点（UTC）重置；{_BYOK_EXIT}。",
                dimension="daily_cost",
                used=used,
                limit=limits.daily_cost_nano,
            )

    if limits.monthly_cost_nano > 0:
        month_start = day_start.replace(day=1)
        month = await repo.aggregate_for_window(user_id=user_id, since=month_start)
        used = int(month["cost"]["total"])
        if used >= limits.monthly_cost_nano:
            spent_cny = nano_to_yuan(used)
            cap_cny = nano_to_yuan(limits.monthly_cost_nano)
            # F6 主文案: 用完 + 下月 1 日重置 + 联系管理员提额; _BYOK_EXIT = 次级弱化出口.
            raise QuotaExceededError(
                f"本月额度已用完（约 ¥{spent_cny:.2f} / ¥{cap_cny:.2f}），"
                f"下月 1 日（UTC）重置；测试需要可联系管理员提额，{_BYOK_EXIT}。",
                dimension="monthly_cost",
                used=used,
                limit=limits.monthly_cost_nano,
            )

"""Cost display and quota settings.

Two default groups (决策④ / D7 / F2):

* Global ``quota_*`` — the ``billing_mode=platform`` full platform-paid deployment
  (内测计费翻转, 成本配额与计费 §〇·六 F2): 月成本 ≈¥1000 + **日成本** ≈¥100 (防单日
  打爆) + 500 请求/日. 日 token 维 0 (退出值守 — 多模型目录单价差 ~30×, token 帽映射
  不了钱).
* Free-tier ``free_tier_*`` — the byok deployment's platform-paid paths (免费档
  fallback / 显式偏好 platform): ≈¥1/月 · 200k token/日 · 50 请求/日, 原样保留.

``0`` = that dimension is unlimited. Monthly / daily cost are USD (float), converted
to nano-USD at check time (决策①). Values are internal-beta 起步值 — adjust by 运营数据.
"""

from pydantic import BaseModel


class QuotaSettings(BaseModel):
    cny_per_usd: float = 7.2
    # Global defaults for billing_mode=platform (full platform-paid deployment, F2).
    # daily_tokens=0 → 退出值守 (token 帽在多模型目录下映射不了钱, 由日成本维兜底).
    quota_daily_tokens: int = 0
    quota_monthly_cost_usd: float = 138.89  # ≈¥1000 @ cny_per_usd=7.2
    quota_daily_cost_usd: float = 13.89  # ≈¥100/日 — 防单日打爆 / 脚本失控
    quota_daily_requests: int = 500
    # Free-tier defaults for byok deployments on any platform-paid path
    # (explicit platform preference or free-tier fallback). ≈¥1 / month.
    # daily_cost=0 (不限) keeps the byok free-tier behavior byte-identical.
    free_tier_monthly_cost_usd: float = 0.14
    free_tier_daily_cost_usd: float = 0.0
    free_tier_daily_tokens: int = 200_000
    free_tier_daily_requests: int = 50

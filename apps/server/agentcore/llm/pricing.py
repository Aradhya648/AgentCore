"""Single source of truth for turning token usage into money (不变量 #2).

Every place that needs a cost calls :func:`calculate_cost` — there is no other
price table and no per-site arithmetic. **Ledger authority is nano-CNY**
(``1 CNY = 1e9 nano``); curated domestic cards write ¥/1M tokens directly.
API / display paths use nano-CNY with no FX (``nano_to_yuan``; ``cny_total`` is yuan).

Money is never a float. Costs are computed in :class:`~decimal.Decimal` and
returned as integer **nano-CNY** — the canonical unit stored in the
``cost_events`` ledger and carried over the API. Display converts nano → 元
via :func:`nano_to_yuan` (``nano / 1e9``, no FX).

Pricing layers (call-level ``credential_source``):

- User (BYOK): community estimate table → ``unpriced`` (never Flash/glm fallback)
- Platform/vendor: curated ``_PRICING`` → community → glm-5.2 fallback + warning

User path never falls back to the default tier — unknown → ``unpriced`` (0).
Platform/vendor keep default-tier fallback + warning (quota must not go blank).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from agentcore.core.logging import get_logger
from agentcore.llm.community_prices import community_pricing_for
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO
from agentcore.llm.provider.protocol import TokenUsage

logger = get_logger(__name__)

# Call-level credential origin for pricing (replaces deployment ``billing_mode``).
# user = BYOK; platform = operator main key; vendor = doubao/kimi/zhipu extras.
CredentialSource = Literal["user", "platform", "vendor"]
PricingSource = Literal["curated", "estimated", "unpriced"]
_VENDOR_PREFIXES = frozenset({"doubao", "kimi", "zhipu"})

# 1 CNY expressed in nano-CNY. The ledger and API speak integer nano-CNY.
NANO_PER_CNY = 1_000_000_000

# 豆包 (Volcengine 方舟) routed model id — keyed WITH the ``doubao/`` prefix because
# that is the exact string that reaches calculate_cost: the ProviderRouter only strips
# the prefix when *calling* the vendor, so cost accounting still sees the original id.
# TODO(Phase 2 定价表): match by vendor prefix so a new dated version (…-2606xx) keeps
# its price instead of silently degrading to the default tier.
DOUBAO_SEED_TURBO = "doubao/doubao-seed-2-1-turbo-260628"

# Qwen-VL-Max (通义千问视觉) — model id constant for vision reader config.
# No curated CNY card this step (USD list withdrawn); platform path → community /
# glm fallback. Constant kept for imports elsewhere.
QWEN_VL_MAX = "qwen-vl-max"

# Platform upstream reference model id (OpenAI-compatible). Constant kept for
# imports; no curated card this step (USD list withdrawn).
PLATFORM_GPT_4O = "gpt-4o"

# Platform relay catalog models (billing_mode=platform 内测中转目录, 成本配额与计费 §〇·六 F4).
PLATFORM_RELAY_GLM_52 = "glm-5.2"  # 平台默认；bigmodel.cn 人民币列表价直写
# Second operator relay catalog id (jiurelay); same list price as glm-5.2, distinct
# PLATFORM_MODELS entry so it can carry its own PLATFORM_MODEL_CREDENTIALS + upstream_model.
PLATFORM_RELAY_GLM_52_JIU = "glm-5.2-jiu"
PLATFORM_RELAY_GROK_45 = "grok-4.5"  # id 常量保留；本步无 curated CNY 卡
# Vision-only on the operator relay (VISION_MODEL); curated so role=vision does not
# fall back to glm-5.2. Keep OFF PLATFORM_MODELS — not a user-selectable chat model.
PLATFORM_RELAY_KIMI_K25 = "kimi-k2.5"

# CNY per 1M tokens (F4 curated). 国内官价直写 ¥。
# DeepSeek：api-docs.deepseek.com/zh-cn/quick_start/pricing（人民币表）。
# gpt-4o / grok-4.5 / qwen-vl-max — 仍无 curated（不上架）。
_PRICING: dict[str, dict[str, Decimal]] = {
    # DeepSeek V4 — 中文定价页：百万 tokens 输入（缓存命中/未命中）/ 输出。
    # Flash: ¥0.02 / ¥1 / ¥2；Pro: ¥0.025 / ¥3 / ¥6（卡保留，allowlist 可暂不上架）。
    DEEPSEEK_V4_FLASH: {
        "cache_hit": Decimal("0.02"),
        "cache_miss": Decimal("1"),
        "output": Decimal("2"),
    },
    DEEPSEEK_V4_PRO: {
        "cache_hit": Decimal("0.025"),
        "cache_miss": Decimal("3"),
        "output": Decimal("6"),
    },
    # 豆包 doubao-seed-2.1-turbo via 火山方舟. Volcengine 豆包1.6 统一定价,
    # tiered by INPUT length; this is the 0–32K tier (input ¥0.8/1M, output ¥8/1M).
    # No usable cache tier: generic OpenAI-compatible provider doesn't surface a
    # prompt cache split, so input is always billed as a miss (cache_hit mirrors
    # cache_miss). Source: Volcengine 豆包大模型 1.6 定价 (2025 FORCE).
    DOUBAO_SEED_TURBO: {
        "cache_hit": Decimal("0.8"),
        "cache_miss": Decimal("0.8"),
        "output": Decimal("8"),
    },
    # Platform relay default "glm-5.2" — F4 curated = 智谱开放平台（bigmodel.cn）
    # 人民币列表价直写。Source: bigmodel.cn/pricing
    # GLM-5.2：输入 ¥8/1M、缓存命中 ¥2/1M、输出 ¥28/1M。
    PLATFORM_RELAY_GLM_52: {
        "cache_hit": Decimal("2"),
        "cache_miss": Decimal("8"),
        "output": Decimal("28"),
    },
    # Same nominal CNY card as glm-5.2 (second relay; catalog id differs).
    PLATFORM_RELAY_GLM_52_JIU: {
        "cache_hit": Decimal("2"),
        "cache_miss": Decimal("8"),
        "output": Decimal("28"),
    },
    # Platform vision (VISION_MODEL=kimi-k2.5 on tokenrhythm-class relay).
    # Effective CNY/1M from relay /models: in ¥4 / out ¥21 / cache_read ¥0.8.
    PLATFORM_RELAY_KIMI_K25: {
        "cache_hit": Decimal("0.8"),
        "cache_miss": Decimal("4"),
        "output": Decimal("21"),
    },
}

# Unknown / unset platform model falls back to glm-5.2 (has CNY curated card)
# rather than failing: a missing price must never crash a turn.
# Platform/vendor only — user path stays unpriced instead.
_DEFAULT_MODEL = PLATFORM_RELAY_GLM_52

# tokens × (CNY / 1M tokens) → nano-CNY  ==  tokens × cny_per_million × 1000.
_PER_MILLION_TO_NANO = Decimal(1000)


@dataclass(frozen=True)
class Cost:
    """A run's (or turn's) cost in integer nano-CNY.

    ``input`` is the whole input bill (cached + uncached); ``cached`` re-states
    just the cache-hit portion so the UI can show「省了多少」without re-pricing.
    ``output`` already includes reasoning tokens (reasoning is a billed subset of
    completion, not a separate line). ``total == input + output``.

    ``pricing_source`` records which price layer produced the numbers.
    ``credential_source`` rides along for ledger routing (user → estimated column).
    """

    input: int
    cached: int
    output: int
    total: int
    currency: str = "CNY"
    pricing_source: PricingSource = "curated"
    credential_source: CredentialSource = "platform"


def _nano(tokens: int, price_per_million: Decimal) -> int:
    """Price ``tokens`` at ``price_per_million`` CNY/1M, as integer nano-CNY."""
    if tokens <= 0:
        return 0
    value = Decimal(tokens) * price_per_million * _PER_MILLION_TO_NANO
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def resolve_credential_source(
    *,
    credential_source: CredentialSource | None = None,
    billing_mode: str | None = None,
    provider_name: str | None = None,
    model: str | None = None,
) -> CredentialSource:
    """Resolve call-level pricing source (never reads deployment ``billing_mode``).

    Precedence: explicit ``credential_source`` → provider name → model vendor
    prefix → legacy ``billing_mode`` alias (byok→user, else platform) → ambient
    log-context ``credential_source`` → ``platform`` (charge).
    """
    if credential_source is not None:
        return credential_source
    if provider_name in _VENDOR_PREFIXES:
        return "vendor"
    if provider_name == "user":
        return "user"
    if provider_name == "platform":
        return "platform"
    if model and "/" in model:
        prefix, _, _rest = model.partition("/")
        if prefix in _VENDOR_PREFIXES:
            return "vendor"
    if billing_mode is not None:
        return "user" if billing_mode == "byok" else "platform"
    try:
        from agentcore.core.log_context import get_log_value

        ambient = get_log_value("credential_source")
        if ambient in ("user", "platform", "vendor"):
            return ambient  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 — pricing must never depend on log plumbing
        pass
    return "platform"


def resolve_price_card(
    model: str,
    *,
    credential_source: CredentialSource,
) -> tuple[dict[str, Decimal] | None, PricingSource, bool]:
    """Resolve ``(card, pricing_source, used_flash_fallback)`` for one call.

    User: community → unpriced (never default-tier fallback).
    Platform/vendor: curated → community → glm-5.2 fallback.
    """
    if credential_source == "user":
        community = community_pricing_for(model)
        if community is not None:
            return community, "estimated", False
        return None, "unpriced", False

    curated = _PRICING.get(model)
    if curated is not None:
        return curated, "curated", False
    community = community_pricing_for(model)
    if community is not None:
        return community, "estimated", False
    return _PRICING[_DEFAULT_MODEL], "curated", True


def pricing_for(model: str) -> dict[str, Decimal]:
    """The price card for a model, falling back to the default (glm-5.2) tier."""
    card, _src, _fb = resolve_price_card(model, credential_source="platform")
    assert card is not None
    return card


def has_curated_pricing(model: str) -> bool:
    """Whether ``model`` has an authoritative curated price card (不落社区/回落).

    Platform catalog models MUST have one (成本配额与计费 §〇·六 F4): a default-tier
    ``cost.pricing_fallback`` on a platform-billed catalog row is a 漏配缺陷, not a
    graceful degrade. The catalog builder uses this to surface such misconfiguration.
    """
    return (model or "").strip() in _PRICING


def pricing_for_model(
    model: str,
    *,
    credential_source: CredentialSource | None = None,
    billing_mode: str | None = None,
) -> dict[str, Decimal] | None:
    """Price card for ``model``, or ``None`` when user path is unpriced."""
    source = resolve_credential_source(
        credential_source=credential_source, billing_mode=billing_mode, model=model
    )
    card, pricing_source, _fb = resolve_price_card(model, credential_source=source)
    if pricing_source == "unpriced":
        return None
    return card


def calculate_cost(
    model: str,
    usage: TokenUsage,
    *,
    credential_source: CredentialSource | None = None,
    billing_mode: str | None = None,
    provider_name: str | None = None,
) -> Cost:
    """Convert a run's token usage into money — the only place this happens.

    Input is split by cache hit/miss (DeepSeek pre-splits the counts); output is
    priced whole (reasoning already included). Returns integer nano-CNY.

    Pricing follows **call-level credential source** and the two-layer card
    resolve, not deployment ``settings.billing_mode``.

    Two guards keep the bill honest when upstream usage is imperfect:

    - **Cache-split reconciliation**: pricing the input by hit/miss alone silently
      bills it as 0 whenever the cache split is absent but the prompt isn't — e.g.
      a BYOK ``base_url`` pointing at a proxy/gateway that returns standard
      OpenAI usage without DeepSeek's ``prompt_cache_{hit,miss}_tokens``, a model
      swap, or a dropped field. So the uncached count is reconciled to
      ``max(input_tokens − cache_hit, cache_miss)``: on the native DeepSeek path
      (``hit + miss == prompt``) this is a no-op, and when the split is missing
      the whole prompt is priced as a cache miss instead of vanishing.
    - **Fallback visibility** (platform/vendor only): an unknown/unset ``model``
      degrades to the glm-5.2 tier, logged as ``cost.pricing_fallback``.
    """
    source = resolve_credential_source(
        credential_source=credential_source,
        billing_mode=billing_mode,
        provider_name=provider_name,
        model=model,
    )
    card, pricing_source, used_fallback = resolve_price_card(
        model, credential_source=source
    )
    if card is None:
        return Cost(
            input=0,
            cached=0,
            output=0,
            total=0,
            pricing_source="unpriced",
            credential_source=source,
        )

    if used_fallback and (usage.input_tokens or usage.output_tokens):
        logger.warning(
            "cost.pricing_fallback",
            model=model or "(unset)",
            fallback=_DEFAULT_MODEL,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    cache_miss_tokens = max(usage.input_tokens - usage.cache_hit_tokens, usage.cache_miss_tokens)
    cached = _nano(usage.cache_hit_tokens, card["cache_hit"])
    uncached = _nano(cache_miss_tokens, card["cache_miss"])
    output = _nano(usage.output_tokens, card["output"])
    input_total = cached + uncached
    return Cost(
        input=input_total,
        cached=cached,
        output=output,
        total=input_total + output,
        pricing_source=pricing_source,
        credential_source=source,
    )


def cache_savings(
    model: str,
    usage: TokenUsage,
    *,
    credential_source: CredentialSource | None = None,
    billing_mode: str | None = None,
) -> int:
    """Nano-CNY saved by prefix-cache hits this run vs. paying the miss price.

    ``cache_hit_tokens × (miss_price − hit_price)`` — powers the「前缀缓存替你省了
    ¥X」彩蛋 (§七E). Zero when nothing hit the cache.
    """
    p = pricing_for_model(
        model,
        credential_source=credential_source,
        billing_mode=billing_mode,
    )
    if p is None:
        return 0
    full = _nano(usage.cache_hit_tokens, p["cache_miss"])
    paid = _nano(usage.cache_hit_tokens, p["cache_hit"])
    return max(full - paid, 0)


def nano_to_yuan(nano: int) -> float:
    """Convert ledger nano-CNY to yuan for display, rounded to fen (2 decimals).

    ``nano / NANO_PER_CNY`` — no FX. Wire field ``cny_total`` carries this yuan value
    (name kept; semantics are 元, not USD×rate).
    """
    yuan = Decimal(nano) / Decimal(NANO_PER_CNY)
    return float(yuan.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

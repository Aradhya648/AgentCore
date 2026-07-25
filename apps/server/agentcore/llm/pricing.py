"""Single source of truth for turning token usage into money (不变量 #2).

Every place that needs a cost calls :func:`calculate_cost` — there is no other
price table and no per-site arithmetic. Prices are USD per 1M tokens: DeepSeek from
``docs/03-AI核心/DeepSeek-V4-API参考.md`` §三 (authoritative); third-party vendors
(豆包/方舟) from the vendor's published CNY rate converted at ``CNY_PER_USD`` (see the
table comments). Per-input-length tiers + FX-from-config are the Phase 2 定价表 item.

Money is never a float. Costs are computed in :class:`~decimal.Decimal` and
returned as integer **nano-USD** (1 USD = 1e9 nano) — the canonical unit stored
in the ``cost_events`` ledger and carried over the API. Only the display layer
converts to CNY (via the single configured rate), so rounding never accretes
across a month of aggregation.

Pricing layers (call-level ``credential_source``):

1. User-defined unit card (highest; only when ``credential_source=user``)
2. In-repo community estimate table
3. Curated ``_PRICING`` (platform/vendor ledger authority)

User path never falls back to Flash — unknown → ``unpriced`` (0). Platform/vendor
keep Flash fallback + warning (quota must not go blank).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from agentcore.core.logging import get_logger
from agentcore.llm.community_prices import community_pricing_for
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO
from agentcore.llm.provider.protocol import TokenUsage

logger = get_logger(__name__)

# Call-level credential origin for pricing (replaces deployment ``billing_mode``).
# user = BYOK; platform = operator main key; vendor = doubao/kimi/zhipu extras.
CredentialSource = Literal["user", "platform", "vendor"]
PricingSource = Literal["curated", "estimated", "user_defined", "unpriced"]
_VENDOR_PREFIXES = frozenset({"doubao", "kimi", "zhipu"})

# 1 USD expressed in nano-USD. The ledger and API speak integer nano-USD.
NANO_PER_USD = 1_000_000_000

# 豆包 (Volcengine 方舟) routed model id — keyed WITH the ``doubao/`` prefix because
# that is the exact string that reaches calculate_cost: the ProviderRouter only strips
# the prefix when *calling* the vendor, so cost accounting still sees the original id.
# TODO(Phase 2 定价表): match by vendor prefix so a new dated version (…-2606xx) keeps
# its price instead of silently degrading to Flash.
DOUBAO_SEED_TURBO = "doubao/doubao-seed-2-1-turbo-260628"

# Qwen-VL-Max (通义千问视觉) — the default board 读图 reader via DashScope's
# OpenAI-compatible endpoint (AI协作白板.md §九.4). Keyed by the exact ``vision_model``
# config string that reaches calculate_cost (config/llm.py default). Other vision models
# (GLM-4V / GPT-4o / 本地 vLLM…) are user-selectable and fall back to the default tier +
# a logged warning until added — same posture as any unpriced model.
QWEN_VL_MAX = "qwen-vl-max"

# Platform upstream reference model (OpenAI-compatible). Prices below are for ledger/quota.
# gpt-4o: OpenAI API list price (2025-04) as the platform reference tier.
PLATFORM_GPT_4O = "gpt-4o"

# Platform relay catalog models (billing_mode=platform 内测中转目录, 成本配额与计费 §〇·六 F4).
# The operator's relay upstream cost is ≈0; these are NOMINAL reference prices for
# ledger/quota only (名义记账, F4 要求目录模型必须有 curated 价卡). 名义参考价、运营可调.
PLATFORM_RELAY_52 = "5.2"  # 平台默认；名义按 gpt-4o 档
PLATFORM_RELAY_GROK_45 = "grok-4.5"  # 名义参考 community grok-3 档

# USD per 1M tokens. DeepSeek: docs/03-AI核心/DeepSeek-V4-API参考.md §三 (authoritative);
# cache_hit is ~50× cheaper than cache_miss — splitting input by hit/miss is what keeps
# the bill honest on multi-turn chats (DeepSeek prefix caching).
_PRICING: dict[str, dict[str, Decimal]] = {
    DEEPSEEK_V4_FLASH: {
        "cache_hit": Decimal("0.0028"),
        "cache_miss": Decimal("0.14"),
        "output": Decimal("0.28"),
    },
    DEEPSEEK_V4_PRO: {
        "cache_hit": Decimal("0.003625"),
        "cache_miss": Decimal("0.435"),
        "output": Decimal("0.87"),
    },
    # 豆包 doubao-seed-2.1-turbo via 火山方舟. Volcengine 豆包1.6 统一定价 (深度思考/非思考同价),
    # tiered by INPUT length; this is the 0–32K tier (input ¥0.8/1M, output ¥8/1M) — the
    # common case (debate prompts sit well under 32K). USD = CNY ÷ 7.2 (settings.cny_per_usd):
    # ¥0.8→$0.1111, ¥8→$1.1111. No usable cache tier here: the generic OpenAI-compatible
    # provider doesn't surface a prompt cache split, so input is always billed as a miss
    # (cache_hit mirrors cache_miss and is never exercised). Source: Volcengine 豆包大模型 1.6
    # 定价 (2025 FORCE). TODO(Phase 2 定价表): per-input-length tiers + FX from config.
    DOUBAO_SEED_TURBO: {
        "cache_hit": Decimal("0.1111"),
        "cache_miss": Decimal("0.1111"),
        "output": Decimal("1.1111"),
    },
    # Qwen-VL-Max via DashScope international (USD-denominated, the default compatible-mode
    # base_url): input $0.80/1M, output $3.20/1M, cache hit = 20% of input = $0.16/1M.
    # Source: 阿里云百炼模型价格 + help.aliyun.com/zh/model-studio Context Cache (命中缓存的输入
    # 按标准输入单价 20% 计费). QwenVLReader parses the OpenAI-style prompt-cache split
    # (``prompt_tokens_details.cached_tokens``, TokenUsage.from_openai_wire), so a reported
    # hit prices at this discounted rate; absent split still bills the prompt as a miss.
    QWEN_VL_MAX: {
        "cache_hit": Decimal("0.16"),
        "cache_miss": Decimal("0.80"),
        "output": Decimal("3.20"),
    },
    # Platform upstream — OpenAI gpt-4o (config/platform.py default platform_model).
    # Source: OpenAI API pricing (input $2.50/1M, cached input $1.25/1M, output $10/1M).
    PLATFORM_GPT_4O: {
        "cache_hit": Decimal("1.25"),
        "cache_miss": Decimal("2.50"),
        "output": Decimal("10.00"),
    },
    # Platform relay default "5.2" — 名义参考价、运营可调 (F4: platform catalog models MUST
    # be curated; actual relay cost ≈0). Tracks the gpt-4o tier (input $2.50/1M, cached
    # $1.25/1M, output $10/1M) so the ledger/quota stays honest without a real unit cost.
    PLATFORM_RELAY_52: {
        "cache_hit": Decimal("1.25"),
        "cache_miss": Decimal("2.50"),
        "output": Decimal("10.00"),
    },
    # Platform relay "grok-4.5" — 名义参考价、运营可调. References the community grok-3 tier
    # (community_prices.json: cache_hit $1.50/1M, input $3.00/1M, output $15.00/1M).
    PLATFORM_RELAY_GROK_45: {
        "cache_hit": Decimal("1.50"),
        "cache_miss": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
}

# Unknown / unset model falls back to the cheaper Flash tier rather than failing:
# a missing price must never crash a turn (the bill degrades, the chat does not).
# Platform/vendor only — user path stays unpriced instead.
_DEFAULT_MODEL = DEEPSEEK_V4_FLASH

# tokens × (USD / 1M tokens) → nano-USD  ==  tokens × usd_per_million × 1000.
_USD_PER_MILLION_TO_NANO = Decimal(1000)


@dataclass(frozen=True)
class Cost:
    """A run's (or turn's) cost in integer nano-USD.

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
    currency: str = "USD"
    pricing_source: PricingSource = "curated"
    credential_source: CredentialSource = "platform"


def _nano(tokens: int, price_per_million: Decimal) -> int:
    """Price ``tokens`` at ``price_per_million`` USD/1M, as integer nano-USD."""
    if tokens <= 0:
        return 0
    value = Decimal(tokens) * price_per_million * _USD_PER_MILLION_TO_NANO
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


def parse_user_prices(
    *,
    cache_hit: str | None = None,
    cache_miss: str | None = None,
    output: str | None = None,
) -> dict[str, Decimal] | None:
    """Parse optional USD-per-1M decimal strings into a price card, or ``None``.

    Only input (cache_miss) + output are required — most vendors publish just
    those two. ``cache_hit`` defaults to the input price (no cache discount),
    which over- rather than under-estimates.
    """
    if not (cache_miss and output):
        return None
    try:
        card = {
            "cache_hit": Decimal(str(cache_hit).strip() if cache_hit else str(cache_miss).strip()),
            "cache_miss": Decimal(str(cache_miss).strip()),
            "output": Decimal(str(output).strip()),
        }
    except (InvalidOperation, ValueError):
        return None
    if any(v < 0 for v in card.values()):
        return None
    return card


def _ambient_user_prices() -> dict[str, Decimal] | None:
    try:
        from agentcore.core.log_context import get_log_value

        return parse_user_prices(
            cache_hit=get_log_value("user_price_cache_hit") or None,
            cache_miss=get_log_value("user_price_cache_miss") or None,
            output=get_log_value("user_price_output") or None,
        )
    except Exception:  # noqa: BLE001
        return None


def resolve_price_card(
    model: str,
    *,
    credential_source: CredentialSource,
    user_prices: dict[str, Decimal] | None = None,
) -> tuple[dict[str, Decimal] | None, PricingSource, bool]:
    """Resolve ``(card, pricing_source, used_flash_fallback)`` for one call.

    User: user_defined → community → unpriced (never Flash).
    Platform/vendor: curated → community → Flash fallback.
    """
    if credential_source == "user":
        card = user_prices or _ambient_user_prices()
        if card is not None:
            return card, "user_defined", False
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
    """The price card for a model, falling back to the default (Flash) tier."""
    card, _src, _fb = resolve_price_card(model, credential_source="platform")
    assert card is not None
    return card


def has_curated_pricing(model: str) -> bool:
    """Whether ``model`` has an authoritative curated price card (不落社区/回落).

    Platform catalog models MUST have one (成本配额与计费 §〇·六 F4): a Flash
    ``cost.pricing_fallback`` on a platform-billed catalog row is a 漏配缺陷, not a
    graceful degrade. The catalog builder uses this to surface such misconfiguration.
    """
    return (model or "").strip() in _PRICING


def pricing_for_model(
    model: str,
    *,
    credential_source: CredentialSource | None = None,
    billing_mode: str | None = None,
    user_prices: dict[str, Decimal] | None = None,
) -> dict[str, Decimal] | None:
    """Price card for ``model``, or ``None`` when user path is unpriced."""
    source = resolve_credential_source(
        credential_source=credential_source, billing_mode=billing_mode, model=model
    )
    card, pricing_source, _fb = resolve_price_card(
        model, credential_source=source, user_prices=user_prices
    )
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
    user_prices: dict[str, Decimal] | None = None,
) -> Cost:
    """Convert a run's token usage into money — the only place this happens.

    Input is split by cache hit/miss (DeepSeek pre-splits the counts); output is
    priced whole (reasoning already included). Returns integer nano-USD.

    Pricing follows **call-level credential source** and the three-layer card
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
      degrades to the Flash tier, logged as ``cost.pricing_fallback``.
    """
    source = resolve_credential_source(
        credential_source=credential_source,
        billing_mode=billing_mode,
        provider_name=provider_name,
        model=model,
    )
    card, pricing_source, used_fallback = resolve_price_card(
        model, credential_source=source, user_prices=user_prices
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
    user_prices: dict[str, Decimal] | None = None,
) -> int:
    """Nano-USD saved by prefix-cache hits this run vs. paying the miss price.

    ``cache_hit_tokens × (miss_price − hit_price)`` — powers the「前缀缓存替你省了
    ¥X」彩蛋 (§七E). Zero when nothing hit the cache.
    """
    p = pricing_for_model(
        model,
        credential_source=credential_source,
        billing_mode=billing_mode,
        user_prices=user_prices,
    )
    if p is None:
        return 0
    full = _nano(usage.cache_hit_tokens, p["cache_miss"])
    paid = _nano(usage.cache_hit_tokens, p["cache_hit"])
    return max(full - paid, 0)


def nano_usd_to_cny(nano_usd: int, cny_per_usd: float) -> float:
    """Convert nano-USD to CNY yuan for display, rounded to fen (2 decimals).

    Display-only (the ledger stays USD nano). ``cny_per_usd`` is the single
    configured rate (``settings.cny_per_usd``), passed in to keep this pure.
    """
    yuan = Decimal(nano_usd) / Decimal(NANO_PER_USD) * Decimal(str(cny_per_usd))
    return float(yuan.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

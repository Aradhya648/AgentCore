"""Lightweight display metadata that ENRICHES a model id — never an allow-list.

Discovery decides WHICH models a user can pick: BYOK proxies the user's own
``GET /models`` (llm/catalog.py); the platform set is the operator's configured
models. This module only maps a known id → nicer catalog fields (display name /
vendor / capability tags / context length). An unknown id still gets a best-effort
derived entry, so the catalog always returns something usable — the goal is
enhancement, not gatekeeping (never hardcode「可选模型清单」to replace discovery).

Capability tags are a subset of ``{"vision", "tools", "reasoning"}`` — the same
three flags the frontend renders. Context length is a display hint (tokens).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The three capability flags surfaced in the catalog (contract §1). Kept as a
# module constant so the schema layer and tests share one source of truth.
CAPABILITY_VISION = "vision"
CAPABILITY_TOOLS = "tools"
CAPABILITY_REASONING = "reasoning"
KNOWN_CAPABILITIES = frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS, CAPABILITY_REASONING})


@dataclass(frozen=True)
class ModelMeta:
    """Display enrichment for one model id (all fields best-effort)."""

    display_name: str
    vendor: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    context_length: int | None = None


# Curated enrichment for ids AgentCore commonly sees (platform + popular BYOK
# endpoints). Keys are lowercase, provider-prefix-stripped; matching also does a
# longest-family prefix scan so a dated variant (…-2606xx) inherits its family's
# metadata. Context lengths are rounded display hints, not billing facts.
_METADATA: dict[str, ModelMeta] = {
    "deepseek-v4-flash": ModelMeta(
        display_name="DeepSeek V4 Flash",
        vendor="DeepSeek",
        capabilities=frozenset({CAPABILITY_TOOLS, CAPABILITY_REASONING}),
        context_length=128_000,
    ),
    "deepseek-v4-pro": ModelMeta(
        display_name="DeepSeek V4 Pro",
        vendor="DeepSeek",
        capabilities=frozenset({CAPABILITY_TOOLS, CAPABILITY_REASONING}),
        context_length=128_000,
    ),
    "gpt-4o": ModelMeta(
        display_name="GPT-4o",
        vendor="OpenAI",
        capabilities=frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS}),
        context_length=128_000,
    ),
    "gpt-4o-mini": ModelMeta(
        display_name="GPT-4o mini",
        vendor="OpenAI",
        capabilities=frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS}),
        context_length=128_000,
    ),
    "gpt-4.1": ModelMeta(
        display_name="GPT-4.1",
        vendor="OpenAI",
        capabilities=frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS}),
        context_length=1_000_000,
    ),
    "o3": ModelMeta(
        display_name="OpenAI o3",
        vendor="OpenAI",
        capabilities=frozenset({CAPABILITY_TOOLS, CAPABILITY_REASONING}),
        context_length=200_000,
    ),
    "qwen-vl-max": ModelMeta(
        display_name="Qwen-VL-Max",
        vendor="通义千问",
        capabilities=frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS}),
        context_length=32_000,
    ),
    "qwen-max": ModelMeta(
        display_name="Qwen-Max",
        vendor="通义千问",
        capabilities=frozenset({CAPABILITY_TOOLS}),
        context_length=32_000,
    ),
    "doubao-seed": ModelMeta(
        display_name="豆包 Seed",
        vendor="豆包 (火山方舟)",
        capabilities=frozenset({CAPABILITY_TOOLS}),
        context_length=256_000,
    ),
    "kimi-k2": ModelMeta(
        display_name="Kimi K2",
        vendor="Moonshot",
        capabilities=frozenset({CAPABILITY_TOOLS}),
        context_length=128_000,
    ),
    "moonshot-v1-128k": ModelMeta(
        display_name="Moonshot v1 128K",
        vendor="Moonshot",
        capabilities=frozenset({CAPABILITY_TOOLS}),
        context_length=128_000,
    ),
    "glm-4.6": ModelMeta(
        display_name="GLM-4.6",
        vendor="智谱 AI",
        capabilities=frozenset({CAPABILITY_TOOLS}),
        context_length=128_000,
    ),
    "glm-4v": ModelMeta(
        display_name="GLM-4V",
        vendor="智谱 AI",
        capabilities=frozenset({CAPABILITY_VISION, CAPABILITY_TOOLS}),
        context_length=8_000,
    ),
    # Platform relay default id (config/platform.py PLATFORM_MODEL). GLM-5.2 on
    # the operator's中转 upstream; curated as 智谱 AI for catalog display.
    "glm-5.2": ModelMeta(
        display_name="GLM-5.2",
        vendor="智谱 AI",
        capabilities=frozenset({CAPABILITY_TOOLS, CAPABILITY_REASONING}),
        context_length=128_000,
    ),
    "grok-4.5": ModelMeta(
        display_name="Grok 4.5",
        vendor="xAI",
        capabilities=frozenset({CAPABILITY_TOOLS, CAPABILITY_REASONING}),
        context_length=128_000,
    ),
}

# Vendor guesses by leading provider prefix / substring for unknown ids, so a
# derived entry still names a plausible vendor instead of "Unknown".
_VENDOR_HINTS: tuple[tuple[str, str], ...] = (
    ("deepseek", "DeepSeek"),
    ("gpt", "OpenAI"),
    ("o1", "OpenAI"),
    ("o3", "OpenAI"),
    ("o4", "OpenAI"),
    ("claude", "Anthropic"),
    ("gemini", "Google"),
    ("qwen", "通义千问"),
    ("doubao", "豆包 (火山方舟)"),
    ("kimi", "Moonshot"),
    ("moonshot", "Moonshot"),
    ("glm", "智谱 AI"),
    ("yi-", "零一万物"),
    ("mistral", "Mistral"),
    ("llama", "Meta"),
    ("grok", "xAI"),
)


def _normalize(model_id: str) -> str:
    """Lowercase and drop a single leading ``provider/`` route prefix."""
    key = (model_id or "").strip().lower()
    if "/" in key:
        _prefix, _, rest = key.partition("/")
        if rest:
            key = rest
    return key


def _derive_capabilities(key: str) -> frozenset[str]:
    """Best-effort capability tags from id keywords (conservative — omit if unsure)."""
    caps: set[str] = set()
    if any(tok in key for tok in ("-vl", "vision", "-v-", "4o", "4v", "gemini", "omni")):
        caps.add(CAPABILITY_VISION)
    if any(tok in key for tok in ("reason", "think", "-r1", "o1", "o3", "o4", "-r-")):
        caps.add(CAPABILITY_REASONING)
    return frozenset(caps)


def _derive_vendor(key: str) -> str:
    for token, vendor in _VENDOR_HINTS:
        if token in key:
            return vendor
    return "其他"


def _humanize(model_id: str) -> str:
    """A readable display name for an unknown id (keep the raw id, tidy separators)."""
    raw = (model_id or "").strip()
    if not raw:
        return "未知模型"
    tail = raw.rsplit("/", 1)[-1]
    return tail.replace("_", " ").replace("-", " ").strip() or tail


def model_metadata_for(model_id: str) -> ModelMeta:
    """Enrichment for ``model_id`` — exact, then family-prefix, then derived.

    Never returns ``None``: an unknown id yields a derived entry (humanized name,
    vendor guess, keyword-inferred capabilities) so the catalog stays complete.
    """
    key = _normalize(model_id)
    if not key:
        return ModelMeta(display_name=_humanize(model_id), vendor="其他")
    exact = _METADATA.get(key)
    if exact is not None:
        return exact
    # Longest-family prefix: a dated / sized variant inherits its family entry.
    best_key: str | None = None
    for known in _METADATA:
        if key.startswith(known) and (best_key is None or len(known) > len(best_key)):
            best_key = known
    if best_key is not None:
        return _METADATA[best_key]
    return ModelMeta(
        display_name=_humanize(model_id),
        vendor=_derive_vendor(key),
        capabilities=_derive_capabilities(key),
    )

"""SimAgent LLM resolution — DeepSeek via platform, BYOK, or eval env."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.factory import build_provider
from agentcore.llm.profiles import PLATFORM_MODEL_FLASH, PLATFORM_MODEL_PRO
from agentcore.llm.provider.protocol import LLMProvider
from agentcore.llm.resolve import (
    ModelConfig,
    platform_llm_credentials,
    resolve_user_llm_credentials,
)


class SimModelTier(StrEnum):
    """Decision importance tier for model routing (BE-13)."""

    ROUTINE = "routine"
    CRITICAL = "critical"


class SimDecisionKind(StrEnum):
    """What an LLM call serves this tick — the input to the routing strategy (WS-D)."""

    ROUTINE_TICK = "routine_tick"  # per-agent movement / stay / idle
    INTERACTION = "interaction"  # trade / vote / conversation protocol resolution
    REFLECTION = "reflection"  # low-frequency self-reflection & goal update


# Known "upgrade" pairs: a fast routine model → a stronger model for critical decisions.
# When the resolved base model is not a known upgradable id (BYOK / proxy), critical safely
# aliases the base so we never emit an invalid model name.
SIM_ROUTINE_MODEL = PLATFORM_MODEL_FLASH
SIM_CRITICAL_MODEL = PLATFORM_MODEL_PRO
_CRITICAL_UPGRADES: dict[str, str] = {SIM_ROUTINE_MODEL: SIM_CRITICAL_MODEL}

# The routing strategy: which decisions warrant the critical tier, and why (explainable).
_CRITICAL_DECISIONS: frozenset[SimDecisionKind] = frozenset(
    {SimDecisionKind.INTERACTION, SimDecisionKind.REFLECTION}
)
_DECISION_RATIONALE: dict[SimDecisionKind, str] = {
    SimDecisionKind.ROUTINE_TICK: "日常移动/停留：高频、低风险，用快速模型即可",
    SimDecisionKind.INTERACTION: "交易/投票/对话：多方博弈且改变世界状态，值得更强模型",
    SimDecisionKind.REFLECTION: "低频反思与目标调整：影响长期行为走向，值得更强模型",
}


def tier_for_decision(kind: SimDecisionKind) -> SimModelTier:
    """Map a decision kind to its model tier (the core routing policy)."""
    return SimModelTier.CRITICAL if kind in _CRITICAL_DECISIONS else SimModelTier.ROUTINE


class SimModelRoutingConfig(BaseModel):
    """Per-run model routing manifest: a model id per decision tier."""

    routine_model: str
    critical_model: str = Field(
        description="Model for pivotal decisions (interactions, reflection); "
        "upgraded from routine when a known mapping exists, else aliases routine."
    )


def default_routing_config(base_model: str) -> SimModelRoutingConfig:
    """Routine tier uses the resolved base model; critical tier upgrades to a stronger
    model when a known mapping exists (e.g. deepseek-v4-flash → deepseek-v4-pro)."""
    critical = _CRITICAL_UPGRADES.get(base_model, base_model)
    return SimModelRoutingConfig(routine_model=base_model, critical_model=critical)


class SimModelRouter:
    """Resolve which model to use for a given decision tier or decision kind."""

    def __init__(self, config: SimModelRoutingConfig):
        self._config = config

    @classmethod
    def from_run_config(cls, run_config: dict | None, *, fallback: str) -> SimModelRouter:
        raw = (run_config or {}).get("model_routing") or {}
        if raw.get("routine_model"):
            cfg = SimModelRoutingConfig.model_validate(raw)
        else:
            cfg = default_routing_config(fallback)
        return cls(cfg)

    @property
    def config(self) -> SimModelRoutingConfig:
        return self._config

    def resolve(self, tier: SimModelTier = SimModelTier.ROUTINE) -> str:
        if tier == SimModelTier.CRITICAL:
            return self._config.critical_model
        return self._config.routine_model

    def model_for_decision(self, kind: SimDecisionKind) -> str:
        """Resolve the model for a decision kind via the routing policy."""
        return self.resolve(tier_for_decision(kind))

    def explain_decision(self, kind: SimDecisionKind) -> str:
        """Human-readable justification for the tier chosen for ``kind``."""
        tier = tier_for_decision(kind)
        model = self.resolve(tier)
        return f"{kind.value}→{tier.value}（{model}）：{_DECISION_RATIONALE[kind]}"

    def to_manifest(self) -> dict:
        return {"model_routing": self._config.model_dump()}


class SimLlmNotConfigured(Exception):
    """No usable DeepSeek credentials for simulation."""


def is_deepseek_upstream(base_url: str) -> bool:
    return "deepseek.com" in (base_url or "").lower()


def sim_native_tools(base_url: str) -> bool:
    """DeepSeek supports native tool calling; other upstreams use text-JSON fallback."""
    return is_deepseek_upstream(base_url)


def _eval_credentials() -> LLMCredentials | None:
    key = os.environ.get("EVAL_DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    base = os.environ.get("EVAL_DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com"
    model = os.environ.get("EVAL_DEEPSEEK_MODEL", "").strip() or PLATFORM_MODEL_FLASH
    return LLMCredentials(api_key=key, base_url=base, default_model=model)


def _platform_deepseek() -> LLMCredentials | None:
    platform = platform_llm_credentials()
    if platform is None or not is_deepseek_upstream(platform.base_url):
        return None
    return platform


def _to_model_config(creds: LLMCredentials, *, source: str) -> ModelConfig:
    return ModelConfig(
        model=creds.default_model or PLATFORM_MODEL_FLASH,
        base_url=creds.base_url,
        api_key=creds.api_key,
        source=source,  # type: ignore[arg-type]
        purpose="sim.town",
    )


async def resolve_sim_model_config(
    session: AsyncSession | None,
    user_id: str | None,
) -> ModelConfig:
    """Resolve DeepSeek for sim: platform → user BYOK → EVAL_DEEPSEEK_*."""
    platform = _platform_deepseek()
    if platform is not None:
        return _to_model_config(platform, source="platform")

    if session is not None and user_id:
        byok = await resolve_user_llm_credentials(session, user_id)
        if byok is not None and is_deepseek_upstream(byok.base_url):
            return _to_model_config(byok, source="byok")

    eval_creds = _eval_credentials()
    if eval_creds is not None:
        return _to_model_config(eval_creds, source="platform")

    raise SimLlmNotConfigured(
        "模拟决策需要 DeepSeek：请在 .env 配置 PLATFORM_* 指向 api.deepseek.com，"
        "或在「设置·模型配置」保存 DeepSeek Key，或导出 EVAL_DEEPSEEK_API_KEY。"
    )


async def build_sim_provider(
    session: AsyncSession | None,
    user_id: str | None,
) -> tuple[LLMProvider, ModelConfig]:
    cfg = await resolve_sim_model_config(session, user_id)
    creds = LLMCredentials(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_model=cfg.model,
    )
    return build_provider(creds), cfg


def resolve_text_mode(
    base_url: str,
    *,
    override: bool | None,
) -> bool:
    if override is not None:
        return override
    return not sim_native_tools(base_url)

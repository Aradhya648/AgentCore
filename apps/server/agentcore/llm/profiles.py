"""Scenario profiles: inference params per usage scenario (model resolved separately)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentcore.llm.credentials import LLMCredentials

from agentcore.llm.provider.protocol import LLMMessage, LLMRequest

# Platform model id constants (eval / pricing / migration defaults).
PLATFORM_MODEL_FLASH = "deepseek-v4-flash"
PLATFORM_MODEL_PRO = "deepseek-v4-pro"
DEEPSEEK_V4_FLASH = PLATFORM_MODEL_FLASH
DEEPSEEK_V4_PRO = PLATFORM_MODEL_PRO

# Router / ``agent_provider_id`` sentinel when a worker override runs on platform credentials
# (main turn may be BYOK). ``route_model_for("agent")`` prefixes ``platform/{model}``;
# ``build_turn_router`` / debate extras register :func:`build_platform_provider` under
# this key (per-model credentials via ``platform_llm_credentials(model=…)``).
PLATFORM_PROVIDER_SENTINEL = "platform"


@dataclass(frozen=True)
class ProfileParams:
    """Inference params for one usage scenario (no model — use ModelConfig.model)."""

    temperature: float = 0.7
    max_tokens: int | None = None
    max_rounds: int = 16
    name: str = ""
    # None = provider default (DeepSeek V4 → thinking on). False = force off for
    # background one-shots (title / memory / …) — required so a 64-token title
    # budget is not eaten by reasoning_content (平台LLM接入 · DeepSeek 易错).
    thinking: bool | None = None


PROFILES: dict[str, ProfileParams] = {
    "chat": ProfileParams(temperature=0.7, max_rounds=16),
    # Single delegated-worker profile: one round budget (28) for every worker —
    # 力度差异由委派协作结构（拆分 / 复审 / replan）表达，不再有 per-worker 档位。
    "agent": ProfileParams(temperature=0.7, max_rounds=28),
    "memory": ProfileParams(temperature=0.3, max_rounds=1, thinking=False),
    "compaction": ProfileParams(temperature=0.3, max_rounds=1, thinking=False),
    "file.rewrite": ProfileParams(temperature=0.4, max_rounds=1, thinking=False),
    # max_tokens=1024: BYOK reasoning models (e.g. *.5.2) may spend budget on
    # reasoning_content even when thinking=False (only honored for DeepSeek V4);
    # 64 was enough for flash, 256 still hit finish_reason=length with EMPTY content
    # on *.5.2 (协作图压测: reasoning ate the whole budget, chips silently missing).
    # The garnish output itself is <100 tokens — the headroom is all for reasoning.
    "title": ProfileParams(temperature=0.3, max_tokens=1024, max_rounds=1, thinking=False),
    "followups": ProfileParams(temperature=0.5, max_tokens=1024, max_rounds=1, thinking=False),
}

_DEFAULT_PROFILE = "chat"


def get_profile(name: str) -> ProfileParams:
    resolved = name if name in PROFILES else _DEFAULT_PROFILE
    return replace(PROFILES[resolved], name=resolved)


def agent_profile() -> ProfileParams:
    """The single delegated-worker profile (unified round budget, no tiers)."""
    return get_profile("agent")


def build_request(
    profile: ProfileParams,
    messages: list[LLMMessage],
    *,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    stream: bool = True,
    model: str,
) -> LLMRequest:
    return LLMRequest(
        messages=messages,
        model=model,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        tools=tools,
        tool_choice=tool_choice if tools else "none",
        stream=stream,
        scenario=profile.name or _DEFAULT_PROFILE,
        thinking=profile.thinking,
    )


@dataclass(frozen=True)
class TurnProfiles:
    """Turn-level resolved model + static scenario params (replaces ProfileSet)."""

    model: str
    model_overrides: dict[str, str] = field(default_factory=dict)
    # BYOK provider id or ``PLATFORM_PROVIDER_SENTINEL`` for platform-credential worker
    # overrides; None = follow turn creds. Cross-origin / cross-provider worker defaults
    # register on the turn ProviderRouter so ``route_model_for("agent")`` can dispatch
    # with a ``provider_id/model`` (or ``platform/model``) prefix.
    agent_provider_id: str | None = None

    def model_for(self, profile_name: str) -> str:
        return self.model_overrides.get(profile_name, self.model)

    def route_model_for(
        self, profile_name: str, *, turn_provider_id: str | None = None
    ) -> str:
        """Model id for an LLMRequest — may include a router prefix for cross-provider agent."""
        model = self.model_for(profile_name)
        if (
            profile_name == "agent"
            and self.agent_provider_id
            and self.agent_provider_id != turn_provider_id
        ):
            return f"{self.agent_provider_id}/{model}"
        return model

    def get(self, name: str) -> ProfileParams:
        return get_profile(name)

    def agent(self) -> ProfileParams:
        return agent_profile()


def default_turn_profiles(*, model: str | None = None) -> TurnProfiles:
    from agentcore.config import settings

    return TurnProfiles(model=model or settings.platform_model)


def turn_profiles_for_turn(
    profile_set: TurnProfiles | None = None,
    llm_credentials: LLMCredentials | None = None,
) -> TurnProfiles:
    """Resolve turn profiles for a pipeline/sidecar run.

    BYOK and inference-proxy turns must not inherit ``settings.platform_model`` when
    the caller did not supply an explicit profile set — the upstream model comes from
    the user's credentials (direct BYOK) or from the proxy's server-side resolution.
    """
    if profile_set is not None:
        return profile_set
    if llm_credentials is not None:
        from agentcore.llm.resolve import resolve_turn_model

        return default_turn_profiles(model=resolve_turn_model(llm_credentials))
    return default_turn_profiles()


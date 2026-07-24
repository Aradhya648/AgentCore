"""Shared LLM profile helpers for engine/pipeline tests."""

from __future__ import annotations

from agentcore.llm.profiles import ProfileParams, TurnProfiles


def make_profile_params(*, max_rounds: int = 20, **kwargs: object) -> ProfileParams:
    """ProfileParams for react_loop tests (model via ``turn_model``)."""
    return ProfileParams(max_rounds=max_rounds, **kwargs)  # type: ignore[arg-type]


def make_turn_profiles(*, model: str = "chat-model") -> TurnProfiles:
    """TurnProfiles for pipeline/resume e2e tests."""
    return TurnProfiles(model=model)

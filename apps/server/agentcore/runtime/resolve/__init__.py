"""Turn resolve: prompt assembly, profile variants, CEO toolset wiring."""

from __future__ import annotations

from typing import Any

__all__ = [
    "CHAT_CITATION_HINT",
    "FRAGMENT_BASE",
    "FRAGMENT_CEO_CORE",
    "FRAGMENT_CEO_VISUALIZATION",
    "FRAGMENT_CITATION",
    "OVERRIDABLE_KEYS",
    "PromptProfile",
    "_assemble_ceo_toolset",
    "_build_attachment_context",
    "active_profile",
    "assemble_system_prompt",
    "compose_ceo_chat_prompt",
    "resolve",
    "use_profile",
]


def __getattr__(name: str) -> Any:
    # Lazy: importing ``ceo_surface`` / ``prompt`` must not pull the heavy
    # prepare → sessions → runs → debate chain (parallel modules may be mid-edit).
    if name in ("_assemble_ceo_toolset", "_build_attachment_context"):
        from agentcore.runtime.resolve import prepare as _prepare

        return getattr(_prepare, name)
    if name in (
        "FRAGMENT_BASE",
        "FRAGMENT_CEO_CORE",
        "FRAGMENT_CEO_VISUALIZATION",
        "FRAGMENT_CITATION",
        "OVERRIDABLE_KEYS",
        "PromptProfile",
        "active_profile",
        "resolve",
        "use_profile",
    ):
        from agentcore.runtime.resolve import profile as _profile

        return getattr(_profile, name)
    if name in (
        "CHAT_CITATION_HINT",
        "assemble_system_prompt",
        "compose_ceo_chat_prompt",
    ):
        from agentcore.runtime.resolve import prompt as _prompt

        return getattr(_prompt, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Eval-only quality-mode resolution (decoupled from production turn profiles)."""

from __future__ import annotations

import os

from agentcore.llm.profiles import (
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    TurnProfiles,
)

ROLE_CEO = "ceo"
ROLE_WORKER = "worker"

ROLE_TO_PROFILE: dict[str, str] = {
    ROLE_CEO: "chat",
    ROLE_WORKER: "agent",
}

CONFIGURABLE_ROLES: tuple[str, ...] = (ROLE_CEO, ROLE_WORKER)

KNOWN_MODELS: tuple[str, ...] = (DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO)

Assignments = dict[str, str]

SYSTEM_DEFAULT_MODE = "economy"
SYSTEM_PRESETS: dict[str, Assignments] = {
    "economy": {},
    "quality": {
        ROLE_CEO: DEEPSEEK_V4_PRO,
        ROLE_WORKER: DEEPSEEK_V4_PRO,
    },
}


def _clamp_to_ceiling(assignments: Assignments, ceiling: frozenset[str]) -> Assignments:
    return {
        role: model
        for role, model in assignments.items()
        if role in CONFIGURABLE_ROLES and model in ceiling
    }


def _base_model() -> str:
    """被评基座模型：``EVAL_BASE_MODEL`` 覆盖（对比不同上游模型时用），缺省 Flash。

    有的中转 key 只认自家模型名（如 ``glm-5.2``），发 ``deepseek-v4-flash`` 直接 403 ——
    对比评测须能把 team 路径的基座名切到该 key 认的名字（D3 授权的可配化）。
    """
    return os.environ.get("EVAL_BASE_MODEL", "").strip() or DEEPSEEK_V4_FLASH


def build_profile_set(assignments: Assignments, *, ceiling: frozenset[str]) -> TurnProfiles:
    safe = _clamp_to_ceiling(assignments, ceiling)
    overrides = {ROLE_TO_PROFILE[role]: model for role, model in safe.items()}
    return TurnProfiles(model=_base_model(), model_overrides=overrides)


def resolve_assignments(
    mode_ref: str | None, *, custom_modes: dict[str, Assignments]
) -> Assignments:
    if not mode_ref:
        return SYSTEM_PRESETS[SYSTEM_DEFAULT_MODE]
    if mode_ref in SYSTEM_PRESETS:
        return SYSTEM_PRESETS[mode_ref]
    if mode_ref in custom_modes:
        return custom_modes[mode_ref]
    return SYSTEM_PRESETS[SYSTEM_DEFAULT_MODE]


def resolve_profile_set(
    mode_ref: str | None,
    *,
    custom_modes: dict[str, Assignments],
    ceiling: frozenset[str],
) -> TurnProfiles:
    return build_profile_set(
        resolve_assignments(mode_ref, custom_modes=custom_modes), ceiling=ceiling
    )

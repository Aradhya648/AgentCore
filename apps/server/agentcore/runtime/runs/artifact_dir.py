"""案卷 ``artifact_dir``：布局常量 → 委派交付默认目录 + 验收前缀。

工作区布局事实见 ``workspace_context``；本模块只在 ``form=files`` /
``requires_files`` / 已声明 ``artifacts`` 且语义为案卷时，按 ``stage_dirs``
填默认落盘目录。Worker 只定文件名；契约验收复用 ``artifacts`` 目录前缀闸。

不做：``file_write`` 启发式改写、根目录搬迁、``playbook=none`` 特例。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentcore.workspace.stage_dirs import (
    DEBATE_DIR,
    DOCS_PREFIX,
    RESEARCH_DIR,
    REVIEWS_DIR,
)

if TYPE_CHECKING:
    from agentcore.runtime.runs.types import Deliverable, RunSpec

_STAGE_DIRS = (RESEARCH_DIR, DEBATE_DIR, REVIEWS_DIR)

# 案卷语义（讨论 / 调研 / 审查）；与 WC 边界句同一产品口径，非写盘启发式。
_DOSSIER_SEMANTIC = re.compile(
    r"调研|研究|竞品|审查|质检|评审|讨论|笔记|案卷|透镜|"
    r"research|dossier|(?<![a-zA-Z])review(?![a-zA-Z])",
    re.IGNORECASE,
)
_REVIEW_SEMANTIC = re.compile(
    r"审查|质检|评审|(?<![a-zA-Z])review(?![a-zA-Z])",
    re.IGNORECASE,
)


def normalize_artifact_dir(path: str) -> str:
    """Workspace-relative POSIX dir without trailing slash."""
    return path.replace("\\", "/").strip().lstrip("./").rstrip("/")


def stage_dir_covering(path: str) -> str:
    """Return the stage dir that covers ``path``, or ``\"\"``."""
    p = normalize_artifact_dir(path)
    if not p:
        return ""
    for d in _STAGE_DIRS:
        if p == d or p.startswith(f"{d}/"):
            return d
    return ""


def _looks_like_business_artifact(path: str) -> bool:
    """True when path has a non-dossier directory structure (e.g. ``site/index.html``)."""
    p = normalize_artifact_dir(path)
    if not p or "/" not in p:
        return False
    return not (p == DOCS_PREFIX or p.startswith(f"{DOCS_PREFIX}/"))


def _is_dossier_semantic(role: str, task: str, name: str = "") -> bool:
    text = f"{role}\n{task}\n{name}"
    return bool(_DOSSIER_SEMANTIC.search(text))


def _default_stage_dir(role: str, task: str, name: str = "") -> str:
    text = f"{role}\n{task}\n{name}"
    if _REVIEW_SEMANTIC.search(text):
        return REVIEWS_DIR
    return RESEARCH_DIR


def resolve_artifact_dir(
    deliverable: Deliverable,
    *,
    role: str = "",
    task: str = "",
) -> str:
    """Resolve the dossier dir for a file deliverable, or ``\"\"`` when not applicable."""
    if deliverable.form == "prose":
        return ""
    fileish = (
        deliverable.form == "files"
        or deliverable.requires_files
        or bool(deliverable.artifacts)
    )
    if not fileish:
        return ""

    explicit = normalize_artifact_dir(deliverable.artifact_dir)
    if explicit:
        return explicit

    for pattern in deliverable.artifacts:
        covered = stage_dir_covering(pattern)
        if covered:
            return covered

    if any(_looks_like_business_artifact(a) for a in deliverable.artifacts):
        return ""

    if not _is_dossier_semantic(role, task, deliverable.name):
        return ""

    return _default_stage_dir(role, task, deliverable.name)


def apply_artifact_dir_defaults(deliverable: Deliverable, *, role: str, task: str) -> None:
    """Fill ``artifact_dir`` and ensure acceptance covers that prefix (in-place)."""
    resolved = resolve_artifact_dir(deliverable, role=role, task=task)
    if not resolved:
        return

    deliverable.artifact_dir = resolved
    deliverable.requires_files = True
    prefix = f"{resolved}/"

    if not deliverable.artifacts:
        deliverable.artifacts = [prefix]
        return

    relocated: list[str] = []
    for raw in deliverable.artifacts:
        norm = normalize_artifact_dir(raw)
        if not norm:
            continue
        if "/" not in norm:
            relocated.append(f"{resolved}/{norm}")
        else:
            relocated.append(norm)
    deliverable.artifacts = relocated or [prefix]


def apply_artifact_dir_to_spec(spec: RunSpec) -> None:
    """Apply dossier ``artifact_dir`` defaults to one plan node (in-place)."""
    if spec.deliverable is None:
        return
    apply_artifact_dir_defaults(spec.deliverable, role=spec.role, task=spec.task)


def apply_artifact_dir_to_specs(specs: list[RunSpec]) -> None:
    for spec in specs:
        apply_artifact_dir_to_spec(spec)


def apply_artifact_dir_to_plan(plan: object) -> None:
    nodes = getattr(plan, "nodes", None) or []
    apply_artifact_dir_to_specs(list(nodes))


__all__ = [
    "apply_artifact_dir_defaults",
    "apply_artifact_dir_to_plan",
    "apply_artifact_dir_to_spec",
    "apply_artifact_dir_to_specs",
    "normalize_artifact_dir",
    "resolve_artifact_dir",
    "stage_dir_covering",
]

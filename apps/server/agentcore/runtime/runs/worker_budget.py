"""派单时为 worker 回填统一 token 顶与墙钟超时 backstop.

全局 ``engine_worker_token_ceiling``（默认 600k）与统一墙钟 600s 是防失控安全阀，
**不做**按任务规格的四档启发式分档。CEO 显式 ``timeout_ms`` / 预置 ``token_ceiling``
恒优先（已写入则不动）。

共享谓词（``is_research_root`` / ``is_deep_deliverable`` 等）仍供检索预算、定向检索
工具面、delegate 复杂度改写复用——与本模块的统一 backstop 回填正交。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import Deliverable, RunSpec

__all__ = [
    "DIRECTED_SEARCH_DISCIPLINE",
    "DIRECTED_SEARCH_TOOL_NAMES",
    "WORKER_TIMEOUT_BACKSTOP_S",
    "apply_directed_search_tools",
    "apply_directed_search_tools_to_specs",
    "apply_worker_budgets",
    "apply_worker_budgets_to_specs",
    "ensure_directed_search_tools",
    "is_deep_deliverable",
    "is_directed_search_role",
    "is_research_root",
]

# 统一墙钟 backstop（原 deep 档值）；CEO 显式 timeout_ms 恒优先。
WORKER_TIMEOUT_BACKSTOP_S = 600

# 审查 / 调查类 worker：定向检索工具（复用现有 grep / code_search，不新造）。
# CEO 若手搓 least-privilege 成 ``file_list``+``file_read``，builder 会补回这些工具，
# 避免整文件通读烧穿 token（真实 trace：4-worker 代码审查 51×file_read、零 grep）。
DIRECTED_SEARCH_TOOL_NAMES: frozenset[str] = frozenset({"grep", "code_search"})

DIRECTED_SEARCH_DISCIPLINE = (
    "【检索纪律】概念/意图先用 code_search，精确符号或字符串用 grep；"
    "命中后再 file_read（优先 offset/limit）；禁止无目标地整目录逐文件通读。"
)

# 角色名宽匹配：审查 / 调查 / 质检 / 审校 / review / audit …
# 只影响工具面与检索纪律，不改变 token / 超时 backstop。
_DIRECTED_SEARCH_ROLE_MARKERS: tuple[str, ...] = (
    "审校",
    "审查",
    "质检",
    "评审",
    "调查",
    "调研",
    "review",
    "audit",
    "investigate",
    "inspector",
    "survey",
)

# 成篇门槛：派单时已知的 min_length（字）。≥ 此值视作成篇报告信号。
_LONG_FORM_MIN_LENGTH = 3_000


def is_deep_deliverable(deliverable: Deliverable | None) -> bool:
    """True when dispatch-time deliverable signals a deep / long-form file report."""
    if deliverable is None:
        return False
    if deliverable.requires_files:
        return True
    if deliverable.form == "files":
        return True
    if deliverable.artifacts:
        return True
    return deliverable.min_length >= _LONG_FORM_MIN_LENGTH


def is_directed_search_role(role: str) -> bool:
    """True when the role should get grep/code_search + 检索纪律（审查 / 调查类）.

    Covers 审查官 / 质检 / 调研员 / 审校 etc. Does **not** change token or timeout
    backstop; only tool-surface enrichment and prompt discipline.
    """
    r = (role or "").strip().lower()
    if not r:
        return False
    return any(marker in r for marker in _DIRECTED_SEARCH_ROLE_MARKERS)


def ensure_directed_search_tools(
    tools: list[str] | None,
    *,
    role: str,
    valid_tools: set[str] | None,
) -> list[str] | None:
    """Ensure review/investigation allow-lists include grep/code_search when available.

    ``None`` (unrestricted) is left alone — the worker registry already offers them.
    Explicit least-privilege lists that omit directed search get them appended when
    present in ``valid_tools`` (or unconditionally when ``valid_tools`` is unknown).
    """
    if not is_directed_search_role(role):
        return tools
    extras = [
        name
        for name in sorted(DIRECTED_SEARCH_TOOL_NAMES)
        if valid_tools is None or name in valid_tools
    ]
    if not extras:
        return tools
    if tools is None:
        return None
    merged = list(tools)
    for name in extras:
        if name not in merged:
            merged.append(name)
    return merged


def apply_directed_search_tools(
    plan: RunPlan,
    *,
    valid_tools: set[str] | None = None,
) -> None:
    """Stamp directed-search tools onto review/investigation nodes (in place)."""
    apply_directed_search_tools_to_specs(plan.nodes, valid_tools=valid_tools)


def apply_directed_search_tools_to_specs(
    specs: list[RunSpec],
    *,
    valid_tools: set[str] | None = None,
) -> None:
    """Same as :func:`apply_directed_search_tools` for a replan ``add`` batch."""
    for spec in specs:
        spec.tools = ensure_directed_search_tools(
            spec.tools, role=spec.role, valid_tools=valid_tools
        )


def is_research_root(
    complexity_hint: str,
    deliverable: Deliverable | None,
    *,
    has_upstream: bool,
    retrieval_budget: int | None,
) -> bool:
    """True when a dispatch is a research-wave root (for retrieval budget defaults).

    调研波 root 判据：无上游依赖（``has_upstream`` 为 False）+ 检索预算非显式 0 +
    ``complexity_hint`` ≠ light。落盘深研（:func:`is_deep_deliverable`）两头信号都有时
    排除——检索默认仍走 ROOT 额度而非 research 额度。

    ``retrieval_budget`` 取**解析后**的值（检索预算在 worker 预算之前应用）：无上游节点的结构化
    默认恒 > 0，故解析值为 0 只可能来自 CEO 显式 0 → 判非研究 root；``None``（尚未填默认）视作未
    显式关 0、仍可命中——供 :mod:`~agentcore.runtime.runs.retrieval_budget` 在填默认前复用同一
    判据（单一判据、两模块共用，避免漂移）。
    """
    if complexity_hint == "light":
        return False
    if has_upstream:
        return False
    if retrieval_budget == 0:
        return False
    return not is_deep_deliverable(deliverable)


def apply_worker_budgets(
    plan: RunPlan,
    *,
    default_token_ceiling: int | None = None,
) -> None:
    """Stamp unified ``token_ceiling`` / ``policy.timeout_s`` backstop on every node."""
    apply_worker_budgets_to_specs(
        plan.nodes,
        default_token_ceiling=default_token_ceiling,
    )


def apply_worker_budgets_to_specs(
    specs: list[RunSpec],
    *,
    default_token_ceiling: int | None = None,
) -> None:
    """Same as :func:`apply_worker_budgets` for a replan ``add`` batch."""
    ceiling = (
        default_token_ceiling
        if default_token_ceiling is not None and default_token_ceiling > 0
        else _settings_default_token_ceiling()
    )
    for spec in specs:
        if spec.token_ceiling is None:
            spec.token_ceiling = ceiling
        # CEO 显式 timeout_ms → builder 已写入 timeout_s；未声明时填统一 backstop。
        if spec.policy.timeout_s is None:
            spec.policy.timeout_s = WORKER_TIMEOUT_BACKSTOP_S


def _settings_default_token_ceiling() -> int:
    try:
        from agentcore.config import settings

        ceiling = int(settings.engine_worker_token_ceiling)
        if ceiling > 0:
            return ceiling
    except Exception:  # noqa: BLE001 — settings optional in unit stubs
        pass
    return 600_000

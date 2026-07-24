"""Plan-time retrieval budget (检索与交付约束前置提案 A1).

Structured defaults on ``RunSpec.retrieval_budget`` + strip search tools when the
resolved limit is 0. Runtime counter lives on ``ToolContext.retrieval_budget``
(:class:`~agentcore.tools.protocol.RetrievalBudgetState`); enforce in
``tool_exec`` (orthogonal to LoopController / team_gate). Cache hits and A3
query-contract rejects do not consume budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.runtime.runs.worker_budget import is_research_root
from agentcore.tools.protocol import RetrievalBudgetState

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec
    from agentcore.tools.protocol import ToolResult

__all__ = [
    "BUDGET_EXHAUSTED_FEEDBACK",
    "DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER",
    "DEFAULT_RETRIEVAL_BUDGET_DOWNSTREAM",
    "DEFAULT_RETRIEVAL_BUDGET_LENS_BASE",
    "DEFAULT_RETRIEVAL_BUDGET_LENS_GAP",
    "DEFAULT_RETRIEVAL_BUDGET_RESEARCH",
    "DEFAULT_RETRIEVAL_BUDGET_ROOT",
    "RETRIEVAL_BUDGET_CRITICAL_REMAINING",
    "RETRIEVAL_TOOL_NAMES",
    "RetrievalBudgetState",
    "apply_retrieval_budgets",
    "apply_retrieval_budgets_to_specs",
    "budget_exhausted_output",
    "charges_retrieval_budget",
    "default_retrieval_budget",
    "exclude_retrieval_tools",
    "format_retrieval_budget_critical_prompt",
    "format_retrieval_budget_line",
    "is_retrieval_budget_critical",
    "parse_retrieval_budget",
    "rework_refill_slots",
]

# Tools that share one per-run retrieval budget (web_search + read_url combined).
RETRIEVAL_TOOL_NAMES: frozenset[str] = frozenset({"web_search", "read_url"})

# Structured defaults — conservative starters; 待 A6 观测校准 (提案 §六).
DEFAULT_RETRIEVAL_BUDGET_ROOT = 8  # 无上游依赖（light / 落盘深研 root）
# research 档 root：无上游 + 非 light + 非落盘深研 + 检索未显式关 0（判据见
# worker_budget.is_research_root）。深读姿态修正后 read_url 与 web_search 共池——原 10 偏紧
# （合成事故 90456883… 研究员 8 次耗尽；真实 legal research_report 亦见检索槽被扇出烧尽）。
# 标定 14（参考区间 12–16 中上）：多给 2–4 次深读核对原文，仍远低于无上限。**待观测校准**
# （开发期无真实产线数据，数值为基于该 trace 的假设标定，不做任何自动校准逻辑）。
DEFAULT_RETRIEVAL_BUDGET_RESEARCH = 14  # 无上游调研波 root（替代 ROOT=8）
# 有上游且非 prose 合成波（含 research_report 审校）：原 3 偏紧——审校核对关键法条 /
# 判例原文常需数次 read_url。标定 5，与透镜缺口档对齐上调。
DEFAULT_RETRIEVAL_BUDGET_DOWNSTREAM = 5
# 多视角透镜：底料负责人 vs 缺口透镜（playbook 显式写入 retrieval_budget）。
DEFAULT_RETRIEVAL_BUDGET_LENS_BASE = 6  # 首透镜·公共底料负责人（稍高于缺口透镜）
DEFAULT_RETRIEVAL_BUDGET_LENS_GAP = 5  # 其余透镜·独有缺口（对齐下游默认）
# 辩手有幕1 案卷时：案卷已覆盖底料，只留残搜槽位补漏。原 4（ROOT/2）→ 2026-07-22 复测：
# 案卷充分时残搜 3 次几乎全是噪声域名，正文引用几乎全来自案卷 → 校准为 2。无案卷路径不动。
DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER = 2

# 同轮超订缓解：剩余槽位 ≤ 此值时经 reflection 注入提前告知，避免当轮 fan-out 超订被挡回。
RETRIEVAL_BUDGET_CRITICAL_REMAINING = 2

BUDGET_EXHAUSTED_FEEDBACK = (
    "检索预算已尽：请基于证据台账中现有材料交付，并在交接（handoff）中如实标注检索缺口"
    "（缺什么、为何没补上）。不要再调用 web_search / read_url。"
    "主管可用 continue_from_run_id 带现场续派并显式提高 retrieval_budget。"
)


def parse_retrieval_budget(raw: Any) -> int | None:
    """CEO-explicit ``retrieval_budget``; ``None`` = omit → structured default later."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, float) and raw >= 0 and raw == int(raw):
        return int(raw)
    return None


def default_retrieval_budget(spec: RunSpec, *, complexity_hint: str = "standard") -> int:
    """Structured default from DAG shape + deliverable.form — never role strings.

    无上游调研波 root（:func:`~agentcore.runtime.runs.worker_budget.is_research_root`）给
    research 额度；其余无上游 root（light / 落盘深研）仍给 ROOT；下游按 form 收紧。
    ``complexity_hint`` 由 :func:`apply_retrieval_budgets` 从派单批级透传——与
    worker_budget 共用同一 :func:`is_research_root`，两模块不漂移。
    """
    has_upstream = bool(spec.depends_on)
    form = spec.deliverable.form if spec.deliverable is not None else None
    if is_research_root(
        complexity_hint,
        spec.deliverable,
        has_upstream=has_upstream,
        retrieval_budget=spec.retrieval_budget,
    ):
        return DEFAULT_RETRIEVAL_BUDGET_RESEARCH
    if not has_upstream:
        return DEFAULT_RETRIEVAL_BUDGET_ROOT
    if form == "prose":
        return 0
    return DEFAULT_RETRIEVAL_BUDGET_DOWNSTREAM


def exclude_retrieval_tools(
    tools: list[str] | None,
    valid_tools: set[str] | None,
) -> list[str] | None:
    """Remove web_search/read_url from an allow-list (预算 0 → 不装配检索工具).

    Unrestricted (``None``) becomes an explicit list of ``valid_tools`` minus
    retrieval tools when ``valid_tools`` is known. Returns ``[]`` (not ``None``)
    when the stripped set is empty — unlike builder._tools, empty here means
    "no tools from the declared set" so the engine does not re-open all tools;
    escalate / notes are re-granted later by the executor.
    """
    if tools is not None:
        return [t for t in tools if t not in RETRIEVAL_TOOL_NAMES]
    if valid_tools is not None:
        return sorted(valid_tools - RETRIEVAL_TOOL_NAMES)
    return None


def apply_retrieval_budgets(
    plan: RunPlan,
    *,
    valid_tools: set[str] | None = None,
    complexity_hint: str = "standard",
) -> None:
    """Resolve budgets on every node (CEO explicit wins) and strip tools when 0."""
    for spec in plan.nodes:
        _apply_one(spec, valid_tools=valid_tools, complexity_hint=complexity_hint)


def apply_retrieval_budgets_to_specs(
    specs: list[RunSpec],
    *,
    valid_tools: set[str] | None = None,
    complexity_hint: str = "standard",
) -> None:
    """Same as :func:`apply_retrieval_budgets` for a replan ``add`` batch."""
    for spec in specs:
        _apply_one(spec, valid_tools=valid_tools, complexity_hint=complexity_hint)


def _apply_one(
    spec: RunSpec, *, valid_tools: set[str] | None, complexity_hint: str = "standard"
) -> None:
    if spec.retrieval_budget is None:
        spec.retrieval_budget = default_retrieval_budget(spec, complexity_hint=complexity_hint)
    if spec.retrieval_budget == 0:
        # 复用 tasks[].tools 白名单：预算 0 → 不装配检索工具。
        stripped = exclude_retrieval_tools(spec.tools, valid_tools)
        if stripped is not None:
            spec.tools = stripped


def format_retrieval_budget_line(budget: int | None) -> str:
    """Worker-facing one-liner for the deliverable / context block."""
    if budget is None:
        return ""
    if budget <= 0:
        return (
            "- 检索预算：0（本任务不装配 web_search / read_url；"
            "基于上游与台账现有证据交付，缺口在交接中标注）"
        )
    return (
        f"- 检索预算：本 run 合计最多 {budget} 次 web_search/read_url"
        "（缓存命中不计）；用尽后基于台账现有证据交付并在交接中标注检索缺口。"
        "续派请主管用 continue_from_run_id 并显式提高 retrieval_budget"
    )


def is_retrieval_budget_critical(remaining: int, *, limit: int) -> bool:
    """True when budget is still open but remaining slots are critically low.

    Used by the engine to inject a one-shot reflection before the next think round,
    so the model does not fan out more ``web_search``/``read_url`` calls than slots left.
    Exhausted (``remaining <= 0``) is handled by wind_down, not this path.
    """
    if limit <= 0:
        return False
    return 0 < remaining <= RETRIEVAL_BUDGET_CRITICAL_REMAINING


def format_retrieval_budget_critical_prompt(*, remaining: int, limit: int) -> str:
    """``[系统提示]`` steer when retrieval slots are critically low (同轮超订缓解)."""
    return (
        f"[系统提示] 检索预算仅剩 {remaining} 次（本 run 上限 {limit} 次 "
        "web_search/read_url，缓存命中不计）。下一轮请只发起不超过剩余次数的检索调用，"
        "优先深读最关键来源；勿并行扇出超过剩余槽位的查询——超订会被挡回并浪费本轮。"
        "若现有证据已够，请直接基于台账交付并在交接中标注检索缺口。"
    )


def rework_refill_slots(
    *,
    original_limit: int,
    wind_down_entered: bool,
) -> int:
    """How many retrieval slots a contract rework may add (预算语义不绕过).

    - After token / timeout wind_down: **0** — rework must not restore investigation.
    - Otherwise: half the original resolved budget (min 1), same slice size as before.
    Caller must apply via :meth:`RetrievalBudgetState.refill_within_cap` with
    ``cap=original_limit`` so the absolute ceiling never grows past the plan-time
    budget (unlike unbounded :meth:`~RetrievalBudgetState.refill`).
    """
    if wind_down_entered or original_limit <= 0:
        return 0
    return max(1, int(original_limit) // 2)


def charges_retrieval_budget(result: ToolResult) -> bool:
    """True when a completed retrieval call should consume one budget slot.

    Cache hits (``metadata.cached``) do not charge. Failures (including A3 query
    contract rejects) do not charge — they never produced a live backend hit worth
    counting, and A3 must remain free to rewrite (提案 A3).
    """
    if not result.success:
        return False
    meta = result.metadata or {}
    return not meta.get("cached")


def budget_exhausted_output() -> str:
    return BUDGET_EXHAUSTED_FEEDBACK

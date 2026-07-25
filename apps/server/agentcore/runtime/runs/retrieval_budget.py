"""Plan-time retrieval budget (检索与交付约束前置提案 A1).

Structured defaults on ``RunSpec.retrieval_budget`` + strip search tools when the
resolved limit is 0. Runtime counter lives on ``ToolContext.retrieval_budget``
(:class:`~agentcore.tools.protocol.RetrievalBudgetState`); enforce in
``tool_exec`` (orthogonal to LoopController / team_gate). Cache hits and A3
query-contract rejects do not consume budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.tools.protocol import RetrievalBudgetState

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec
    from agentcore.tools.protocol import ToolResult

__all__ = [
    "BUDGET_EXHAUSTED_FEEDBACK",
    "DEFAULT_RETRIEVAL_BUDGET",
    "DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER",
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

# 统一默认：任意非 prose、且 CEO 未显式声明的 worker → 14。
# 开发期无真实产线数据，14 为假设统一阀（原 RESEARCH 档复用；已删 ROOT/DOWNSTREAM
# 与透镜 base/gap 分档）。不做批级共享池 / 按 worker 数缩放——接受 N×线性税。
DEFAULT_RETRIEVAL_BUDGET = 14
# 辩手有幕1 案卷时：案卷已覆盖底料，只留残搜槽位补漏。原 4 → 2026-07-22 复测：
# 案卷充分时残搜 3 次几乎全是噪声域名，正文引用几乎全来自案卷 → 校准为 2。
# 窄硬例外（对齐 prose 式硬规则），不是结构猜档。无案卷路径不动。
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
    """Structured default — unified single value + hard exceptions; never role strings.

    - ``form=prose`` → 0（剥离检索工具由 :func:`_apply_one` 完成）
    - 其余 → :data:`DEFAULT_RETRIEVAL_BUDGET`（14）

    CEO / schema 显式 ``retrieval_budget`` 由调用方在填默认前保留，不经本函数。
    ``complexity_hint`` 保留签名兼容，**不再**参与分档（``is_research_root`` 亦不参与）。
    """
    del complexity_hint  # API compat only; no tiering
    form = spec.deliverable.form if spec.deliverable is not None else None
    if form == "prose":
        return 0
    return DEFAULT_RETRIEVAL_BUDGET


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

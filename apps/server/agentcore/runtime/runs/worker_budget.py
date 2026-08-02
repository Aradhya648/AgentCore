"""派单时为 worker 回填统一 token 顶与墙钟超时 backstop.

全局 ``engine_worker_token_ceiling``（默认 4M）与统一墙钟 1200s 是防失控安全阀，
**不做**按任务规格的四档启发式分档。CEO 显式 ``timeout_ms`` / 预置 ``token_ceiling``
恒优先（已写入则不动）。

共享谓词（``is_research_root`` / ``is_deep_deliverable`` 等）仍供定向检索工具面、
delegate 复杂度改写等复用——与本模块的统一 token/超时 backstop 回填正交。
检索预算已改为统一单值默认，不再经 ``is_research_root`` 分档。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import Deliverable, RunSpec

__all__ = [
    "DIRECTED_SEARCH_DISCIPLINE",
    "DIRECTED_SEARCH_TOOL_NAMES",
    "LIGHT_REPAIR_MAX_ROUNDS",
    "VERIFY_POLICY_INNER",
    "VERIFY_POLICY_OUTER",
    "VERIFY_INNER_DISCIPLINE",
    "WORKER_TIMEOUT_BACKSTOP_S",
    "apply_directed_search_tools",
    "apply_directed_search_tools_to_specs",
    "apply_light_round_budgets",
    "apply_verify_policies",
    "apply_verify_policies_to_specs",
    "apply_worker_budgets",
    "apply_worker_budgets_to_specs",
    "blocks_light_complexity",
    "ensure_directed_search_tools",
    "is_deep_deliverable",
    "is_directed_search_role",
    "is_outer_verify_role",
    "is_research_root",
    "is_short_write_posture",
    "resolve_prose_idle_finalize_rounds",
    "should_enable_prose_idle",
    "should_enable_zero_write",
    "should_tighten_verify_exec_thrash",
]

# 统一墙钟 backstop；CEO 显式 timeout_ms 恒优先。
WORKER_TIMEOUT_BACKSTOP_S = 1200

# Short ReAct ceiling constant (repair_code playbook / CEO explicit caps).
# ``complexity_hint=light`` no longer stamps this — see :func:`apply_light_round_budgets`.
# Distinct from contract ``light_repair`` (format-only pass inside executor_node).
LIGHT_REPAIR_MAX_ROUNDS = 6

# 审查 / 调查类 worker：定向检索工具（复用现有 grep / code_search，不新造）。
# 真纯丙后执行层忽略 tasks[].tools 收窄；本集合仍供审查角色提示纪律与兼容补回。
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

# verify_policy：调查/审查默认 inner；验收/外环角色不自动打标。
VERIFY_POLICY_INNER = "inner"
VERIFY_POLICY_OUTER = "outer"
VERIFY_INNER_DISCIPLINE = (
    "【验证范围】本队员为调查/审查姿态（verify_policy=inner）："
    "禁止全仓 typecheck / build / `tsc -b`（勿用 test_run 烧分钟级预算「再确认」）。"
    "修码自检用内环 code_diagnostics；运行时 blank-page / 挂载问题优先 browser 与入口链路阅读；"
    "外环全量验绿请 escalate 或交验收员。"
)
_OUTER_VERIFY_ROLE_MARKERS: tuple[str, ...] = (
    "验收",
    "验证员",
    "外环",
    "verify",
    "acceptance",
    "typecheck",
    "qa lead",
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


def blocks_light_complexity(deliverable: Deliverable | None) -> bool:
    """True when deliverable must not keep ``complexity_hint=light``.

    Long-form research (min_length ≥ 3k) still blocks light. File landing alone
    (``requires_files`` / ``form=files`` / ``artifacts``) does **not** — repair /
    single-file runtime fixes may be light + requires_files.
    """
    if deliverable is None:
        return False
    return deliverable.min_length >= _LONG_FORM_MIN_LENGTH


def apply_light_round_budgets(
    plan: RunPlan,
    *,
    complexity_hint: str,
) -> None:
    """Retired no-op: ``complexity_hint=light`` no longer stamps short ``max_rounds``.

    Kept (and still called from builder) to avoid a large call-site move. Short
    round caps remain via CEO explicit ``max_rounds`` and ``repair_code`` playbook
    builders — not via light posture.
    """
    _ = (plan, complexity_hint)


def is_short_write_posture(*, max_rounds: int | None) -> bool:
    """True when a short round budget is stamped (CEO explicit / repair_code).

    ``complexity_hint=light`` no longer stamps ``max_rounds``. ``repair_code``
    playbook builders and CEO-declared caps still can. Standard workers leave
    ``max_rounds=None`` (profile default) — not short-write posture.
    """
    return max_rounds is not None and max_rounds > 0


def should_enable_zero_write(
    *,
    files_expected: bool,
    short_write_posture: bool | None = None,
    max_rounds: int | None = None,
    form_prose: bool = False,
) -> bool:
    """Files zero-write催写 — **retired** (always off).

    Product: do not nudge/finalize solely because landing files are still zero
    after N investigation rounds (standard or short/light). Delivery pressure
    stays on round/token ceilings + user stop. 真纯丙后不再有「白名单缺写盘 →
    补写工具」半成品路径。

    Call-site kwargs retained for compatibility. Prose idle ladder is also retired
    (:func:`should_enable_prose_idle` always false).
    """
    _ = (files_expected, short_write_posture, max_rounds, form_prose)
    return False


def should_enable_prose_idle(
    *,
    files_expected: bool,
    short_write_posture: bool | None = None,
    max_rounds: int | None = None,
) -> bool:
    """Prose short-budget idle ladder — **retired** (always off).

    Formerly: short-stamped prose workers (diagnose/verify) shared the zero_write
    warn→FINALIZE counter with handoff as delivery. Mid-loop DEGRADED from idle
    reads is gone; hard ceilings + convergence spin remain. Kwargs kept for
    call-site compatibility.
    """
    _ = (files_expected, short_write_posture, max_rounds)
    return False


def resolve_prose_idle_finalize_rounds(max_rounds: int | None) -> int:
    """Retired helper: prose idle bar derivation (always 0 with default settings).

    Kept for tests/compat; ``create_loop_controller`` no longer enables the ladder.
    """
    from agentcore.config import settings

    _ = max_rounds
    base = max(0, int(settings.engine_zero_write_finalize_rounds))
    if base <= 0:
        return 0
    # settings override only — production default is 0 (ladder retired).
    if max_rounds is not None and max_rounds > 0:
        return max(2, min(base, max_rounds - 1))
    return max(2, min(base, 4))


def should_tighten_verify_exec_thrash(
    *,
    short_write_posture: bool,
    files_expected: bool,
    has_execution_tools: bool,
) -> bool:
    """Repair verify short posture: tighten unproductive / tool-failure ladders.

    Applies when the worker is short-budget (CEO / repair_code stamped max_rounds),
    holds execution tools, and is **not** a files-landing node (verify / diagnose
    prose). Reuses LoopController repeated-failure / circuit-breaker / unproductive
    paths — does **not** add a parallel fuse. Files short-write nodes no longer use
    zero-write催写 (retired); they still skip this verify tighten path.
    """
    return bool(
        short_write_posture and has_execution_tools and not files_expected
    )


def is_directed_search_role(role: str) -> bool:
    """True when the role should get grep/code_search + 检索纪律（审查 / 调查类）.

    Covers 审查官 / 质检 / 调研员 / 审校 etc. Does **not** change token or timeout
    backstop; only tool-surface enrichment and prompt discipline.
    """
    r = (role or "").strip().lower()
    if not r:
        return False
    return any(marker in r for marker in _DIRECTED_SEARCH_ROLE_MARKERS)


def is_outer_verify_role(role: str) -> bool:
    """True when the role is acceptance / outer-loop verify (do not auto-stamp inner)."""
    r = (role or "").strip().lower()
    if not r:
        return False
    return any(marker in r for marker in _OUTER_VERIFY_ROLE_MARKERS)


def apply_verify_policies(plan: RunPlan) -> None:
    """Stamp ``verify_policy=inner`` on review/investigation seats (unless explicit)."""
    apply_verify_policies_to_specs(plan.nodes)


def apply_verify_policies_to_specs(specs: list[RunSpec]) -> None:
    """Same as :func:`apply_verify_policies` for a replan ``add`` batch."""
    for spec in specs:
        raw = (spec.verify_policy or "").strip().lower()
        if raw in (VERIFY_POLICY_INNER, VERIFY_POLICY_OUTER):
            spec.verify_policy = raw
            continue
        if is_outer_verify_role(spec.role):
            continue
        if is_directed_search_role(spec.role):
            spec.verify_policy = VERIFY_POLICY_INNER


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
    """True when a dispatch is a research-wave root (结构谓词，供别用).

    调研波 root 判据：无上游依赖（``has_upstream`` 为 False）+ 检索预算非显式 0 +
    ``complexity_hint`` ≠ light。落盘深研（:func:`is_deep_deliverable`）排除。

    **不再**参与检索预算默认分档（检索已统一为单值 + 硬例外）。
    ``retrieval_budget`` 取解析后值：显式 0 → 判非研究 root；``None`` 视作未显式关 0。
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
    return 4_000_000

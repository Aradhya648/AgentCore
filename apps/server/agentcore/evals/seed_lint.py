"""种子用例静态校验（评估体系 §五 / §八 零 LLM 自测）.

纯结构检查，不跑模型：必填字段、枚举合法、引用的 check 名已注册、samples≥1 等。
用于 per-PR 硬门禁（用例写错立刻挂），也被 loader 复用以早失败。
"""

from __future__ import annotations

from typing import Any

from agentcore.evals.checks import CHECK_NAMES
from agentcore.evals.mast import MAST_CODES
from agentcore.evals.prompt_profiles import PROFILE_NAMES

_CATEGORIES = {"qa", "retrieval", "team", "tool_use", "no_fabrication", "routing"}
_PATHS = {"single", "team"}
_TOOLSETS = {"ceo", "worker"}
_REQUIRED = ("id", "category", "user_message")
_EXPECTED_SHAPE_KEYS = frozenset(
    {
        "min_workers",
        "max_workers",
        "parallel_fanout_min",
        "has_join",
        "pipeline_depth_min",
        "pipeline_edges_min",
        "independent_reviewer",
        "has_nested",
        "min_roles",
        "plan_types",
    }
)


def _lint_milestones(cid: str, raw: dict[str, Any]) -> list[str]:
    """校验 milestone 子目标清单（后端架构.md §五）：结构 + id 唯一 + 权重正 + 阈值合法。

    milestone 非必填；声明了才校验。每条须为 ``{"id", "desc", "weight"?}``，``id`` 用例内唯一、
    ``desc`` 非空、``weight``（缺省 1）须为正数；``milestone_threshold``（缺省 0.8）须在 (0, 1]。
    """
    errors: list[str] = []
    milestones = raw.get("milestones")
    if milestones is None:
        return errors
    if not isinstance(milestones, list):
        return [f"[{cid}] milestones 须为列表"]

    seen: set[str] = set()
    for i, m in enumerate(milestones):
        if not isinstance(m, dict):
            errors.append(f"[{cid}] milestones[{i}] 须为对象")
            continue
        mid = m.get("id")
        if not mid:
            errors.append(f"[{cid}] milestones[{i}] 缺 id")
        elif mid in seen:
            errors.append(f"[{cid}] milestones id 重复: {mid!r}")
        else:
            seen.add(mid)
        if not m.get("desc"):
            errors.append(f"[{cid}] milestones[{mid or i}] 缺 desc（子目标描述）")
        if "weight" in m:
            try:
                if float(m["weight"]) <= 0:
                    errors.append(f"[{cid}] milestones[{mid or i}] weight 须为正数")
            except (TypeError, ValueError):
                errors.append(f"[{cid}] milestones[{mid or i}] weight 须为数值")

    if "milestone_threshold" in raw:
        try:
            t = float(raw["milestone_threshold"])
            if not 0.0 < t <= 1.0:
                errors.append(f"[{cid}] milestone_threshold={t} 须在 (0, 1]")
        except (TypeError, ValueError):
            errors.append(f"[{cid}] milestone_threshold 须为数值")

    return errors


def lint_case(raw: dict[str, Any]) -> list[str]:
    """返回一条用例的所有结构错误（空列表 = 合法）。"""
    errors: list[str] = []
    cid = raw.get("id") or "<no-id>"

    for f in _REQUIRED:
        if not raw.get(f):
            errors.append(f"[{cid}] 缺必填字段 {f!r}")

    category = raw.get("category")
    if category is not None and category not in _CATEGORIES:
        errors.append(f"[{cid}] category={category!r} 非法（须属 {sorted(_CATEGORIES)}）")

    path = raw.get("path", "single")
    if path not in _PATHS:
        errors.append(f"[{cid}] path={path!r} 非法（须属 {sorted(_PATHS)}）")

    toolset = raw.get("toolset", "ceo")
    if toolset not in _TOOLSETS:
        errors.append(f"[{cid}] toolset={toolset!r} 非法（须属 {sorted(_TOOLSETS)}）")

    checks = raw.get("checks", [])
    if not isinstance(checks, list):
        errors.append(f"[{cid}] checks 须为列表")
    else:
        for i, spec in enumerate(checks):
            if not isinstance(spec, dict) or "name" not in spec:
                errors.append(f"[{cid}] checks[{i}] 须为含 name 的对象")
            elif spec["name"] not in CHECK_NAMES:
                errors.append(f"[{cid}] checks[{i}].name={spec['name']!r} 未注册")

    errors.extend(_lint_milestones(cid, raw))

    if not checks and not raw.get("rubric") and not raw.get("milestones"):
        errors.append(f"[{cid}] 既无 checks 也无 rubric / milestones——该用例不会判定任何东西")

    # 路由用例（方向③）：路由准确率聚合器（routing.py）靠声明的 check 当**单一标签源**——
    # Delegated=期望委派、NotDelegated=期望自答，故每条 routing 用例须**恰好声明其一**（标签
    # 唯一），且须走 path="team"（single 路径恒不委派，NotDelegated 会平凡通过、Delegated 不
    # 可能成立，度量失真）。非 routing 类别不受此约束。
    if category == "routing" and isinstance(checks, list):
        names = {s.get("name") for s in checks if isinstance(s, dict)}
        label = names & {"Delegated", "NotDelegated"}
        if len(label) != 1:
            errors.append(
                f"[{cid}] category=routing 须恰好声明 Delegated / NotDelegated 之一"
                f"（路由准确率的标签源），当前={sorted(label)}"
            )
        if path != "team":
            errors.append(f"[{cid}] category=routing 须 path='team'（single 恒不委派、度量失真）")

    try:
        samples = int(raw.get("samples", 1))
        if samples < 1:
            errors.append(f"[{cid}] samples={samples} 须 ≥1")
    except (TypeError, ValueError):
        errors.append(f"[{cid}] samples 须为整数")

    # 方向① 变体注入：声明的 prompt_profile 必须是已注册的变体名（写错立刻挂）。
    profile = raw.get("prompt_profile")
    if profile is not None and profile not in PROFILE_NAMES:
        errors.append(f"[{cid}] prompt_profile={profile!r} 未注册（须属 {sorted(PROFILE_NAMES)}）")

    # 学·度量 §2.5：声明的 MAST 失败标签必须是已注册的 14 类之一（写错码立刻挂，避免聚合时
    # 静默漏标）。非 MAST 套件不挂此字段、平凡通过。
    mast = raw.get("mast")
    if mast is not None and mast not in MAST_CODES:
        errors.append(f"[{cid}] mast={mast!r} 非法（须属 MAST 14 类 {sorted(MAST_CODES)}）")

    # 协作形状（阶段 1）：expected_shape 可选；声明了则键须属已知集合。
    shape = raw.get("expected_shape")
    if shape is not None:
        if not isinstance(shape, dict):
            errors.append(f"[{cid}] expected_shape 须为对象")
        else:
            unknown = set(shape) - _EXPECTED_SHAPE_KEYS
            if unknown:
                errors.append(
                    f"[{cid}] expected_shape 含未知键 {sorted(unknown)}"
                    f"（须属 {sorted(_EXPECTED_SHAPE_KEYS)}）"
                )
            if "plan_types" in shape and not isinstance(shape["plan_types"], list):
                errors.append(f"[{cid}] expected_shape.plan_types 须为列表")

    return errors


def lint_suite(cases: list[dict[str, Any]]) -> list[str]:
    """校验整套用例：逐例结构 + 全局 id 唯一。"""
    errors: list[str] = []
    seen: set[str] = set()
    for raw in cases:
        errors.extend(lint_case(raw))
        cid = raw.get("id")
        if cid:
            if cid in seen:
                errors.append(f"[{cid}] id 重复")
            seen.add(cid)
    return errors


# --- 对比评估用例校验（团队 vs 单体）—— 现状见 docs/02-架构/后端架构.md §五 ---

_ARCHETYPES = {"parallel_research", "debate", "cross_domain", "simple"}
_ARMS = {"single", "team", "matched_single"}
_COMPARISON_REQUIRED = ("id", "archetype", "user_message")


def lint_comparison_case(raw: dict[str, Any]) -> list[str]:
    """返回一条对比用例的所有结构错误（空列表 = 合法）。"""
    errors: list[str] = []
    cid = raw.get("id") or "<no-id>"

    for f in _COMPARISON_REQUIRED:
        if not raw.get(f):
            errors.append(f"[{cid}] 缺必填字段 {f!r}")

    archetype = raw.get("archetype")
    if archetype is not None and archetype not in _ARCHETYPES:
        errors.append(f"[{cid}] archetype={archetype!r} 非法（须属 {sorted(_ARCHETYPES)}）")

    arms = raw.get("arms", ["single", "team"])
    if not isinstance(arms, list) or len(arms) < 2:
        errors.append(f"[{cid}] arms 须为含 ≥2 个臂的列表")
        arms = []
    else:
        for a in arms:
            if a not in _ARMS:
                errors.append(f"[{cid}] arms 含非法臂 {a!r}（须属 {sorted(_ARMS)}）")

    baseline = raw.get("baseline_arm", "single")
    if arms and baseline not in arms:
        errors.append(f"[{cid}] baseline_arm={baseline!r} 不在 arms={arms}")

    # matched_single（等算力单体）的 best-of-N 预算取自 team 的实测 compute，故声明它必须同
    # 时声明 team；通常还应把 baseline_arm 设为 matched_single 才能得到「team vs 等算力单体」。
    if arms and "matched_single" in arms and "team" not in arms:
        errors.append(
            f"[{cid}] arms 含 matched_single 须同时含 team（等算力预算取自 team 实测 compute）"
        )

    toolset = raw.get("toolset", "ceo")
    if toolset not in _TOOLSETS:
        errors.append(f"[{cid}] toolset={toolset!r} 非法（须属 {sorted(_TOOLSETS)}）")

    checks = raw.get("checks", {})
    if not isinstance(checks, dict):
        errors.append(f"[{cid}] checks 须为 {{arm: [check]}} 对象")
        checks = {}
    else:
        for arm, specs in checks.items():
            if arms and arm not in arms:
                errors.append(f"[{cid}] checks 含未声明的臂 {arm!r}")
            if not isinstance(specs, list):
                errors.append(f"[{cid}] checks[{arm!r}] 须为列表")
                continue
            for i, spec in enumerate(specs):
                if not isinstance(spec, dict) or "name" not in spec:
                    errors.append(f"[{cid}] checks[{arm!r}][{i}] 须为含 name 的对象")
                elif spec["name"] not in CHECK_NAMES:
                    errors.append(f"[{cid}] checks[{arm!r}][{i}].name={spec['name']!r} 未注册")

    has_any_check = isinstance(checks, dict) and any(checks.values())
    if not has_any_check and not raw.get("rubric"):
        errors.append(f"[{cid}] 既无 checks 也无 rubric——该用例不会判定任何东西")

    try:
        samples = int(raw.get("samples", 1))
        if samples < 1:
            errors.append(f"[{cid}] samples={samples} 须 ≥1")
    except (TypeError, ValueError):
        errors.append(f"[{cid}] samples 须为整数")

    return errors


def lint_comparison_suite(cases: list[dict[str, Any]]) -> list[str]:
    """校验整套对比用例：逐例结构 + 全局 id 唯一。"""
    errors: list[str] = []
    seen: set[str] = set()
    for raw in cases:
        errors.extend(lint_comparison_case(raw))
        cid = raw.get("id")
        if cid:
            if cid in seen:
                errors.append(f"[{cid}] id 重复")
            seen.add(cid)
    return errors

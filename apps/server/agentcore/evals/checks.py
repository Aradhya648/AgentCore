"""确定性 Check（评估体系 §五）：判定无需 LLM.

每个 Check 从 ``{"name", "args"}`` 规格经 :func:`build_check` 实例化；注册表的键集
（:data:`CHECK_NAMES`）供 ``seed_lint`` 校验用例里引用的 check 名是否存在。
Check 读 :class:`TurnOutcome`，返回 :class:`CheckOutcome`。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentcore.evals.style_lint import style_violations
from agentcore.evals.types import CheckOutcome, EvalCase, TurnOutcome


@dataclass
class FinishReasonCheck:
    """回合正常收口（默认 ``end_turn``，即非 error / max_rounds / degraded / unproductive）。"""

    expected: str = "end_turn"
    name: str = "FinishReason"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        ok = outcome.finish_reason == self.expected
        return CheckOutcome(self.name, ok, f"finish_reason={outcome.finish_reason!r}")


@dataclass
class NonEmptyCheck:
    """回复正文非空、长度达阈值。"""

    min_len: int = 1
    name: str = "NonEmpty"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        n = len((outcome.content or "").strip())
        return CheckOutcome(self.name, n >= self.min_len, f"len={n} (min {self.min_len})")


@dataclass
class ToolCalledCheck:
    """调用了指定工具（按工具名匹配，至少一次）。"""

    tool: str = ""
    name: str = "ToolCalled"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        names = [t[0] for t in outcome.tool_calls]
        ok = self.tool in names
        return CheckOutcome(self.name, ok, f"want {self.tool!r} in {names}")


@dataclass
class ToolArgsValidCheck:
    """指定工具的入参 JSON 合法、且含必填键（``tool`` 为空时校验所有工具调用）。"""

    tool: str | None = None
    required: list[str] = field(default_factory=list)
    name: str = "ToolArgsValid"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        matched = [(n, a) for (n, a) in outcome.tool_calls if self.tool is None or n == self.tool]
        if not matched:
            return CheckOutcome(self.name, False, f"no call to {self.tool!r}")
        for n, raw in matched:
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError as e:
                return CheckOutcome(self.name, False, f"{n}: bad JSON ({e})")
            missing = [k for k in self.required if k not in args]
            if missing:
                return CheckOutcome(self.name, False, f"{n}: missing {missing}")
        return CheckOutcome(self.name, True, f"{len(matched)} call(s) valid")


@dataclass
class ToolArgNonEmptyCheck:
    """指定工具的某次调用，入参 ``arg`` 存在且**非空**（非空 list/str/dict 等真值）。

    比 ``ToolArgsValid.required``（仅查键是否存在）更强：断言「模型不仅填了这个参数、还真
    带了内容」。典型用途是验证 escalate 的结构化 ``questions``——worker 真把【只有用户能定】
    的岔路拆成了选项（而非把键留空 / 给空数组）。任一匹配调用满足即通过。
    """

    tool: str = ""
    arg: str = ""
    name: str = "ToolArgNonEmpty"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        matched = [(n, a) for (n, a) in outcome.tool_calls if n == self.tool]
        if not matched:
            return CheckOutcome(self.name, False, f"no call to {self.tool!r}")
        for n, raw in matched:
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                continue
            if args.get(self.arg):  # truthy ⇒ present & non-empty (空 list/str/dict 为假)
                return CheckOutcome(self.name, True, f"{n}.{self.arg} non-empty")
        return CheckOutcome(self.name, False, f"{self.tool}.{self.arg} empty/missing in all calls")


@dataclass
class HasCitationsCheck:
    """引用数达阈值（检索类用例）。"""

    min_count: int = 1
    name: str = "HasCitations"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        n = len(outcome.citations)
        return CheckOutcome(self.name, n >= self.min_count, f"citations={n} (min {self.min_count})")


@dataclass
class DelegatedCheck:
    """本回合确实委派了团队。"""

    name: str = "Delegated"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        return CheckOutcome(self.name, outcome.delegated, f"delegated={outcome.delegated}")


@dataclass
class NotDelegatedCheck:
    """本回合**没有**委派团队（``DelegatedCheck`` 的护栏逆否）。

    探测「过度编排」——简单问题本该 CEO 直接答，却拆成一支团队，是 Multi-Agent 产品
    最典型的体验/成本灾难。须走 ``path="team"`` 才有意义（``single`` 路径恒不委派、
    断言会平凡通过）；功能套件据此守住「简单问题零编排」这条护栏。
    """

    name: str = "NotDelegated"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        return CheckOutcome(self.name, not outcome.delegated, f"delegated={outcome.delegated}")


@dataclass
class RosterMatchesCheck:
    """实际委派出的角色覆盖期望角色（``roster ⊇ expected``）。"""

    expected: list[str] = field(default_factory=list)
    name: str = "RosterMatches"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        actual = set(outcome.roster)
        missing = [r for r in self.expected if r not in actual]
        ok = not missing
        return CheckOutcome(self.name, ok, f"roster={outcome.roster}, missing={missing}")


@dataclass
class ShapeMatchesCheck:
    """规划 DAG 相对期望形状的匹配分（报告/诊断，不进 L0 门禁）.

    读 ``case.expected_shape``（或 ``args`` 覆盖）+ ``outcome.plan_runs``，经
    ``shape_score.score_shape`` 得 0~1。``passed`` = 分数 ≥ ``threshold``（默认 0.6），但本
    Check 在 ``DIAGNOSTIC_CHECKS`` 中，不计入用例 pass/fail。
    """

    threshold: float = 0.6
    name: str = "ShapeMatches"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        from agentcore.evals.shape_score import score_shape

        expected = case.expected_shape
        result = score_shape(outcome.plan_runs, expected, plan_type=outcome.plan_type)
        ok = result.score >= self.threshold
        return CheckOutcome(
            self.name,
            ok,
            f"score={result.score:.2f} (阈 {self.threshold:.2f}); {result.summary}",
        )


@dataclass
class MaxRoundsCheck:
    """轮数不超过预算（探测空转 / 收敛差）。"""

    budget: int = 16
    name: str = "MaxRounds"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        ok = outcome.rounds <= self.budget
        return CheckOutcome(self.name, ok, f"rounds={outcome.rounds} (budget {self.budget})")


@dataclass
class MaxToolCallsCheck:
    """工具调用总数不超过预算（探测检索 / 工具滥用——团队任务尤甚）。

    读 ``outcome.tool_calls`` 长度（含被委派 worker 的调用，由 ``RecordingSink`` 全量截获）。
    与 ``MaxRounds`` 正交：轮数看 ReAct 节奏，工具数看「检索 / 读取是否泛滥」——一道团队任务
    打数十次 ``web_search`` 的成本 / 延迟灾难，靠它才可量化、可回归。
    """

    budget: int = 24
    name: str = "MaxToolCalls"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        n = len(outcome.tool_calls)
        return CheckOutcome(self.name, n <= self.budget, f"tool_calls={n} (budget {self.budget})")


@dataclass
class StyleCleanCheck:
    """回复无 anti-slop 风格违规（方向④确定性护栏）。

    跑 ``style_lint.style_violations`` 检测套话开场 / 客套收尾 / 未授权 emoji（纯文本、零
    LLM，详见 ``style_lint.py``）。``args.allow`` 可豁免规则——典型是用户自己用了 emoji 时
    放行 ``"emoji"``，与 ``<output_style>`` 的 emoji soft carve-out 对齐。
    """

    allow: list[str] = field(default_factory=list)
    name: str = "StyleClean"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        violations = [v for v in style_violations(outcome.content) if v.rule not in self.allow]
        ok = not violations
        detail = "clean" if ok else "; ".join(f"{v.rule}:{v.snippet}" for v in violations)
        return CheckOutcome(self.name, ok, detail)


@dataclass
class NoFabricationMarkerCheck:
    """回复不含编造痕迹（确定性子集：禁用短语命中即判失败）。

    完整的「不编造」靠 LLM 裁判（§六）；本 Check 只兜确定性可判的明显信号——例如声称
    使用了未提供的工具/能力的固定话术，经 ``args.forbidden`` 配置。空列表则恒过。
    """

    forbidden: list[str] = field(default_factory=list)
    name: str = "NoFabricationMarker"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        text = outcome.content or ""
        hit = [p for p in self.forbidden if p in text]
        return CheckOutcome(self.name, not hit, f"forbidden hits={hit}")


@dataclass
class ContentMatchesCheck:
    """回复正文匹配/不匹配给定正则——**确定性的「答案对不对」校验**。

    评估套件原本只有结构 / 轨迹类 Check（收口、工具、引用数、roster、轮数），**没有**「交付
    物语义上对不对」这一维：一份答案错了、却结构完整（过得了轻层 ``finish_guard`` 的代码围栏
    闭合 + 角标越界两查），现有 Check 一律放行。本 Check 用一个**已知正确答案**的正则在正文上
    ``re.search``——``negate=False`` 要求命中（正确答案出现即过）、``negate=True`` 要求**不**命
    中（探测某个错误答案没出现）。``flags`` 取 ``"i"``（忽略大小写）/``"s"``（``.`` 跨行）/
    ``"m"``（多行），可组合（如 ``"is"``）。

    主用途是「挖坑」探针（远期规划.md §2.5 重层立项证据）：给一道有唯一可判答案的任务（第 N
    个素数 / 复利终值 / 大数乘法 / 日期推算），用本 Check 当确定性地面真值，量化「回合过了轻层
    却答错」的缺陷率——那正是机械轻层够不着、需重层（要跑 / 要重算 / 回源对照）才拦得住的那一类。
    """

    pattern: str = ""
    negate: bool = False
    flags: str = ""
    name: str = "ContentMatches"

    _FLAG_BITS = {"i": re.IGNORECASE, "s": re.DOTALL, "m": re.MULTILINE}

    def _flag_value(self) -> int:
        bits = 0
        for ch in self.flags:
            bits |= self._FLAG_BITS.get(ch, 0)
        return bits

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        text = outcome.content or ""
        try:
            hit = re.search(self.pattern, text, self._flag_value()) is not None
        except re.error as e:
            return CheckOutcome(self.name, False, f"bad regex {self.pattern!r}: {e}")
        ok = (not hit) if self.negate else hit
        verb = "must-not-match" if self.negate else "must-match"
        return CheckOutcome(self.name, ok, f"{verb} {self.pattern!r} -> {'hit' if hit else 'miss'}")


@dataclass
class DeliverableIntegrityCheck:
    """成品完整性（确定性）：禁省略标记 + 同 path 连续 ``file_write`` 字数骤降。

    复用 ``file_ops.has_omission_marker`` / ``is_severe_shrink``——与生产 overwrite soft
    nudge 同语义。扫 ``outcome.content`` 与全部 ``file_write`` 入参正文；任一含省略标记即
    不过。字数骤降仅在同一 path **有旧稿**（≥2 次 write）时比末次 vs 前次；无旧稿跳过该维，
    避免首写误报。默认 gating（不进 ``DIAGNOSTIC_CHECKS``）。
    """

    name: str = "DeliverableIntegrity"

    def run(self, case: EvalCase, outcome: TurnOutcome) -> CheckOutcome:
        from agentcore.tools.builtin.file_ops import has_omission_marker, is_severe_shrink

        reasons: list[str] = []

        content = outcome.content or ""
        if has_omission_marker(content):
            reasons.append("omission in content")

        # path → 按调用序累积的 content 列表（仅成功解析的 file_write）
        writes_by_path: dict[str, list[str]] = {}
        for tool_name, raw in outcome.tool_calls:
            if tool_name != "file_write":
                continue
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                continue
            if not isinstance(args, dict):
                continue
            body = args.get("content")
            if not isinstance(body, str):
                continue
            if has_omission_marker(body):
                path = args.get("path") if isinstance(args.get("path"), str) else "?"
                reasons.append(f"omission in file_write({path})")
            path = args.get("path")
            if isinstance(path, str) and path:
                writes_by_path.setdefault(path, []).append(body)

        for path, bodies in writes_by_path.items():
            if len(bodies) < 2:
                continue  # 无旧稿：跳过 shrink 维
            old_chars = len(bodies[-2])
            new_chars = len(bodies[-1])
            if is_severe_shrink(old_chars, new_chars):
                reasons.append(f"severe shrink {path} ({old_chars}→{new_chars})")

        if reasons:
            return CheckOutcome(self.name, False, "; ".join(reasons))
        return CheckOutcome(self.name, True, "ok")


# 注册表：check 名 → 从 args 构造实例。新增 Check 在此登记，seed_lint 据键集校验。
_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "FinishReason": lambda a: FinishReasonCheck(expected=a.get("expected", "end_turn")),
    "NonEmpty": lambda a: NonEmptyCheck(min_len=int(a.get("min_len", 1))),
    "ToolCalled": lambda a: ToolCalledCheck(tool=a.get("tool", "")),
    "ToolArgsValid": lambda a: ToolArgsValidCheck(
        tool=a.get("tool"), required=list(a.get("required", []))
    ),
    "ToolArgNonEmpty": lambda a: ToolArgNonEmptyCheck(
        tool=a.get("tool", ""), arg=a.get("arg", "")
    ),
    "HasCitations": lambda a: HasCitationsCheck(min_count=int(a.get("min", 1))),
    "Delegated": lambda a: DelegatedCheck(),
    "NotDelegated": lambda a: NotDelegatedCheck(),
    "RosterMatches": lambda a: RosterMatchesCheck(expected=list(a.get("expected", []))),
    "ShapeMatches": lambda a: ShapeMatchesCheck(threshold=float(a.get("threshold", 0.6))),
    "MaxRounds": lambda a: MaxRoundsCheck(budget=int(a.get("budget", 16))),
    "MaxToolCalls": lambda a: MaxToolCallsCheck(budget=int(a.get("budget", 24))),
    "NoFabricationMarker": lambda a: NoFabricationMarkerCheck(
        forbidden=list(a.get("forbidden", []))
    ),
    "StyleClean": lambda a: StyleCleanCheck(allow=list(a.get("allow", []))),
    "ContentMatches": lambda a: ContentMatchesCheck(
        pattern=a.get("pattern", ""),
        negate=bool(a.get("negate", False)),
        flags=a.get("flags", ""),
    ),
    "DeliverableIntegrity": lambda a: DeliverableIntegrityCheck(),
}

CHECK_NAMES: frozenset[str] = frozenset(_REGISTRY)

# 诊断 Check（轨迹形状）：仍注册、仍跑、仍报告，但**不计入** pass/fail（后端架构.md §五）。
# 「派没派 / roster 对不对」是编排手段，不是任务结果——把它当 golden 标签会变成回归测试作者的
# 编排理论（「实现冒充需求」）。过度编排改由「个体贡献=0 + L0 成本预算」度量，期望角色改由 L1
# milestone 覆盖度量。``runner.apply_checks`` 据此集合把对应 CheckOutcome 标为 gating=False。
DIAGNOSTIC_CHECKS: frozenset[str] = frozenset(
    {"Delegated", "NotDelegated", "RosterMatches", "ShapeMatches"}
)

# plan-only 模式下仍有意义的 Check（形状 / 委派）；其余内容类标 n/a、绝不 gating。
PLAN_ONLY_SHAPE_CHECKS: frozenset[str] = frozenset(DIAGNOSTIC_CHECKS)


def build_check(spec: dict[str, Any]) -> Any:
    """从 ``{"name", "args"}`` 规格构造一个 Check 实例（名未注册则 KeyError）。"""
    name = spec["name"]
    args = spec.get("args") or {}
    return _REGISTRY[name](args)

"""路由准确率聚合（方向③：CEO「自己做 vs 交团队」是否判对）.

把一套 ``category="routing"`` 的黄金用例跑出的 :class:`CaseReport` 聚合成**混淆矩阵 +
两类业务化错误率**。与「功能评估」的逐例 PASS/FAIL（``report.py``）正交：那只回「这例过没过」，
本模块回「整套里 CEO 该委派时漏委派多少、不该委派却过度编排多少」——后者才是 Multi-Agent
产品命门（[`docs/06-规划/远期规划.md`](../../../docs/06-规划/远期规划.md)
§2.4「提示词优化」方向③）。

**单一标签源**：每条路由用例用它声明的 check 编码期望方向——``Delegated`` = 期望委派
（正类），``NotDelegated`` = 期望自答（负类）。聚合器从 :class:`CheckOutcome` 的 ``name``
读期望、从 ``outcome.delegated`` 读实际，故无需新增 schema 字段（``seed_lint`` 保证每条
路由用例恰好声明其一）。

**确定性边界**：本模块的混淆矩阵 / 比率全是纯算术，可用合成 :class:`CaseReport` 零成本
单测（见 ``tests/test_evals_routing.py``）。但要**产生**每条用例的 ``outcome.delegated``，
必须把它跑过真实 ``run_chat_pipeline``（真模型 CEO 回合）——故度量本身需真模型运行，属
[`远期规划 §2.4`](../../../docs/06-规划/远期规划.md) 已延后的 eval 主线；本模块只把「跑完
之后怎么算」这层先建好、测好。

正类 = 「应当委派」。于是：
- TP：该委派、确委派；TN：该自答、确自答；
- FP：该自答却委派 = **过度编排**（成本 / 延迟灾难，产品最痛）；
- FN：该委派却自答 = **组队不足**（团队价值被埋没）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentcore.evals.types import CaseReport

# 期望方向由这两个 check 名编码（单一标签源，与 checks.py 注册名一致）。
_DELEGATE_CHECK = "Delegated"
_SELF_CHECK = "NotDelegated"


def _expected_delegate(report: CaseReport) -> bool | None:
    """从用例声明的 check 读期望方向：``Delegated``→True / ``NotDelegated``→False / 都没有→None.

    None = 这条不是带路由标签的用例（聚合器跳过它，不计入混淆矩阵）。``seed_lint`` 已保证
    ``category="routing"`` 的用例恰好声明其一，所以正常套件不会出现「两者都声明」的歧义；
    真出现也以「有 Delegated 即正类」为准（确定且可预期）。
    """
    names = {c.name for c in report.checks}
    if _DELEGATE_CHECK in names:
        return True
    if _SELF_CHECK in names:
        return False
    return None


@dataclass
class RoutingMetrics:
    """一套路由用例的混淆矩阵 + 业务化错误率（正类 = 应当委派）。"""

    total: int = 0  # 计入的带标签路由用例数（errored / 无标签的不计）
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    errors: int = 0  # outcome.error 非空——跑挂了，不计入混淆矩阵但单列出来
    # (case_id, expected_delegate, observed_delegate)，仅收错判，供逐条排查。
    misroutes: list[tuple[str, bool, bool]] = field(default_factory=list)

    @property
    def accuracy(self) -> float | None:
        """整体判对率 (TP+TN)/total；无样本则 None。"""
        return (self.tp + self.tn) / self.total if self.total else None

    @property
    def precision(self) -> float | None:
        """委派精确率 TP/(TP+FP)：它委派的里有多少是真该委派；无委派则 None。"""
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        """委派召回率 TP/(TP+FN)：该委派的里有多少真委派了；无正类样本则 None。"""
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def f1(self) -> float | None:
        """精确率与召回率的调和均值；任一为 None / 和为 0 则 None。"""
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def over_delegation_rate(self) -> float | None:
        """过度编排率 FP/(FP+TN)：该自答的里有多少被过度拆成了团队（产品最痛）；无负类则 None。"""
        denom = self.fp + self.tn
        return self.fp / denom if denom else None

    @property
    def under_delegation_rate(self) -> float | None:
        """组队不足率 FN/(TP+FN)：该委派的里有多少被 CEO 自己埋头做了；无正类则 None。"""
        denom = self.tp + self.fn
        return self.fn / denom if denom else None


def routing_metrics(reports: list[CaseReport]) -> RoutingMetrics:
    """把路由用例的 :class:`CaseReport` 聚合成 :class:`RoutingMetrics`（纯算术，零 LLM）.

    只计入带路由标签（声明了 ``Delegated`` / ``NotDelegated``）且未报错的用例；errored 的
    单独计入 ``errors`` 并跳过混淆矩阵（跑挂 ≠ 路由判错，不该污染准确率）。``samples>1`` 时
    同一 case_id 的多条各自计入（与 ``EvalReport`` 同口径，治非确定性靠多采样后再看比率）。
    """
    m = RoutingMetrics()
    for r in reports:
        expected = _expected_delegate(r)
        if expected is None:
            continue
        if r.outcome.error is not None:
            m.errors += 1
            continue
        observed = r.outcome.delegated
        m.total += 1
        if expected and observed:
            m.tp += 1
        elif expected and not observed:
            m.fn += 1
            m.misroutes.append((r.case_id, expected, observed))
        elif not expected and observed:
            m.fp += 1
            m.misroutes.append((r.case_id, expected, observed))
        else:
            m.tn += 1
    return m


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def routing_metrics_to_dict(m: RoutingMetrics) -> dict:
    """JSON-able dict（落盘 baseline / 回归对比；与 report_to_dict 风格一致）。"""
    return {
        "total": m.total,
        "errors": m.errors,
        "confusion": {"tp": m.tp, "fp": m.fp, "fn": m.fn, "tn": m.tn},
        "accuracy": m.accuracy,
        "precision": m.precision,
        "recall": m.recall,
        "f1": m.f1,
        "over_delegation_rate": m.over_delegation_rate,
        "under_delegation_rate": m.under_delegation_rate,
        "misroutes": [
            {"case_id": cid, "expected_delegate": exp, "observed_delegate": obs}
            for (cid, exp, obs) in m.misroutes
        ],
    }


def format_routing_report(m: RoutingMetrics) -> str:
    """控制台文本：混淆矩阵 + 两类业务化错误率 + 逐条错判。ASCII 标记避免 Windows 乱码。"""
    lines: list[str] = ["=" * 64, "AgentCore 路由准确率（CEO 自己做 vs 交团队）", "=" * 64]
    lines.append(f"  计入用例 {m.total}    跑挂 {m.errors}")
    lines.append("  混淆矩阵（正类 = 应当委派）:")
    lines.append(f"    TP(该委派·确委派) {m.tp}    FN(该委派·却自答) {m.fn}")
    lines.append(f"    FP(该自答·却委派) {m.fp}    TN(该自答·确自答) {m.tn}")
    lines.append("-" * 64)
    lines.append(
        f"  准确率   {_pct(m.accuracy)}    精确率 {_pct(m.precision)}    "
        f"召回率 {_pct(m.recall)}    F1 {_pct(m.f1)}"
    )
    lines.append(f"  过度编排率 {_pct(m.over_delegation_rate)}（该自答却拆团队）")
    lines.append(f"  组队不足率 {_pct(m.under_delegation_rate)}（该委派却自己做）")
    if m.misroutes:
        lines.append("-" * 64)
        lines.append("  错判逐条:")
        for cid, exp, obs in m.misroutes:
            kind = "过度编排" if (obs and not exp) else "组队不足"
            lines.append(f"    [{kind}] {cid}: 期望委派={exp} 实际委派={obs}")
    lines.append("=" * 64)
    return "\n".join(lines)

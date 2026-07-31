"""决策支持 playbook：compare_options."""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.playbooks._common import (
    MAX_PLAYBOOK_FANOUT,
    clean_str,
    clean_str_list,
)


def compare_options(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """N×并行评估各选项 → 汇总对比 + 推荐（依赖全部评估）.

    The decision-support shape: one evaluator per option (each stays objective on its own one),
    then a synthesiser produces the cross-option comparison the CEO relays.

    options 超过 ``MAX_PLAYBOOK_FANOUT`` 时显式拒绝（不折叠、不静默截断），引导 CEO 收敛短名单。
    """
    question = clean_str(args.get("question"))
    options = clean_str_list(args.get("options"), cap=None)
    errors: list[str] = []
    if not question:
        errors.append("compare_options 需要 slot『question』（要决策的问题）")
    if len(options) < 2:
        errors.append("compare_options 需要 slot『options』（>=2 个待比较选项）")
    elif len(options) > MAX_PLAYBOOK_FANOUT:
        errors.append(
            f"compare_options 的 options 共 {len(options)} 个，超过上限 "
            f"{MAX_PLAYBOOK_FANOUT}；请收敛为短名单后再试"
            "（本 playbook 不对选项做折叠或静默截断）。"
        )
    if errors:
        return [], errors
    criteria = clean_str_list(args.get("criteria"), cap=8)
    crit_eval = ("，按这些维度评估：" + "、".join(criteria)) if criteria else ""
    crit_sum = (f"（维度：{'、'.join(criteria)}）") if criteria else ""

    eval_ids = [f"eval_{i}" for i in range(len(options))]
    tasks: list[dict[str, Any]] = []
    for eid, opt in zip(eval_ids, options, strict=True):
        tasks.append(
            {
                "id": eid,
                "role": "评估员",
                "task": (
                    f"针对决策问题【{question}】，深入评估这一个选项：{opt}{crit_eval}。"
                    "给出它的优点 / 缺点 / 适用与不适用场景，只评这一个、保持客观。"
                ),
                "deliverable": {"name": f"对选项【{opt}】的评估"},
            }
        )
    tasks.append(
        {
            "id": "summary",
            "role": "汇总分析师",
            "task": (
                f"对照上游对各选项的评估，针对【{question}】给出横向对比{crit_sum}："
                "一张对比表 + 明确推荐及理由；若各选项各有适用场景，说清分别何时选谁。"
            ),
            "depends_on": eval_ids,
            "deliverable": {"name": "对比表 + 推荐结论"},
        }
    )
    return tasks, []

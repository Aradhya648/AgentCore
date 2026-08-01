"""代码审计 playbook：``code_audit``（报告纪律内建；正交于 research_report 成篇审校）。"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.playbooks._common import (
    clean_str,
    clean_str_list,
    fold_fanout_slots,
)
from agentcore.workspace.stage_dirs import REVIEWS_DIR

# 与规划定案一致：每工人模块 Phase B 最多定案条数。
_DEFAULT_K = 8

_REQUIRED_SECTIONS = [
    "〇、人审速览",
    "一、属实缺陷",
    "二、已撤销",
    "三、观察与工程债",
]

_AUDIT_DISCIPLINE = """
【两阶段·强制】先 A 宽扫只出候选（严重度上限低/观察），
再 B 定案（读全函数体、追上游、查根+包内配置）。
向用户「共 N 条缺陷」只计 B 定案属实且落入「一、属实缺陷」者；A 候选未进 B 不进 N。
预算不够则少报：本模块 Phase B 最多定案 K={k} 条；未覆盖面最多一行「未覆盖缺口」。

【每条发现强制字段】验证方式∈全文精读|运行验证|静态推断·未读全|待核实；
定案∈属实|误报|部分属实|待核实；证据指针=文件:行或命令+退出码。
安全/路径/注入类必写可达性（输入是否用户可控+调用链一句话）；其它中+建议写。
硬规则：验证方式为未读全或定案为待核实 → 不得标中及以上。

【严重度】高=明确利用/注入路径，或静默丢数据/错归属且用户可感知；
中=可达安全削弱/错配即挂/工具误伤本机其它工程；产品语义错默认中；
低=纵深缺失/不可达/探针质量/属实可修的小工程卫生（低进 N）；
观察·工程=超时/未读全/纯慢（不进 N）。禁止把全量 tsc/pytest 超时写成中+缺陷。

【Phase B checklist·中+属实前必过】①cleanup/定义须读全或全文 grep 证缺；
②标识符未定义须全文搜；③ignore/配置查根+包内，能跑则 git check-ignore / git ls-files；
④「不存在」按 import 路径解析；⑤穿越/注入追生成源头；⑥范本对比先确认对照有、本处无；
⑦标高必须写出谁在什么输入下触发。

【交付骨架·唯一】报告须含且仅以这些大节组织：
〇、人审速览（仍成立中+ / 已撤销 / 待核实与缺口）→ 一、属实缺陷 → 二、已撤销 → 三、观察与工程债。
正向确认默认不写。禁止套 research_report 学术审校环；质量靠 A/B+本契约。
""".strip()


def _safe_label(name: str) -> str:
    """Filename-safe label (keep CJK; strip path separators)."""
    s = name.strip().replace("\\", "_").replace("/", "_").replace("..", "_")
    return s[:80] or "scope"


def _report_artifact(label: str) -> str:
    return f"{REVIEWS_DIR}/code-audit-{_safe_label(label)}.md"


def _auditor_task_body(
    *,
    scope: str,
    module: str,
    focus: str,
    k: int,
    artifact: str,
) -> str:
    focus_line = f"侧重：{focus}。" if focus else "全类问题均可报，按 rubric 定严重度。"
    json_artifact = (
        artifact[:-3] + ".audit.json" if artifact.endswith(".md") else f"{artifact}.audit.json"
    )
    return (
        f"对范围【{scope}】中的模块【{module}】做代码审计（只读调查，默认不改业务源码；"
        f"报告落盘除外）。{focus_line}"
        f"{_AUDIT_DISCIPLINE.format(k=k)}"
        f"完整报告用 file_write 落到 `{artifact}`（Markdown）；"
        f"另交配套 `{json_artifact}`（findings：severity/verification/verdict/evidence 等）。"
        "handoff 只给人审速览摘要 + 路径，不得以 handoff 替代落盘。"
        "短命令优先：rg/grep、定点 read、git check-ignore、git ls-files；"
        "禁止把全量 typecheck/全量 pytest 超时当作中+缺陷证据。"
    )


def _auditor_deliverable(artifact: str, name: str) -> dict[str, Any]:
    json_artifact = (
        artifact[:-3] + ".audit.json" if artifact.endswith(".md") else f"{artifact}.audit.json"
    )
    return {
        "form": "files",
        "name": name,
        "artifacts": [artifact, json_artifact],
        "required_sections": list(_REQUIRED_SECTIONS),
        "must_contain": ["验证方式", "定案"],
        "strict": True,
        "code_audit_gate": True,
    }


def code_audit(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """代码审计：1 人两阶段 A→B；多模块则并行审计员 + 主管跨模块速览。

    与 ``parallel_brief``（摸底对齐）、``research_report``（成文+学术审校）、
    ``repair_code``（按症状修）划界：本形状专产纪律化审计报告。
    """
    scope = clean_str(args.get("scope") or args.get("topic") or args.get("target"))
    if not scope:
        return [], [
            "code_audit 需要 slot『scope』（审计范围：路径/模块/子系统；"
            "亦接受 topic/target）"
        ]

    focus = clean_str(args.get("focus"))
    k_raw = args.get("k")
    try:
        k = int(k_raw) if k_raw is not None and str(k_raw).strip() != "" else _DEFAULT_K
    except (TypeError, ValueError):
        return [], ["code_audit slot『k』须为正整数（每模块 Phase B 定案上限）"]
    if k < 1 or k > 40:
        return [], ["code_audit slot『k』须在 1–40（默认 8）"]

    modules = clean_str_list(
        args.get("modules") or args.get("angles") or args.get("areas"),
        cap=None,
    )
    out_override = clean_str(args.get("output_path"))

    if not modules:
        label = clean_str(args.get("label")) or "main"
        artifact = out_override or _report_artifact(label)
        return [
            {
                "id": "audit_0",
                "role": "代码审计员",
                "task": _auditor_task_body(
                    scope=scope, module=scope, focus=focus, k=k, artifact=artifact
                ),
                "deliverable": _auditor_deliverable(
                    artifact, f"代码审计报告（已落盘 {artifact}）"
                ),
            }
        ], []

    if len(modules) < 2:
        return [], [
            "code_audit 若传 modules/angles，须 ≥2 个模块（单模块请省略 modules，"
            "只用 scope）"
        ]

    slots, fold_note = fold_fanout_slots(modules, label="审计模块")
    fold_hint = f" {fold_note}" if fold_note else ""
    tasks: list[dict[str, Any]] = []
    audit_ids: list[str] = []

    for i, parts in enumerate(slots):
        merged = len(parts) > 1
        label = " + ".join(parts)
        artifact = _report_artifact(label)
        module_desc = (
            f"合并模块：{'、'.join(f'【{p}】' for p in parts)}（须全部覆盖）"
            if merged
            else parts[0]
        )
        tid = f"audit_{i}"
        audit_ids.append(tid)
        body: dict[str, Any] = {
            "id": tid,
            "role": "代码审计员",
            "task": (
                _auditor_task_body(
                    scope=scope, module=module_desc, focus=focus, k=k, artifact=artifact
                )
                + fold_hint
            ),
            "deliverable": _auditor_deliverable(
                artifact, f"【{label}】审计报告（已落盘 {artifact}）"
            ),
        }
        if fold_note and merged:
            body["playbook_note"] = fold_note
        tasks.append(body)

    synth_path = out_override or f"{REVIEWS_DIR}/code-audit-汇总速览.md"
    tasks.append(
        {
            "id": "audit_synth",
            "role": "审计主管",
            "depends_on": list(audit_ids),
            "task": (
                f"汇总主题【{scope}】下各路代码审计报告，产出**跨模块人审速览**（一页内）："
                "仍成立的中+（去重）/ 已撤销 / 待核实与未覆盖缺口；"
                "N 只计各路「一、属实缺陷」合并去重后的条数。"
                f"先 file_read 各审计员落盘报告，再 file_write 到 `{synth_path}`。"
                "不要重做全量审计；不要套 research_report 审校环。"
                "正向确认默认不写。"
            ),
            "deliverable": {
                "form": "files",
                "name": f"跨模块审计人审速览（已落盘 {synth_path}）",
                "artifacts": [synth_path],
                "required_sections": ["人审速览", "属实中+", "缺口"],
                "must_contain": ["属实", "撤销"],
            },
        }
    )
    return tasks, []

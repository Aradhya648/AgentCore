"""Escalation Gate — tool_exec 后区分执行层自愈 vs 方案层上报。

与 Worker 主动 ``escalate`` 工具正交：Gate 是确定性后置检查（模型可能漏报），
``escalate`` 是模型主动通道。Phase 1 只做判断与标记，不实现分裂。
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.text import clip_preview
from agentcore.runtime.loop_controller import ToolAttempt
from agentcore.runtime.routing.models import (
    EscalationKind,
    EscalationSignal,
    GateVerdict,
    ProblemLayer,
)

logger = get_logger(__name__)

# 方案层：需求 / 契约 / 权限 / 范围矛盾（命中 → escalate）
# CONTRADICTION 不用裸词 ``contradict``：用户仓库/游戏文案（证人、证词）高频误伤；
# 只认任务口语（中文短语 / conflicting requirements / requirements contradict…）。
_SCHEME_PATTERNS: tuple[tuple[EscalationKind, re.Pattern[str]], ...] = (
    (
        EscalationKind.CONTRADICTION,
        re.compile(
            r"需求矛盾|互相矛盾|冲突的要求|无法同时满足|"
            r"conflicting\s+requirements|"
            r"requirements?\s+contradict|"
            r"contradict(?:s|ed|ing)?\s+(?:each\s+other|one\s+another)",
            re.IGNORECASE,
        ),
    ),
    (
        EscalationKind.CONTRACT,
        # 注意：不含 "out of scope"（范围偏离归 SCOPE，见下）；此类只收契约/权限语境。
        re.compile(
            r"改(变|动)?接口契约|破坏(对外)?契约|超出权限|越权|无权限|"
            r"breaking\s+change|beyond\s+(my\s+)?(authority|permission)|"
            r"接口不兼容|schema\s+change|api\s+contract",
            re.IGNORECASE,
        ),
    ),
    (
        EscalationKind.SCOPE,
        re.compile(
            r"职责偏离|范围不对|真正(该|要)做的|与(初始)?计划不符|"
            r"out\s+of\s+scope|wrong\s+scope|scope\s+creep",
            re.IGNORECASE,
        ),
    ),
    (
        EscalationKind.DEP,
        re.compile(
            r"缺(少|少一个)?(输入|依赖)|依赖不存在|还没人产出|卡在缺|"
            r"missing\s+(input|dependency)|blocked\s+on\s+missing",
            re.IGNORECASE,
        ),
    ),
)

# 执行层：路径 / import / lint / 超时 / 工具瞬时失败（自愈，不上报）
_EXECUTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"FileNotFoundError|No such file|路径(不存在|错误)|ENOENT",
        r"ModuleNotFoundError|ImportError|import\s+error|cannot\s+import",
        r"SyntaxError|IndentationError|lint|ruff|eslint|prettier",
        r"超时|timeout|timed?\s*out|退出码|exit\s*code|Traceback",
        r"工具 '.*' (执行时发生内部错误|执行超过|未找到)",
        r"ConnectionError|ECONNREFUSED|rate\s*limit|429|5\d\d",
        r"请调整方案或换一种方式|不要原样重试",
    )
)

# 协调类工具失败不走 Gate 升级（它们有自己的通道）
_SKIP_TOOLS = frozenset(
    {"escalate", "post_note", "read_notes", "amend_note", "handoff", "delegate"}
)

# 语料全文可含方案层词，但不代表本任务矛盾——与网页检索同理。
# 含：外网检索 + 工作区读/搜（file_read / grep / code_search）。
# 只跳过对该工具 *输出* 的 scheme 匹配；模型自述仍走 escalate 工具通道。
_SCHEME_SKIP_OUTPUT_TOOLS = frozenset(
    {"web_search", "read_url", "file_read", "grep", "code_search"}
)


def evaluate_after_tools(
    *,
    attempts: list[ToolAttempt],
    tool_outputs: list[str] | None = None,
    run_id: str = "",
) -> GateVerdict:
    """在一轮 ``execute_tools`` 完成后做分层判定。

    ``tool_outputs`` 与 ``attempts`` 按调用顺序对齐（可短于 attempts）；缺省时仅根据
    ``success`` 判定——失败默认视为执行层（自愈），避免误报方案层。
    """
    outputs = list(tool_outputs or [])
    scheme_signals: list[EscalationSignal] = []

    for idx, attempt in enumerate(attempts):
        if attempt.tool_name in _SKIP_TOOLS:
            continue
        text = outputs[idx] if idx < len(outputs) else ""
        # 语料类工具：不扫 tool 输出做方案层词；失败仍按执行层自愈。
        if attempt.tool_name in _SCHEME_SKIP_OUTPUT_TOOLS:
            if not attempt.success:
                logger.debug(
                    "routing.gate.execution_layer",
                    run_id=run_id,
                    tool=attempt.tool_name,
                    policy_failure=attempt.policy_failure,
                )
            continue
        blob = f"{attempt.tool_name}\n{text}"

        scheme = _match_scheme(blob)
        if scheme is not None:
            kind, snippet = scheme
            scheme_signals.append(
                EscalationSignal(
                    layer=ProblemLayer.SCHEME,
                    kind=kind,
                    question=_question_for(kind, attempt.tool_name, snippet),
                    assumption="按当前可验证事实继续能做的部分；方案层待上级确认后再改契约/范围。",
                    evidence=clip_preview(snippet, 200),
                    tool_name=attempt.tool_name,
                    source="escalation_gate",
                )
            )
            continue

        # 失败但无方案层信号 → 执行层（含 policy_failure：环境/策略挡，非方案）
        if not attempt.success:
            logger.debug(
                "routing.gate.execution_layer",
                run_id=run_id,
                tool=attempt.tool_name,
                policy_failure=attempt.policy_failure,
            )

    if scheme_signals:
        logger.info(
            "routing.gate.scheme_escalation",
            run_id=run_id,
            count=len(scheme_signals),
            kinds=[s.kind.value for s in scheme_signals],
        )
        return GateVerdict(
            layer=ProblemLayer.SCHEME,
            action="escalate",
            signals=scheme_signals,
        )

    return GateVerdict(layer=ProblemLayer.EXECUTION, action="continue", signals=[])


def classify_problem(text: str) -> ProblemLayer:
    """对任意障碍文本做分层（供测试 / 诊断；Gate 主路径用 :func:`evaluate_after_tools`）。"""
    if _match_scheme(text) is not None:
        return ProblemLayer.SCHEME
    if any(p.search(text) for p in _EXECUTION_PATTERNS):
        return ProblemLayer.EXECUTION
    # 未知偏执行层：宁可自愈一轮，也不误报方案层
    return ProblemLayer.EXECUTION


def _match_scheme(text: str) -> tuple[EscalationKind, str] | None:
    for kind, pattern in _SCHEME_PATTERNS:
        m = pattern.search(text)
        if m is not None:
            return kind, m.group(0)
    return None


def _question_for(kind: EscalationKind, tool_name: str, snippet: str) -> str:
    tool = f"（工具 {tool_name}）" if tool_name else ""
    if kind is EscalationKind.CONTRADICTION:
        return f"任务需求存在矛盾{tool}：检测到「{snippet}」。请上级明确优先级或取舍。"
    if kind is EscalationKind.CONTRACT:
        return (
            f"继续执行可能改动接口契约或超出权限{tool}："
            f"检测到「{snippet}」。请上级确认是否允许。"
        )
    if kind is EscalationKind.SCOPE:
        return f"发现职责/范围可能偏离初始计划{tool}：检测到「{snippet}」。请上级确认真实目标。"
    if kind is EscalationKind.DEP:
        return f"卡在尚不存在的输入/依赖{tool}：检测到「{snippet}」。请上级补依赖或改计划。"
    return f"遇到需上级拍板的方案层问题{tool}：{snippet}"


def signals_as_dicts(signals: list[EscalationSignal]) -> list[dict[str, Any]]:
    """Serialize gate signals for ``RunState.escalations`` merge."""
    return [s.to_run_escalation_payload() for s in signals]

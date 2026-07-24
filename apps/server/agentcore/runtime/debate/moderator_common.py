"""主持人共用工具 —— 截断 / JSON 容错 / prompt 块拼装。

供议题 / 裁判 / 简报子模块复用；不持状态。→ 见设计: docs/03-AI核心/辩论编排设计.md §二
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agentcore.runtime.debate.types import (
    DebateConfig,
    RoundBoundary,
    RoundResult,
    SideTurn,
)

# 单方发言喂进裁判 / 简报时的截断上限：裁判要看够内容才能判「真交锋」，但全文会爆 prompt。
# 头尾保留（_clip 取首尾各半），让发言的开场立论与收尾结论都留在视野里。
_TURN_CLIP = 3000
_SUMMARY_CLIP = 800
# 跨轮论点账本喂进裁判时的截断（收敛校准 §三 H2）：裁判本只看【当前轮】发言，看不见跨轮重复→
# 老论点换措辞被误判成新论点→永不因边际递减收敛（真实 trace 5 轮撞满 max_rounds 的根因）。喂前
# 几轮的紧凑账本让 new_arguments 能真正跨轮判；用已压缩的 summary/clashes、非全文，守 §二 token 预算。
_LEDGER_SUMMARY_CLIP = 300
_LEDGER_CLASHES_PER_ROUND = 4

# 每轮完成后的回调（DebateTool 在此 emit 逐轮小结 SSE 事件 / 触发老板检查点；测试可省）。
RoundHook = Callable[[RoundResult], Awaitable[None]]
# 本轮焦点既定、辩手发言【前】的回调（DebateTool 据此 emit debate_round_started，让焦点先于
# 发言亮出）；入参 (round_no, focus, opening)。opening 仅首轮非空（后续轮 ""）。测试可省。
RoundStartHook = Callable[[int, str, str], Awaitable[None]]
# 交互式逐轮边界回调（opt-in，辩论编排设计.md §逐轮交互）：每轮判完 + 小结后，把「继续辩 / 加角
# 度 / 够了出结论」的决定权交给用户。入参 (round_no, result, converged, max_rounds)；返回
# :class:`RoundBoundary` 驱动循环，或 ``None`` 表示「交回裁判自动收敛」（DebateTool 在超时 / 无活
# 跃用户时返 None）。未接此钩子（默认 / 测试 / 非交互辩论）时循环逐字按裁判自判收敛，行为不变。
RoundBoundaryHook = Callable[..., Awaitable["RoundBoundary | None"]]

# 主持人内部 LLM 调用：``(system, user, step) → 解析后的 JSON dict``（坏 JSON → {}）。
CompleteJson = Callable[[str, str, str], Awaitable[dict[str, Any]]]


def _clip(text: str, limit: int = _TURN_CLIP) -> str:
    """头尾保留地截断 —— 长发言的立论（头）与结论（尾）都不丢，只挖空中段。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    half = max(1, (limit - 20) // 2)
    return f"{text[:half]}\n……（中段略）……\n{text[-half:]}"


def _parse_json_object(content: str) -> dict[str, Any]:
    """从 LLM 输出抽第一个 JSON 对象；坏 JSON 容错为 {}（调用方按场景降级）。"""
    try:
        start = content.index("{")
        end = content.rindex("}")
        data = json.loads(content[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_str_list(value: Any) -> list[str]:
    """把 LLM 返回的列表字段规整为去空的字符串列表（容忍标量 / 混入非串元素）。

    亦容忍「编号对象」dict（如 ``{"1": "q1", "2": "q2"}``）：仅当全部值为非空字符串时，
    按插入序（文档序）取 values——禁止按 key 排序（字典序会把 ``"10"`` 排到 ``"2"`` 前）。
    其他 dict 形态回落为 []。
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        values = list(value.values())
        if values and all(isinstance(v, str) and v.strip() for v in values):
            return [v.strip() for v in values]
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
        elif item is not None:
            s = str(item).strip()
        else:
            s = ""
        if s:
            out.append(s)
    return out


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "是", "y"}
    return default


def _sides_block(config: DebateConfig) -> str:
    lines = []
    for s in config.sides:
        tag = "（被审方案方）" if s.is_subject else ""
        lines.append(f"- {s.name}{tag}[{s.key}]：{s.stance}")
    return "\n".join(lines)


def _turns_block(turns: Sequence[SideTurn], *, clip: int = _TURN_CLIP) -> str:
    blocks = []
    for t in turns:
        if not t.ok:
            label = "本轮缺席（无有效发言）" if t.absent else "本轮未产出有效发言"
            blocks.append(f"### {t.side_name}[{t.side_key}]\n（{label}）")
            continue
        blocks.append(f"### {t.side_name}[{t.side_key}]\n{_clip(t.content, clip)}")
    return "\n\n".join(blocks)

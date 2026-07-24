"""dev 实测：clear_tool_uses 的净收益 A/B 测量 + keep_recent 阈值扫描（真实 DeepSeek）。

同一条「长 worker 回合」消息窗口，对若干 keep_recent 档各投影一版，发给真实
DeepSeek，对比**实报** input / cache_hit / cache_miss token——把净收益从模型路径
随机性里隔离出来（同输入 → 唯一变量是清理力度）。

每档调用两次 cold→warm 观察前缀缓存：
  - cold：首发，缓存大多 miss
  - warm：复发 = 生产稳态（同一窗口逐轮重发的真实成本）

档位：``None`` = full 基线（不清理）；整数 = 该 keep_recent。min_chars 取 settings。
只读：不写库、不动正在跑的 server；用全局 .env key（build_provider(None)）。
跑法（在 apps/server 下）：
  ``uv run python scripts/measure_tool_clear.py``          # 默认扫 full,6,4,3
  ``uv run python scripts/measure_tool_clear.py 6 4 3 2``  # 自定义档位
"""

import asyncio
import json
import sys
from pathlib import Path

from agentcore.config import settings
from agentcore.core.errors import LLMError
from agentcore.llm.factory import build_provider
from agentcore.llm.provider.protocol import LLMMessage, LLMRequest, ToolCall, ToolCallFunction
from agentcore.runtime.engine.tool_clear import project_cleared_window

REPO = Path(__file__).resolve().parents[3]

# 用真实文件内容当工具结果，体量/分布贴近真实长 worker 回合。
N_FILES = 10
FILE_TRUNC = 5000  # 每份截断到 5000 字符（仍远大于 min_chars，保证可清理）
MIN_SOURCE_LEN = 2500

FILE_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": "读取一个文件的全部内容。",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}


def pick_files(n: int, min_len: int) -> list[tuple[Path, str]]:
    """挑 n 份足够大的真实文档当工具结果（按路径排序，确定性）。"""
    out: list[tuple[Path, str]] = []
    for path in sorted((REPO / "docs").rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(text) >= min_len:
            out.append((path.relative_to(REPO), text[:FILE_TRUNC]))
        if len(out) >= n:
            break
    return out


def build_window(files: list[tuple[Path, str]]) -> list[LLMMessage]:
    """构造一条「读了 N 个文件」的 worker 窗口：每读 = assistant(tool_call)+tool(result)。"""
    listing = "\n".join(str(p) for p, _ in files)
    msgs: list[LLMMessage] = [
        LLMMessage(role="system", content="你是 AgentCore 的研究型 worker，善于通读多份文档并归纳要点。"),
        LLMMessage(role="user", content=f"请逐个阅读以下项目文档，最后给出总体结论：\n{listing}"),
    ]
    for i, (path, text) in enumerate(files):
        cid = f"call_{i:02d}"
        msgs.append(
            LLMMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id=cid,
                        function=ToolCallFunction(
                            name="file_read",
                            arguments=json.dumps({"path": str(path)}, ensure_ascii=False),
                        ),
                    )
                ],
            )
        )
        msgs.append(LLMMessage(role="tool", tool_call_id=cid, content=text))
    msgs.append(LLMMessage(role="user", content="基于以上所有文件，用一句中文给出总体结论。"))
    return msgs


def make_request(window: list[LLMMessage]) -> LLMRequest:
    """非思考 + 工具在场 + tool_choice=none + 极小输出：input/cache 计费与生产一致，
    输出成本压到最低（thinking 不影响 input/cache token 计量，只影响 output）。"""
    return LLMRequest(
        messages=window,
        model="deepseek-v4-flash",
        temperature=0.0,
        max_tokens=32,
        tools=[FILE_READ_TOOL],
        tool_choice="none",
        stream=False,
        thinking=False,
        scenario="measure.tool_clear",
    )


def variant_window(full: list[LLMMessage], keep_recent: int | None, min_chars: int):
    """返回 (window, n_cleared, chars)；keep_recent=None → full 基线（不清理）。"""
    if keep_recent is None:
        return full, 0, sum(len(m.content or "") for m in full)
    cleared = project_cleared_window(
        full, clearable_tools=frozenset({"file_read"}), keep_recent=keep_recent, min_chars=min_chars
    )
    n = 0 if cleared is full else sum(1 for a, b in zip(full, cleared, strict=True) if a.content != b.content)
    return cleared, n, sum(len(m.content or "") for m in cleared)


def parse_sweep(argv: list[str]) -> list[int | None]:
    """CLI 档位：整数列表；总把 full 基线（None）放最前。默认 None,6,4,3。"""
    if not argv:
        return [None, 6, 4, 3]
    vals = [int(a) for a in argv]
    return [None, *vals]


async def main() -> None:
    files = pick_files(N_FILES, MIN_SOURCE_LEN)
    if len(files) < 8:
        print(f"[skip] 仅找到 {len(files)} 份足够大的文档（需≥8）。")
        return

    full = build_window(files)
    min_chars = settings.engine_tool_clear_min_chars
    sweep = parse_sweep(sys.argv[1:])
    base_chars = sum(len(m.content or "") for m in full)

    print("=" * 80)
    print("clear_tool_uses · keep_recent 阈值扫描（真实 DeepSeek，warm = 稳态）")
    print("=" * 80)
    print(f"窗口：{len(files)} 个 file_read 结果 + 系统/用户消息；min_chars={min_chars}")
    print(f"原始字符总量（full）：{base_chars:,}")
    print("-" * 80)

    provider = build_provider(None)
    # (keep_recent, n_cleared, chars, warm_input, warm_hit, warm_miss)
    rows: list[tuple[int | None, int, int, int, int, int]] = []
    try:
        for kr in sweep:
            window, n_cleared, chars = variant_window(full, kr, min_chars)
            await provider.complete(make_request(window))  # cold（暖缓存）
            warm = (await provider.complete(make_request(window))).usage  # warm = 稳态
            rows.append((kr, n_cleared, chars, warm.input_tokens, warm.cache_hit_tokens, warm.cache_miss_tokens))
    except LLMError as exc:
        print(f"[error] DeepSeek 调用失败：{exc}")
        return
    finally:
        await provider.close()

    full_input = next((r[3] for r in rows if r[0] is None), 0)
    head = f"{'keep_recent':<12}{'cleared':>8}{'win_chars':>11}{'warm_input':>12}{'cache_hit':>11}{'cache_miss':>12}{'省 vs full':>12}"
    print(head)
    for kr, n_cleared, chars, inp, hit, miss in rows:
        label = "full" if kr is None else str(kr)
        win_chars = base_chars - chars
        saved = full_input - inp
        pct = f"{saved / full_input * 100:.1f}%" if full_input else "-"
        saved_cell = "基线" if kr is None else f"{saved:,}/{pct}"
        print(f"{label:<12}{n_cleared:>8}{win_chars:>11,}{inp:>12,}{hit:>11,}{miss:>12,}{saved_cell:>12}")
    print("-" * 80)
    print("读法：warm_input 越低省越多；cache_miss 应始终很小（指针稳定→前缀缓存不塌）。")
    print("注：cold-miss ≈ warm_input（冷启动全 miss），即缓存过期/慢节奏轮的省钱上界。")
    print("权衡：keep_recent 越低省越多，但保留逐字结果越少→模型可能需重新调用工具重取")
    print("      （多一次往返 + 重新加回 token），token 曲线测不出这层 re-read 风险。")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())

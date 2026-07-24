"""挖坑探针·代码必须真跑：探「便宜层够不着」的一类缺陷——交付的代码看着对、一执行才暴露 bug。

与 ``evals/cases/probe/`` 的算术探针互补：那批是「单一可判数字」（结果 25/25，反证算术不是缺口）；
本批是「写一个函数 → 真扔进沙箱跑隐藏边界用例」。轻层 ``finish_guard`` 只查代码围栏闭合 + 角标
越界，对**逻辑 bug 一无所知**——这正是只有「真跑一遍」的重层才拦得住的那一类。

方法（决定论、可复现）：
- 生成走产品真实模型（worker = ``agent`` profile → Flash + thinking/high），**不给任何工具**
  （隔离「裸生成」缺陷率：模型无法自己调 ``code_execute`` 自测、掩盖 bug）；
- 执行复用产品同一个 :class:`SubprocessSandbox`，把模型代码 + 隐藏断言一起跑，``exit_code==0`` 且
  打印哨兵 = 通过；任一断言挂 = 交付了带 bug 的代码；
- 每题跑 ``SAMPLES`` 次量化出错率，失败样本打印 stderr 尾部（具体哪条边界断言挂了 = 靶子）。

用法：``uv run python scripts/probe_code_execution.py``（需 ``EVAL_DEEPSEEK_API_KEY`` 或 .env 里的 ``PLATFORM_API_KEY``）。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import sys
from pathlib import Path

from agentcore.evals.harness import _eval_credentials
from agentcore.llm.factory import build_provider
from agentcore.llm.profiles import build_request, default_turn_profiles, get_profile
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.tools.sandbox.protocol import ExecutionRequest
from agentcore.tools.sandbox.subprocess import SubprocessSandbox

DEFAULT_SAMPLES = 5

_NO_TOOLS = (
    "只输出一个 ```python 代码块，里面是完整的函数定义，不要任何解释文字。"
    "不要写测试、不要打印、不要调用任何工具、不要尝试运行代码——只把函数写出来。"
)

# 每题：精确签名 + 易出微妙 bug 的边界；tests 是隐藏断言（含 tuple/list 归一，避免误判格式差异）。
TASKS: list[dict[str, str]] = [
    {
        "id": "roman_to_int",
        "prompt": (
            "用 Python 写一个函数 `roman_to_int(s: str) -> int`，把罗马数字字符串转成整数，"
            "必须正确处理减法表示（IV=4, IX=9, XL=40, XC=90, CD=400, CM=900）。" + _NO_TOOLS
        ),
        "tests": (
            'assert roman_to_int("III") == 3\n'
            'assert roman_to_int("IV") == 4\n'
            'assert roman_to_int("IX") == 9\n'
            'assert roman_to_int("LVIII") == 58\n'
            'assert roman_to_int("XL") == 40\n'
            'assert roman_to_int("CD") == 400\n'
            'assert roman_to_int("MCMXCIV") == 1994\n'
            'assert roman_to_int("MMMCMXCIX") == 3999\n'
        ),
    },
    {
        "id": "merge_intervals",
        "prompt": (
            "用 Python 写一个函数 `merge_intervals(intervals: list[list[int]]) -> list[list[int]]`，"
            "合并所有重叠区间，返回按起点升序、互不重叠的区间列表。相接的区间（如 [1,4] 与 [4,5]）"
            "视为重叠应合并；输入可能未排序；空输入返回空列表。" + _NO_TOOLS
        ),
        "tests": (
            "_n = lambda r: [list(x) for x in r]\n"
            "assert _n(merge_intervals([[1,3],[2,6],[8,10],[15,18]])) == [[1,6],[8,10],[15,18]]\n"
            "assert _n(merge_intervals([[1,4],[4,5]])) == [[1,5]]\n"
            "assert _n(merge_intervals([[1,4],[2,3]])) == [[1,4]]\n"
            "assert _n(merge_intervals([[2,3],[1,4]])) == [[1,4]]\n"
            "assert _n(merge_intervals([])) == []\n"
            "assert _n(merge_intervals([[1,4],[5,6]])) == [[1,4],[5,6]]\n"
        ),
    },
    {
        "id": "is_valid_brackets",
        "prompt": (
            "用 Python 写一个函数 `is_valid(s: str) -> bool`，判断只含 ()[]{} 的字符串括号是否"
            "正确匹配闭合（类型也要匹配）。空串视为合法。" + _NO_TOOLS
        ),
        "tests": (
            'assert is_valid("()") is True\n'
            'assert is_valid("()[]{}") is True\n'
            'assert is_valid("(]") is False\n'
            'assert is_valid("([)]") is False\n'
            'assert is_valid("{[]}") is True\n'
            'assert is_valid("") is True\n'
            'assert is_valid("(") is False\n'
            'assert is_valid("]") is False\n'
        ),
    },
    {
        "id": "find_first_geq",
        "prompt": (
            "用 Python 写一个函数 `find_first_geq(nums: list[int], target: int) -> int`，"
            "nums 已升序（可能有重复元素），返回第一个 >= target 的元素下标；若不存在返回 len(nums)。"
            "要求 O(log n) 二分实现。" + _NO_TOOLS
        ),
        "tests": (
            "assert find_first_geq([1,2,4,4,5], 4) == 2\n"
            "assert find_first_geq([1,2,3], 0) == 0\n"
            "assert find_first_geq([1,2,3], 4) == 3\n"
            "assert find_first_geq([], 1) == 0\n"
            "assert find_first_geq([5], 5) == 0\n"
            "assert find_first_geq([1,3,3,3,5], 3) == 1\n"
            "assert find_first_geq([1,3,3,3,5], 2) == 1\n"
        ),
    },
]


def extract_python(text: str) -> str | None:
    """从模型回复里抽出 Python 代码：取最长的 ``` 围栏块（多块时函数通常是最长那块）。"""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return max(blocks, key=len)
    return None


async def _close(provider) -> None:
    closer = getattr(provider, "close", None) or getattr(provider, "aclose", None)
    if closer:
        res = closer()
        if inspect.isawaitable(res):
            await res


async def _run_task(
    task: dict[str, str], *, profile, model: str, provider, sandbox, samples: int
) -> dict:
    """Run one coding task ``samples`` 次：生成→沙箱真跑隐藏用例，返回 ``{id, passed, total, fails}``。"""
    passed = 0
    fails: list[dict[str, str | int]] = []
    for i in range(samples):
        req = build_request(
            profile,
            [LLMMessage(role="user", content=task["prompt"])],
            stream=False,
            model=model,
        )
        resp = await provider.complete(req)
        code = extract_python(resp.content or "")
        if not code:
            fails.append({"sample": i, "why": "未给出代码块", "detail": (resp.content or "")[-300:]})
            continue
        full = (
            code
            + "\n\n# ---- hidden edge-case tests ----\n"
            + task["tests"]
            + "\nprint('ALL_TESTS_PASSED')\n"
        )
        res = await sandbox.execute(
            ExecutionRequest(code=full, language="python", timeout_seconds=15)
        )
        if res.exit_code == 0 and "ALL_TESTS_PASSED" in res.stdout:
            passed += 1
        else:
            detail = (res.stderr or res.stdout or "(无输出)").strip()
            fails.append({"sample": i, "why": f"exit={res.exit_code}", "detail": detail[-450:]})
    return {"id": task["id"], "passed": passed, "total": samples, "fails": fails}


async def run_probe(samples: int) -> dict:
    """跑完整代码探针，返回 JSON-able 汇总（per-task + total + pass_rate）。"""
    profile = get_profile("agent")
    model = default_turn_profiles().model_for("agent")
    provider = build_provider(_eval_credentials())
    sandbox = SubprocessSandbox()
    print(
        f"\n挖坑探针·代码必须真跑  model={model} "
        f"thinking={profile.thinking} samples={samples}\n"
    )
    tasks_out: list[dict] = []
    grand_pass = grand_total = 0
    try:
        for task in TASKS:
            r = await _run_task(
                task,
                profile=profile,
                model=model,
                provider=provider,
                sandbox=sandbox,
                samples=samples,
            )
            tasks_out.append(r)
            grand_pass += r["passed"]
            grand_total += r["total"]
            print(f"[{r['id']}] {r['passed']}/{r['total']} 通过")
            for f in r["fails"]:
                indented = str(f["detail"]).replace("\n", "\n        ")
                print(f"    ✗ sample {f['sample']}: {f['why']}\n        {indented}")
            print()
    finally:
        await _close(provider)
    pass_rate = grand_pass / grand_total if grand_total else 0.0
    print(f"==== TOTAL: {grand_pass}/{grand_total} 通过（{pass_rate * 100:.0f}%）====\n")
    return {
        "summary": {"passed": grand_pass, "total": grand_total, "pass_rate": pass_rate},
        "tasks": tasks_out,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="挖坑探针·代码必须真跑（生成→沙箱真跑隐藏边界用例）")
    p.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="每题重跑次数（默认 5）")
    p.add_argument("--out", default=None, help="把 JSON 汇总写到该路径（nightly 观测/上传）")
    p.add_argument(
        "--fail-under",
        type=float,
        default=0.9,
        help="总通过率低于该值则 exit 1（回归绊线；nightly 软门禁会吞掉退出码、仅留观测）",
    )
    args = p.parse_args(argv)

    report = asyncio.run(run_probe(args.samples))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[report] 已写出 JSON -> {out}")
    return 0 if report["summary"]["pass_rate"] >= args.fail_under else 1


if __name__ == "__main__":
    sys.exit(main())

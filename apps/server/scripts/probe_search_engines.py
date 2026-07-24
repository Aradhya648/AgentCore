"""Probe the configured SearXNG's per-engine health (C4 引擎池可达性巡检).

``web_search`` depends on a self-hosted SearXNG whose CN scraper engines (baidu/sogou/…)
get CAPTCHA-suspended under load from a datacenter IP — SearXNG then returns HTTP 200
with an EMPTY result set, so ``/healthz`` looks fine while every search comes back blank
(实测案例复盘 案例1；生产 2026-06-23 复盘). This script hits the SAME SearXNG the app
uses and reports, per engine, how many results it contributed plus which engines are
unresponsive (CAPTCHA / timeout) — the evidence to decide whether the pool needs a
restart or widening, and to verify a settings change after deploy.

Run from ``apps/server`` (reads ``SEARXNG_URL`` from settings/env)::

    uv run python scripts/probe_search_engines.py
    uv run python scripts/probe_search_engines.py --query 贝叶斯定理 --query 深圳天气
    uv run python scripts/probe_search_engines.py --engines baidu,360search   # only these
    uv run python scripts/probe_search_engines.py --url http://127.0.0.1:18888 # override host

Exit code 0 = at least one query returned results; 1 = all queries empty / SearXNG
unreachable (degraded). Suitable for a one-shot ops check or a post-deploy verification.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

import httpx

from agentcore.config import settings

# Generic, high-recall canaries: any working general engine returns hits for these, so an
# empty result means the engine pool is degraded — not that the query was too narrow.
_DEFAULT_QUERIES = ["新闻", "人工智能", "深圳天气"]
_TIMEOUT = 20.0
_CONNECT_TIMEOUT = 5.0


def _engines_of(result: dict) -> list[str]:
    """Which engines returned a result row (``engines`` list, or singular ``engine``)."""
    engines = result.get("engines")
    if engines:
        return [str(e) for e in engines]
    one = result.get("engine")
    return [str(one)] if one else []


def _name_reason(entry: object) -> tuple[str, str]:
    """Split a SearXNG ``unresponsive_engines`` entry (``[name, reason, ...]``)."""
    if isinstance(entry, (list, tuple)) and entry:
        name = str(entry[0])
        reason = str(entry[1]) if len(entry) > 1 else ""
        return name, reason
    return str(entry), ""


async def _probe_one(
    client: httpx.AsyncClient, base: str, query: str, engines: str | None
) -> dict:
    params: dict[str, str] = {"q": query, "format": "json", "safesearch": "0"}
    if engines:
        params["engines"] = engines
    resp = await client.get(f"{base}/search", params=params)
    resp.raise_for_status()
    return resp.json()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", action="append", dest="queries", help="自定义查询（可多次）；默认一组通用词"
    )
    parser.add_argument("--engines", default=None, help="逗号分隔，仅测这些引擎（默认测全部已启用引擎）")
    parser.add_argument("--url", default=None, help="覆盖 SEARXNG_URL（默认读配置）")
    args = parser.parse_args()

    queries = args.queries or _DEFAULT_QUERIES
    base = (args.url or settings.searxng_url).rstrip("/")

    print(f"[searxng] {base}")
    print(f"[queries] {queries}")
    if args.engines:
        print(f"[engines] {args.engines}")
    print()

    per_engine: Counter[str] = Counter()
    unresponsive: Counter[str] = Counter()
    total_results = 0
    any_ok = False

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_TIMEOUT, connect=_CONNECT_TIMEOUT)
    ) as client:
        for q in queries:
            try:
                data = await _probe_one(client, base, q, args.engines)
            except httpx.HTTPError as e:
                print(f"  ✗ {q!r}: 请求失败 {type(e).__name__}: {e}")
                continue
            results = data.get("results") or []
            ue = [_name_reason(x) for x in (data.get("unresponsive_engines") or [])]
            total_results += len(results)
            any_ok = any_ok or bool(results)
            for r in results:
                for eng in _engines_of(r):
                    per_engine[eng] += 1
            for name, reason in ue:
                unresponsive[f"{name}: {reason}" if reason else name] += 1
            ue_note = f"，unresponsive={[n for n, _ in ue]}" if ue else ""
            print(f"  {'✓' if results else '✗'} {q!r}: {len(results)} 条{ue_note}")

    print("\n==== 每引擎贡献结果数（按查询累计，去重前）====")
    if per_engine:
        for eng, n in per_engine.most_common():
            print(f"  {eng:14} {n}")
    else:
        print("  （无引擎返回任何结果）")

    if unresponsive:
        print("\n==== 不可用引擎（CAPTCHA / 超时）====")
        for label, n in unresponsive.most_common():
            print(f"  ×{n}  {label}")

    print(f"\n[total] {total_results} 条结果 / {len(queries)} 个查询")
    if not any_ok:
        print(
            "[degraded] 所有查询都返回空 —— 引擎池全军覆没（CAPTCHA/封禁）或 SearXNG 不可达；"
            "考虑重启 agentcore-searxng 或拓宽引擎池"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""引用质量：域名分级、引用池入库过滤、检索观测字段。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.runtime.citations import (
    citation_pool_admissible,
    citation_tier_for_url,
    merge_citations,
    stamp_citation_tier,
)
from agentcore.tools.builtin.web.search import WebSearchTool
from agentcore.tools.builtin.web.search_backend import SearchResult
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-test",
    )


# ── tier 判定（含中文媒体名单补齐）──────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "tier"),
    [
        ("https://wenshu.court.gov.cn/case/1", "official"),
        ("https://www.gov.cn/zhengce/xxx.htm", "official"),
        ("https://www.reuters.com/world/foo", "media"),
        ("https://www.caixin.com/a/b", "media"),
        ("https://www.bjnews.com.cn/detail/1.html", "media"),
        ("https://www.chinanews.com.cn/gn/2024/01-01/1.shtml", "media"),
        ("https://zh.wikipedia.org/wiki/X", "unknown"),
        ("https://random-blog.example/post", "unknown"),
        ("https://yunqi.qq.com/book/tft", "unknown"),
        ("", "unknown"),
    ],
)
def test_citation_tier_allow_list(url: str, tier: str) -> None:
    assert citation_tier_for_url(url) == tier


@pytest.mark.parametrize(
    "url",
    [
        "https://zhidao.baidu.com/question/123",
        "https://www.baidu.com/",
        "https://baidu.com/s?wd=海洋垃圾",
        "https://browser.qq.com/search?q=x",
        "https://www.bing.com/",
        "https://www.google.com/search?q=x",
        "https://wenwen.sogou.com/z/q123.htm",
        # 中日文词典站（根域后缀匹配含子域）
        "https://www.weblio.jp/content/茉莉花",
        "https://ejje.weblio.jp/content/jasmine",
        "https://kotobank.jp/word/茉莉花",
        "https://www.kotobank.jp/word/x",
        "https://jitenon.jp/kanji/x",
        "https://kanji.jitenon.jp/kanji/1",
    ],
)
def test_citation_tier_hard_block(url: str) -> None:
    assert citation_tier_for_url(url) == "blocked"
    assert not citation_pool_admissible(citation_tier_for_url(url))


@pytest.mark.parametrize(
    "url",
    [
        "https://wenku.baidu.com/view/abc",
        "https://baijiahao.baidu.com/s?id=1",
        "https://easylearn.baidu.com/edu",
        "https://www.zhihu.com/question/1",
        "https://blog.csdn.net/u/1",
        "https://www.jianshu.com/p/1",
    ],
)
def test_citation_tier_weak_demote(url: str) -> None:
    assert citation_tier_for_url(url) == "weak"
    # P2：weak 可进 mid-turn sink / 可被 #rN 引用；仅 blocked 拒收
    assert citation_pool_admissible("weak")


def test_baidu_subdomains_not_blanket_blocked() -> None:
    """``baidu.com`` 精确硬拦不得把文库等子域一并判 blocked（子域走 weak）。"""
    assert citation_tier_for_url("https://wenku.baidu.com/view/x") == "weak"
    assert citation_tier_for_url("https://www.baidu.com/") == "blocked"


# ── 入库过滤（P2：仅拒 blocked；卡片投影另测）──────────────────────────────


def test_merge_citations_hard_blocks_and_stamps_tier() -> None:
    sink: list[dict] = []
    numbers = merge_citations(
        sink,
        [
            {
                "url": "https://zhidao.baidu.com/question/1",
                "title": "知道",
                "site": "zhidao.baidu.com",
            },
            {
                "url": "https://www.bjnews.com.cn/detail/1.html",
                "title": "新京报",
                "site": "bjnews.com.cn",
            },
            {
                "url": "https://www.baidu.com/",
                "title": "百度",
                "site": "baidu.com",
            },
        ],
    )
    assert [c["url"] for c in sink] == ["https://www.bjnews.com.cn/detail/1.html"]
    assert sink[0]["tier"] == "media"
    assert numbers == {"https://www.bjnews.com.cn/detail/1.html": 1}


def test_merge_citations_admits_weak_and_unknown() -> None:
    sink: list[dict] = []
    merge_citations(
        sink,
        [
            {
                "url": "https://wenku.baidu.com/view/x",
                "title": "文库",
                "site": "wenku.baidu.com",
            },
            {
                "url": "https://zml.tzc.edu.cn/info/1.htm",
                "title": "高校页",
                "site": "zml.tzc.edu.cn",
            },
            {
                "url": "https://baijiahao.baidu.com/s?id=1",
                "title": "百家号",
                "site": "baijiahao.baidu.com",
            },
        ],
    )
    assert [c["url"] for c in sink] == [
        "https://wenku.baidu.com/view/x",
        "https://zml.tzc.edu.cn/info/1.htm",
        "https://baijiahao.baidu.com/s?id=1",
    ]
    assert sink[0]["tier"] == "weak"
    assert sink[1]["tier"] == "unknown"
    assert sink[2]["tier"] == "weak"


def test_stamp_citation_tier_preserves_explicit() -> None:
    c = {"url": "https://example.com/a", "title": "A", "tier": "media"}
    assert stamp_citation_tier(c)["tier"] == "media"


# ── web_search：硬拦剔除 + 观测字段 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_filters_blocked_and_logs_hosts(monkeypatch) -> None:
    from agentcore.tools.builtin.web import search as search_mod

    logged: list[dict] = []

    def _capture(event: str, **kwargs):
        logged.append({"event": event, **kwargs})

    monkeypatch.setattr(search_mod.logger, "info", _capture)

    class _FakeBackend:
        async def search(self, query, max_results=5, on_phase=None, *, language=None):
            return [
                SearchResult("海洋垃圾 塑料 知道", "https://zhidao.baidu.com/question/1", "海洋垃圾 ugc"),
                SearchResult(
                    "海洋垃圾 塑料污染",
                    "https://www.bjnews.com.cn/detail/1.html",
                    "海洋垃圾与塑料污染报道",
                ),
                SearchResult("海洋垃圾 文库", "https://wenku.baidu.com/view/x", "海洋垃圾 weak"),
                SearchResult("海洋垃圾 首页", "https://www.baidu.com/", "海洋垃圾 home"),
            ]

    monkeypatch.setattr(search_mod, "get_search_backend", lambda: _FakeBackend())
    result = await WebSearchTool().execute({"query": "海洋垃圾 塑料"}, _ctx())

    assert result.success is True
    urls = [c["url"] for c in (result.citations or [])]
    assert "https://zhidao.baidu.com/question/1" not in urls
    assert "https://www.baidu.com/" not in urls
    assert "https://www.bjnews.com.cn/detail/1.html" in urls
    # weak 仍回模型（检索可见）；P2 可被显式引用
    assert "https://wenku.baidu.com/view/x" in urls
    assert result.metadata["query"] == "海洋垃圾 塑料"
    assert "bjnews.com.cn" in result.metadata["hosts"]
    assert "zhidao.baidu.com" in result.metadata.get("blocked_hosts", [])

    search_events = [e for e in logged if e.get("event") == "tool.web_search"]
    assert len(search_events) == 1
    assert search_events[0]["query"] == "海洋垃圾 塑料"
    assert "bjnews.com.cn" in search_events[0]["hosts"]
    assert search_events[0]["blocked_count"] == 2


@pytest.mark.asyncio
async def test_web_search_citations_carry_tier(monkeypatch) -> None:
    from agentcore.tools.builtin.web import search as search_mod

    class _FakeBackend:
        async def search(self, query, max_results=5, on_phase=None, *, language=None):
            return [
                SearchResult("深圳天气 标题一", "https://www.example.com/a", "深圳天气 摘要一"),
                SearchResult(
                    "深圳天气 新京报",
                    "https://www.bjnews.com.cn/detail/1.html",
                    "深圳天气 摘要二",
                ),
            ]

    monkeypatch.setattr(search_mod, "get_search_backend", lambda: _FakeBackend())
    result = await WebSearchTool().execute({"query": "深圳天气"}, _ctx())
    by_url = {c["url"]: c for c in (result.citations or [])}
    assert by_url["https://www.example.com/a"]["tier"] == "unknown"
    assert by_url["https://www.bjnews.com.cn/detail/1.html"]["tier"] == "media"

"""Built-in tool: read_url (fetch a web page and extract its main text)."""

import contextlib
import json
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from agentcore.config import settings
from agentcore.core.citation_tier import stamp_citation_tier
from agentcore.core.logging import get_logger
from agentcore.core.net import (
    EgressError,
    PinnedAddressError,
    PinnedIPTransport,
    describe_net_error,
    site_of,
    web_timeout,
)
from agentcore.core.net import (
    classify_url as _classify_url,
)
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.builtin.web._net import (
    circuit_remaining,
    note_failure,
    note_success,
    read_url_retire_message,
)
from agentcore.tools.builtin.web.github_page import try_fetch_github_page
from agentcore.tools.builtin.web.source_domains import default_source_domain_registry
from agentcore.tools.builtin.web.url_cache import (
    UrlCacheEntry,
    default_url_cache_registry,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)

_DEFAULT_MAX_CHARS = 8000
_MAX_CHARS_CAP = 30000
_MAX_REDIRECTS = 5
_SNIPPET_MAX = 200  # citation preview length — a sentence or two, not the whole lead
# Query-string length (chars) above which a read of a NOVEL domain is treated as a
# possible exfil beacon (PI-002): a fabricated ``?d=<secret>`` rides the query, while
# legitimate article URLs rarely carry a 64+ char opaque query. The query-length AND
# novel-domain conjunction keeps the common search→deep-read and plain-URL reads quiet.
_SUSPICIOUS_QUERY_LEN = 64
# Novel-domain exfil refusal is a true policy block (tool is fine; call refused).
# SSRF / host-circuit / transport hard-fails are NOT policy_failure: continuous
# environmental failures must feed the run-scoped circuit breaker so research
# workers stop empty-spinning after stall→Wave retry (P1 2026-07-29).
_POLICY_FAILURE = "policy_failure"
# Shared stop-read trailer for hard-dead fetch classes (403/404/timeout/SSRF/egress).
_STOP_READ_HINT = (
    "——请停止对该来源换 URL / 同策略重试；基于已有 web_search 摘要与已读材料收口写作，"
    "不要再空转外网深读"
)


def _query_len(url: str) -> int:
    """Length of the URL's query component (exfil-bandwidth proxy); 0 if unparseable."""
    try:
        return len(urlparse(url).query or "")
    except ValueError:
        return 0


async def _is_safe_url(url: str) -> bool:
    """Bool 包装：重定向逐跳重校验（``_safe_request``）。

    引用本模块级 ``_classify_url``（从 :mod:`agentcore.core.net` 导入的别名），
    以便 ``test_web_tools`` 对 ``read_url._classify_url`` 的 monkeypatch 仍生效。
    """
    return await _classify_url(url) is None


async def _safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_redirects: int = _MAX_REDIRECTS,
    **kwargs: Any,
) -> httpx.Response:
    """逐跳重校验的请求：每个重定向目标都重新过 SSRF 检查。

    client 必须以 follow_redirects=False 创建，否则 httpx 会自动跟随、
    使得「公网 URL 302 到内网 IP」绕过检查。命中拦截或超跳数则抛 ValueError。

    出网韧性（受限环境）：按原始请求主机做熔断——近期连续传输失败的主机会被
    临时短路（抛 EgressError 快速失败，不再空耗整个超时窗口）；传输失败计入熔断、
    成功则清零。仅传输层错误（连接/超时/网络）计数，HTTP 4xx/5xx 由调用方处理、
    不视为出网故障。
    """
    request = client.build_request(method, url, **kwargs)
    host = (request.url.host or "").lower()
    remaining = circuit_remaining(host)
    if remaining > 0:
        raise EgressError(
            f"站点 {host} 近期连续访问失败，已临时熔断约 {int(remaining)}s"
            "（出网受限或站点不可达），暂不重试"
        )
    for _ in range(max_redirects + 1):
        if not await _is_safe_url(str(request.url)):
            raise ValueError("URL blocked: private/internal network")
        try:
            resp = await client.send(request)
        except httpx.TimeoutException:
            note_failure(host)
            raise
        except httpx.NetworkError as e:
            # SSRF pin blocks are policy, not transport — must not open the per-host breaker.
            if not isinstance(e, PinnedAddressError):
                note_failure(host)
            raise
        nxt = resp.next_request
        if resp.is_redirect and nxt is not None:
            await resp.aclose()
            request = nxt
            continue
        note_success(host)
        return resp
    raise ValueError("Too many redirects")


class _TextExtractor(HTMLParser):
    """Minimal stdlib HTML→text extractor: drops scripts/styles, keeps the title,
    and inserts newlines at block boundaries (no third-party dependency)."""

    # Drop scripts/styles plus page chrome (nav/header/footer/aside) so both the
    # extracted body text and the fallback citation snippet skip boilerplate menus
    # and footers instead of leading with a navigation bar.
    SKIP_TAGS = frozenset(
        {
            "script",
            "style",
            "noscript",
            "svg",
            "head",
            "nav",
            "header",
            "footer",
            "aside",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False
        # First page-level description meta — a ready-made one-line summary, better
        # for a citation preview than the (often boilerplate-led) body text.
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta" and not self.description:
            a = {k.lower(): (v or "") for k, v in attrs}
            key = a.get("name", "").lower() or a.get("property", "").lower()
            if key in ("description", "og:description", "twitter:description"):
                self.description = a.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._skip_depth == 0:
            self.parts.append(data)


def _extract_page(html: str, max_chars: int) -> tuple[str, str, str]:
    """Return ``(title, text, description)`` from raw HTML; text capped to max_chars.

    ``description`` is the page's ``<meta>`` description (empty when absent) — used to
    seed a citation snippet so a read source still previews on hover.
    """
    extractor = _TextExtractor()
    with contextlib.suppress(Exception):
        extractor.feed(html)
    raw = "".join(extractor.parts)
    text = re.sub(r"\n{3,}", "\n\n", raw).strip()[:max_chars]
    return extractor.title, text, extractor.description


def _extract_text(html: str, max_chars: int) -> tuple[str, str]:
    """Back-compat ``(title, text)`` wrapper over :func:`_extract_page`."""
    title, text, _ = _extract_page(html, max_chars)
    return title, text


def _make_snippet(description: str, text: str) -> str:
    """A short citation preview: prefer the meta description, else the text lead.

    Whitespace is collapsed and the result capped to :data:`_SNIPPET_MAX` so the
    hover card shows a clean sentence-or-two, not a wall of body text.
    """
    source = description.strip() or text.strip()
    return re.sub(r"\s+", " ", source)[:_SNIPPET_MAX].strip()


def _make_display(
    *,
    url: str,
    title: str,
    site: str,
    snippet: str,
    content: str,
) -> dict[str, Any]:
    """Render-oriented twin of the model-facing JSON output (工具结果富渲染).

    The desktop shows a source-style card header (favicon · title · site) plus a
    body preview from ``content`` — same display channel as ``web_search``, so the
    client never parses the JSON ``output`` string.
    """
    return {
        "url": url,
        "title": title,
        "site": site,
        "snippet": snippet,
        "content": content,
    }


class ReadUrlTool:
    """Fetch a web page and return its extracted main text."""

    registration = ToolRegistration(
        surface=ToolSurface.BUILTIN,
        audience=AUDIENCE_BOTH,
    )

    @staticmethod
    def _guard_novel_domain_exfil(url: str, conversation_id: str) -> str | None:
        """Observe (and, under the opt-in flag, refuse) the novel-domain exfil pattern.

        Indirect prompt injection can drive read_url to ``https://attacker/?d=<secret>``
        — the SSRF guard blocks only INTERNAL targets, so a public exfil URL passes. The
        deterministic tell: a legitimate deep-read targets a domain ``web_search``
        surfaced this conversation, while an exfil URL is a model-fabricated NOVEL domain
        carrying a long opaque query (the secret). When both hold, log it (always, for
        observability) and refuse it when ``read_url_block_novel_query`` is on.

        Returns an honest model-facing error string to BLOCK, else ``None`` (allow).
        Skipped for unscoped calls (no per-conversation source set to compare against)
        and for short / absent query strings (no meaningful exfil bandwidth) — so the
        common search→deep-read and plain-URL reads are untouched. Path-based exfil to a
        novel domain with no query is a known residual gap (closing it needs novel-domain
        approval, a heavier UX trade-off — 项目审计-提示注入专项 §五 PI-002).
        """
        if not conversation_id:
            return None
        query_len = _query_len(url)
        if query_len < _SUSPICIOUS_QUERY_LEN:
            return None
        domain = site_of(url)
        if not domain:
            return None
        if default_source_domain_registry().has_domain(conversation_id, domain):
            return None
        logger.warning(
            "tool.read_url_novel_domain",
            url=url[:200],
            site=domain,
            query_len=query_len,
            conversation_id=conversation_id,
            blocked=settings.read_url_block_novel_query,
        )
        if settings.read_url_block_novel_query:
            return (
                "[ERROR] 该链接指向本会话检索结果之外的新域名且携带较长查询参数，"
                "已按出网外泄防护拦截。如确需读取该来源，请先用 web_search 找到它，"
                "或请用户直接提供链接。"
            )
        return None

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_url",
            description=(
                "获取指定网页的正文文本（比 web_search 摘要更完整，但长页面会按 "
                "max_chars 截断），用于在 web_search 摘要不足、确需深读某条结果时。"
                "默认摘要优先：多数问题先用 web_search 摘要作答；"
                "任务要求核对原文或需要正文细节时再调用本工具深读。"
                "注意：部分大型站点（如百度百科、知乎等）有反爬保护，可能返回 403/失败——"
                "此时改用 web_search 摘要或换其他来源，不要对同一被拒站点反复重试。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要读取的网页 URL"},
                    "max_chars": {
                        "type": "integer",
                        "description": "返回的最大字符数，默认 8000",
                    },
                },
                "required": ["url"],
            },
            category=ToolCategory.RESEARCH,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        url = (arguments.get("url") or "").strip()
        if not url:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="缺少必填参数：url",
                duration_ms=0,
            )

        # Run-scoped retirement (survives react_loop restart after stream-stall /
        # Wave retry): refuse without fetching and re-trip the loop breaker.
        retire_msg = read_url_retire_message(context.run_id)
        if retire_msg:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=f"网页读取失败：{retire_msg}",
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={
                    "retire_tools": ["read_url"],
                    # CircuitBreak.message() prefixes ``[系统提示]`` once.
                    "retire_message": retire_msg,
                },
            )

        block = await _classify_url(url)
        if block is not None:
            # SSRF / DNS / blocked-host: count toward the run breaker (not policy_failure)
            # so consecutive environmental refusals hard-stop empty URL thrashing.
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=f"{block.value}{_STOP_READ_HINT}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            raw_max = int(arguments.get("max_chars", _DEFAULT_MAX_CHARS))
            max_chars = max(1, min(raw_max, _MAX_CHARS_CAP))
        except (TypeError, ValueError):
            max_chars = _DEFAULT_MAX_CHARS

        # Conversation-scoped fetch cache: a repeat read of the same page within the
        # conversation is served from memory (within a freshness TTL) instead of
        # re-fetching. Only successful fetches are cached, so a hit's URL already
        # passed the SSRF gate above; unscoped call sites (conversation_id == "")
        # skip the cache entirely.
        cache = (
            default_url_cache_registry().get_or_create(context.conversation_id)
            if context.conversation_id
            else None
        )
        if cache is not None:
            cached = cache.get(url, min_chars=max_chars)
            if cached is not None:
                text = cached.content[:max_chars]
                output = json.dumps(
                    {"url": url, "title": cached.title, "content": text},
                    ensure_ascii=False,
                )
                logger.info("tool.read_url_cache_hit", url=url, content_chars=len(text))
                return ToolResult(
                    tool_call_id="",
                    success=True,
                    output=output,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    output_limit=max_chars + 1024,
                    metadata={
                        "title": cached.title,
                        "content_chars": len(text),
                        "cached": True,
                    },
                    citations=[
                        stamp_citation_tier(
                            {
                                "url": url,
                                "title": cached.title,
                                "snippet": cached.snippet,
                                "site": cached.site,
                                "deep_read": True,
                            }
                        )
                    ],
                    display=_make_display(
                        url=url,
                        title=cached.title,
                        site=cached.site,
                        snippet=cached.snippet,
                        content=text,
                    ),
                )

        # PI-002 出网外泄观测：only reached on a cache MISS (a real outbound fetch is about
        # to happen). A model-fabricated novel domain carrying a long opaque query is the
        # indirect-injection exfil tell — always logged, refused only under the opt-in flag.
        exfil_block = self._guard_novel_domain_exfil(url, context.conversation_id)
        if exfil_block is not None:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=exfil_block,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={_POLICY_FAILURE: True},
            )

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AgentCore/1.0; +https://agentcore.dev)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        # 工具执行阶段进度 (联网前端展示优化): signal the slow blocking leg so the waiting row
        # is live, not a dead spinner — and stay honest about egress control. If THIS host's
        # circuit is OPEN, ``_safe_request`` is about to fast-fail (EgressError), NOT queue —
        # so report「出网受限·快速失败」(blocked) rather than a fake「正在抓取」/「排队」; read_url
        # has no token-bucket/semaphore wait, so it never has a real「排队」state. Otherwise the
        # fetch proceeds → 「正在抓取网页」. Best-effort; ``on_phase`` is None on unscoped call
        # sites (tests / evals). Enforcement stays in ``_safe_request`` (single source of truth);
        # this is an observe-only mirror of the same breaker state.
        if context.on_phase:
            host = (urlparse(url).hostname or "").lower()
            context.on_phase("blocked" if circuit_remaining(host) > 0 else "fetching")
        used_github_api = False
        try:
            # PinnedIPTransport: connect to the IP we validated, closing the DNS-rebinding
            # TOCTOU between the per-hop classify_url check and httpx's own resolution.
            # verify=False: tolerate broken cert chains on gov/court/academic mirrors
            # (same posture as the favicon proxy). SSRF pinning still bounds which hosts
            # we reach; only TLS trust is relaxed.
            async with httpx.AsyncClient(
                timeout=web_timeout(),
                follow_redirects=False,
                transport=PinnedIPTransport(verify=False),
            ) as client:
                # github.com/{owner}/{repo} (root/tree/blob): prefer api.github.com so a
                # HTML connect timeout is not misread as "private repo". Match miss or
                # API failure → fall through to the HTML path below (same SSRF/breaker).
                github_page = await try_fetch_github_page(
                    client, url, max_chars, safe_request=_safe_request
                )
                if github_page is not None:
                    title, text, description = github_page
                    used_github_api = True
                else:
                    resp = await _safe_request(client, "GET", url, headers=headers)
                    resp.raise_for_status()
                    html = resp.text
                    # 工具执行阶段进度: fetched — now parse/extract the main text (可感知的第二段，
                    # 长页面抽取有耗时). Signals「正在提取正文」.
                    if context.on_phase:
                        context.on_phase("reading")
                    title, text, description = _extract_page(html, max_chars)
        except Exception as e:
            reason = describe_net_error(e)
            logger.warning("tool.read_url_error", url=url, error=reason, error_repr=repr(e))
            # Hard-dead classes (anti-crawl / 404 / timeout / connect / host-circuit /
            # pinned SSRF): retries and URL thrashing do not help. Steer toward
            # existing materials; these failures COUNT toward the run circuit breaker
            # (no policy_failure) so Wave/contract restarts still trip disable.
            hint = _STOP_READ_HINT
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (
                401,
                403,
                429,
                451,
            ):
                hint = (
                    "。该站点反爬 / 拒绝访问，换 URL 或重试都读不到"
                    f"{_STOP_READ_HINT}"
                )
            elif isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
                hint = f"。页面不存在（404）{_STOP_READ_HINT}"
            elif isinstance(e, (EgressError, PinnedAddressError)):
                hint = f"。出网受限或地址不可达{_STOP_READ_HINT}"
            elif isinstance(
                e,
                (
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.ConnectError,
                    httpx.NetworkError,
                    httpx.TimeoutException,
                ),
            ):
                hint = f"。连接/读取失败{_STOP_READ_HINT}"
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=f"网页读取失败：{reason}{hint}",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        # GitHub API path has no HTML extract leg; still advance the phase row once.
        if context.on_phase and used_github_api:
            context.on_phase("reading")
        snippet = _make_snippet(description, text)
        site = site_of(url)
        if cache is not None:
            cache.put(
                UrlCacheEntry(
                    url=url,
                    title=title,
                    content=text,
                    snippet=snippet,
                    site=site,
                    max_chars=max_chars,
                    truncated=len(text) >= max_chars,
                    stored_at=time.time(),
                )
            )
        output = json.dumps({"url": url, "title": title, "content": text}, ensure_ascii=False)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=int((time.monotonic() - start) * 1000),
            output_limit=max_chars + 1024,
            metadata={"title": title, "content_chars": len(text)},
            citations=[
                stamp_citation_tier(
                    {
                        "url": url,
                        "title": title,
                        "snippet": snippet,
                        "site": site,
                        "deep_read": True,
                    }
                )
            ],
            display=_make_display(
                url=url,
                title=title,
                site=site,
                snippet=snippet,
                content=text,
            ),
        )

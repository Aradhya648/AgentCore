"""平台层证据台账共享核——登记 / 去重 / tier / 元数据 / 原子 id。

与辩论场级封装（:mod:`agentcore.runtime.debate.evidence_ledger`）及后续回合级
调研台账共用本核。条目模型见提案《引用即出处》§二。

规则：
- append-only；id = ``{prefix}{n}``（登记序，默认 ``#e``）
- 同 URL（:func:`normalize_citation_url`）去重 → 返回既有 id
- 空 URL（底料等）按归一化 title 去重
- ``tier`` 单源 :func:`citation_tier_for_url`；``blocked`` 默拒登记
- ``citable``：P2 起已登记档（含 ``weak``）均为 ``True``；``blocked`` 不进台账
- asyncio 单进程内对分配路径加锁，支撑并行登记不撞号
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from agentcore.runtime.citations import citation_tier_for_url, normalize_citation_url


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", "", (title or "").strip().casefold())


def citable_for_tier(tier: str) -> bool:
    """P2：已登记档均可 ``#rN`` / ``#eN`` 引用（含 ``weak``）；``blocked`` 不进台账。"""
    return tier != "blocked"


@dataclass
class EvidenceLedgerCore:
    """回合 / 场级共享台账核：线程外 asyncio 单进程加锁分配 id。"""

    id_prefix: str = "#e"
    reject_blocked: bool = True
    _entries: list[dict[str, Any]] = field(default_factory=list)
    _by_url: dict[str, str] = field(default_factory=dict)
    _by_title: dict[str, str] = field(default_factory=dict)
    _cursor: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(e["id"] for e in self._entries)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        for e in self._entries:
            if e["id"] == entry_id:
                return dict(e)
        return None

    def all_entries(self) -> list[dict[str, Any]]:
        """全量台账快照（含元数据字段）。"""
        return [dict(e) for e in self._entries]

    def citable_ids(self) -> frozenset[str]:
        """允许被 id 引用的条目 id 集（``citable=true``）。"""
        return frozenset(e["id"] for e in self._entries if e.get("citable"))

    def load_entries(self, entries: list[dict[str, Any]]) -> None:
        """从 pause 快照再水化台账（保留既有 id，后续登记续号）。

        ``_cursor`` 置到末尾，避免把快照条目当成新 delta 重放。
        """
        self._entries = []
        self._by_url = {}
        self._by_title = {}
        self._cursor = 0
        for raw in entries or []:
            if not isinstance(raw, dict):
                continue
            entry_id = str(raw.get("id") or "").strip()
            if not entry_id:
                continue
            norm_url = normalize_citation_url(str(raw.get("url") or ""))
            title = str(raw.get("title") or "")
            tier = str(raw.get("tier") or "unknown")
            entry = {
                "id": entry_id,
                "url": norm_url or str(raw.get("url") or ""),
                "title": title,
                "snippet": str(raw.get("snippet") or ""),
                "site": str(raw.get("site") or ""),
                "date": str(raw.get("date") or ""),
                "tier": tier,
                "query": str(raw.get("query") or ""),
                "deep_read": bool(raw.get("deep_read")),
                "registrant": str(raw.get("registrant") or ""),
                "citable": bool(raw["citable"])
                if "citable" in raw
                else citable_for_tier(tier),
                "dossier_path": str(raw.get("dossier_path") or ""),
                "origin_id": str(raw.get("origin_id") or ""),
                "dossier_label": str(raw.get("dossier_label") or ""),
            }
            self._entries.append(entry)
            if norm_url:
                self._by_url[norm_url] = entry_id
            else:
                title_key = _norm_title(title)
                if title_key:
                    self._by_title[title_key] = entry_id
        self._cursor = len(self._entries)

    def drain_delta(self) -> list[dict[str, Any]]:
        """自上次 drain 以来的新登记条目。"""
        delta = [dict(e) for e in self._entries[self._cursor :]]
        self._cursor = len(self._entries)
        return delta

    async def register(
        self,
        *,
        url: str = "",
        title: str = "",
        snippet: str = "",
        site: str = "",
        date: str = "",
        registrant: str,
        tier: str | None = None,
        query: str = "",
        deep_read: bool = False,
        dossier_path: str = "",
        origin_id: str = "",
        dossier_label: str = "",
    ) -> str | None:
        """异步登记（持锁）；``blocked`` 且 ``reject_blocked`` 时返回 ``None``。"""
        async with self._lock:
            return self._register_unlocked(
                url=url,
                title=title,
                snippet=snippet,
                site=site,
                date=date,
                registrant=registrant,
                tier=tier,
                query=query,
                deep_read=deep_read,
                dossier_path=dossier_path,
                origin_id=origin_id,
                dossier_label=dossier_label,
            )

    def register_sync(
        self,
        *,
        url: str = "",
        title: str = "",
        snippet: str = "",
        site: str = "",
        date: str = "",
        registrant: str,
        tier: str | None = None,
        query: str = "",
        deep_read: bool = False,
        dossier_path: str = "",
        origin_id: str = "",
        dossier_label: str = "",
    ) -> str | None:
        """同步登记。

        供单协程调用方（辩论编排）。并行 worker 须用 :meth:`register`，否则
        跨 await 交错时可能撞号。
        """
        return self._register_unlocked(
            url=url,
            title=title,
            snippet=snippet,
            site=site,
            date=date,
            registrant=registrant,
            tier=tier,
            query=query,
            deep_read=deep_read,
            dossier_path=dossier_path,
            origin_id=origin_id,
            dossier_label=dossier_label,
        )

    async def register_citation(
        self, citation: dict[str, Any], *, registrant: str
    ) -> str | None:
        """从工具 citation dict 异步登记。"""
        return await self.register(
            url=str(citation.get("url") or ""),
            title=str(citation.get("title") or ""),
            snippet=str(citation.get("snippet") or ""),
            site=str(citation.get("site") or ""),
            date=str(citation.get("date") or ""),
            registrant=registrant,
            tier=citation.get("tier") if isinstance(citation.get("tier"), str) else None,
            query=str(citation.get("query") or ""),
            deep_read=bool(citation.get("deep_read")),
        )

    def register_citation_sync(
        self, citation: dict[str, Any], *, registrant: str
    ) -> str | None:
        """从工具 citation dict 同步登记。"""
        return self.register_sync(
            url=str(citation.get("url") or ""),
            title=str(citation.get("title") or ""),
            snippet=str(citation.get("snippet") or ""),
            site=str(citation.get("site") or ""),
            date=str(citation.get("date") or ""),
            registrant=registrant,
            tier=citation.get("tier") if isinstance(citation.get("tier"), str) else None,
            query=str(citation.get("query") or ""),
            deep_read=bool(citation.get("deep_read")),
        )

    async def register_citations(
        self, citations: list[dict[str, Any]], *, registrant: str
    ) -> list[str]:
        """批量异步登记；跳过拒登记项；返回成功 id（含去重命中）。"""
        out: list[str] = []
        async with self._lock:
            for c in citations:
                eid = self._register_unlocked(
                    url=str(c.get("url") or ""),
                    title=str(c.get("title") or ""),
                    snippet=str(c.get("snippet") or ""),
                    site=str(c.get("site") or ""),
                    date=str(c.get("date") or ""),
                    registrant=registrant,
                    tier=c.get("tier") if isinstance(c.get("tier"), str) else None,
                    query=str(c.get("query") or ""),
                    deep_read=bool(c.get("deep_read")),
                )
                if eid is not None:
                    out.append(eid)
        return out

    def register_citations_sync(
        self, citations: list[dict[str, Any]], *, registrant: str
    ) -> list[str]:
        """批量同步登记；跳过拒登记项。"""
        out: list[str] = []
        for c in citations:
            eid = self.register_citation_sync(c, registrant=registrant)
            if eid is not None:
                out.append(eid)
        return out

    def _register_unlocked(
        self,
        *,
        url: str = "",
        title: str = "",
        snippet: str = "",
        site: str = "",
        date: str = "",
        registrant: str,
        tier: str | None = None,
        query: str = "",
        deep_read: bool = False,
        dossier_path: str = "",
        origin_id: str = "",
        dossier_label: str = "",
    ) -> str | None:
        norm_url = normalize_citation_url(url)
        url_tier = citation_tier_for_url(norm_url)
        # 空串 / None 均回退 URL 分级（对齐原辩论 register 的 ``tier or …``）。
        resolved_tier = tier or url_tier
        if self.reject_blocked and (
            url_tier == "blocked" or resolved_tier == "blocked"
        ):
            return None

        if norm_url:
            existing = self._by_url.get(norm_url)
            if existing is not None:
                self._upgrade_existing(
                    existing,
                    query=query,
                    deep_read=deep_read,
                    dossier_path=dossier_path,
                    origin_id=origin_id,
                    dossier_label=dossier_label,
                )
                return existing
        else:
            title_key = _norm_title(title)
            if title_key:
                existing = self._by_title.get(title_key)
                if existing is not None:
                    self._upgrade_existing(
                        existing,
                        query=query,
                        deep_read=deep_read,
                        dossier_path=dossier_path,
                        origin_id=origin_id,
                        dossier_label=dossier_label,
                    )
                    return existing

        entry_id = f"{self.id_prefix}{len(self._entries) + 1}"
        if not site and norm_url:
            site = urlparse(norm_url).netloc.removeprefix("www.")
        entry = {
            "id": entry_id,
            "url": norm_url or (url or ""),
            "title": title or "",
            "snippet": snippet or "",
            "site": site or "",
            "date": date or "",
            "tier": resolved_tier,
            "query": query or "",
            "deep_read": bool(deep_read),
            "registrant": registrant,
            "citable": citable_for_tier(resolved_tier),
            "dossier_path": dossier_path or "",
            "origin_id": origin_id or "",
            "dossier_label": dossier_label or "",
        }
        self._entries.append(entry)
        if norm_url:
            self._by_url[norm_url] = entry_id
        else:
            title_key = _norm_title(title)
            if title_key:
                self._by_title[title_key] = entry_id
        return entry_id

    def _upgrade_existing(
        self,
        entry_id: str,
        *,
        query: str = "",
        deep_read: bool = False,
        dossier_path: str = "",
        origin_id: str = "",
        dossier_label: str = "",
    ) -> None:
        """同 URL / 底料去重命中时：``read_url`` 可升级 ``deep_read``；空字段可补填。"""
        if not (
            deep_read or query or dossier_path or origin_id or dossier_label
        ):
            return
        for e in self._entries:
            if e["id"] != entry_id:
                continue
            if deep_read and not e.get("deep_read"):
                e["deep_read"] = True
            if query and not (e.get("query") or "").strip():
                e["query"] = query
            if dossier_path and not (e.get("dossier_path") or "").strip():
                e["dossier_path"] = dossier_path
            if origin_id and not (e.get("origin_id") or "").strip():
                e["origin_id"] = origin_id
            if dossier_label and not (e.get("dossier_label") or "").strip():
                e["dossier_label"] = dossier_label
            return

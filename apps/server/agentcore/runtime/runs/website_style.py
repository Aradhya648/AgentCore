"""Website style confirmation ledger + DESIGN.md helpers (P1a dual-gate).

Unique source for the user-selected ``style_id`` after ask_user resume (or the
full_auto default). Resume wire priority: explicit ``style_id`` → legitimate
``sN`` in ``selected``; prose note alone never confirms. Playbook ``design``
injects it; ``web_quality_scan`` hard-fails when DESIGN.md lacks the marker.
Keyed on conversation — gate on ``build_website`` / ``build_toolshed`` so non-site
delegates stay untouched.

Persistence (方案 A · 与挂起恢复同构):
- Durable fact ``website_style_confirmed`` via :func:`record_turn_fact`.
- ``turn_paused.website_style`` snapshot at durable pause; resume rehydrates memory.
- Process-local ``_LEDGER`` is a hot cache only — clear + rehydrate from journal /
  paused must still pass the ``build_website`` gate.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, ClassVar

from agentcore.runtime.facts import Fact, FactKind, current_fact_log, record_turn_fact

# Workspace design contract path (playbook artifact).
DESIGN_MD_PATH = "site/DESIGN.md"

# Markdown heading / line the design worker must write; scanner looks for this.
STYLE_ID_HEADING = "用户选定风格 id"

# full_auto narrow default when CEO skips the style card.
DEFAULT_STYLE_ID = "s_default"
DEFAULT_STYLE_LABEL = "简洁克制·高对比"

_WEBSITE_KICKOFF_RE = re.compile(
    r"(?:官网|落地页|营销页|建站|网站|站点|首页|landing\s*page|website|web\s*site|"
    r"控制台|工具台|管理后台|后台系统|admin\s*(?:console|panel|dashboard)|toolshed)",
    re.IGNORECASE,
)

# Greenfield *construction* (delegate ``none`` hard gate). Broader than kickoff:
# requires a build/create verb near a site noun, or explicit hand-write / miss framing.
# Audit/fix follow-ups that only mention 官网 without 做/建… do not match.
_WEBSITE_BUILD_INTENT_RE = re.compile(
    r"(?:"
    r"(?:做|建|搭建|构建|制作|开发|写|帮.?我)"
    r".{0,32}"
    r"(?:官网|落地页|营销页|网站|站点|首页|landing\s*page|website|web\s*site)"
    r"|"
    r"(?:官网|落地页|营销页|网站|站点|首页|landing\s*page|website|web\s*site)"
    r".{0,32}"
    r"(?:做|建|搭建|构建|制作|开发)"
    r"|"
    r"(?:build|create|make|develop)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:landing\s*page|website|web\s*site|\bsite\b)"
    r"|"
    r"(?:手写|hand[- ]?writ).{0,40}"
    r"(?:官网|网站|website|落地页|build_website)"
    r"|"
    r"build_website.{0,48}(?:未|不|miss|没有|不可|目录)"
    r")",
    re.IGNORECASE,
)

# Toolshed / console dense UI construction (same none hard gate; routes to build_toolshed).
# After-noun branch omits bare「做」(「对控制台做审计」误伤)；前缀「帮我做控制台」仍命中。
_TOOLSHED_BUILD_INTENT_RE = re.compile(
    r"(?:"
    r"(?:做|建|搭建|构建|制作|开发|写|帮.?我)"
    r".{0,32}"
    r"(?:控制台|工具台|管理后台|后台系统|运营后台|"
    r"admin\s*(?:console|panel|dashboard)|toolshed|dense\s*ui|saas\s*admin)"
    r"|"
    r"(?:控制台|工具台|管理后台|后台系统|运营后台|"
    r"admin\s*(?:console|panel|dashboard)|toolshed|dense\s*ui|saas\s*admin)"
    r".{0,32}"
    r"(?:建|搭建|构建|制作|开发)"
    r"|"
    r"(?:build|create|make|develop)\s+(?:a\s+|an\s+|the\s+)?"
    r"(?:admin\s*(?:console|panel|dashboard)|toolshed|dense\s*ui)"
    r"|"
    r"(?:手写|hand[- ]?writ).{0,40}"
    r"(?:控制台|工具台|build_toolshed|toolshed)"
    r"|"
    r"build_toolshed.{0,48}(?:未|不|miss|没有|不可|目录)"
    r")",
    re.IGNORECASE,
)

# Mid-turn audit / patch after a site exists — allow ``none`` when call payload
# is follow-up-framed and does not itself restate greenfield construction.
_WEBSITE_FOLLOWUP_EXEMPT_RE = re.compile(
    r"(?:独立审计|审计员|质检|复查|修订员|小范围.{0,12}修复|精准修复|改稿|修补|"
    r"整页验收|页面\s*QA|build_website_verify|"
    r"\baudit\b|\brevise\b|\bfix(?:es|ing)?\b|\bpatch\b)",
    re.IGNORECASE,
)

# User turn: continue / finish remaining work (not bare「继续」alone).
# Alone is NOT enough for the none gate — see :func:`is_website_continuation_intent`
# (must co-occur with a site / toolshed strong noun).
_WEBSITE_CONTINUATION_PHRASE_RE = re.compile(
    r"(?:"
    r"继续完成|接着完成|把剩下|补全分区|写完剩下|写完剩余|把剩余|"
    r"完成剩下|完成剩余|接着写完|继续把|把分区写完|"
    r"finish\s+(?:the\s+)?(?:rest|remaining|site)|"
    r"continue\s+(?:and\s+)?(?:finish|complete)|"
    r"complete\s+(?:the\s+)?(?:rest|remaining|site|sections?)"
    r")",
    re.IGNORECASE,
)

# Site / toolshed anchors that must co-occur with a continuation phrase.
# Generic「继续完成项目的开发」must not trip the gate.
_WEBSITE_CONTINUATION_SITE_ANCHOR_RE = re.compile(
    r"(?:"
    r"官网|落地页|营销页|建站|网站|站点|首页|landing\s*page|website|web\s*site|"
    r"控制台|工具台|管理后台|后台系统|运营后台|"
    r"admin\s*(?:console|panel|dashboard)|toolshed|"
    r"build_website|build_toolshed|build_website_verify|\bsite/"
    r")",
    re.IGNORECASE,
)

# Call blob looks like site / page construction (broader than greenfield build verbs).
# Used with continuation intent so「继续完成官网」+ 建站形 hand-write is blocked.
# Strong signals only — bare HTML/CSS/JS (incl. HTML5 game framing) do not count;
# index.html / styles.css / site/ remain explicit positives. File extensions like
# 卡牌.html alone must not hit.
_WEBSITE_SHAPED_CALL_RE = re.compile(
    r"(?:"
    r"官网|落地页|营销页|网站|站点|首页|landing\s*page|website|web\s*site|"
    r"控制台|工具台|管理后台|后台系统|"
    r"build_website|build_toolshed|build_website_verify|"
    r"index\.html|styles\.css|main\.js|\bsite/"
    r")",
    re.IGNORECASE,
)

# ``s0`` / ``s_default`` / ``s12`` — ids minted by normalize_style_options or default.
_STYLE_ID_TOKEN_RE = re.compile(r"\b(s(?:_default|\d+))\b", re.IGNORECASE)

_HEX_COLOR_RE = re.compile(r"#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})\b")

# ``var(--token, #fallback)`` — fallback hex is not "scattered brand color".
_VAR_FALLBACK_PREFIX = re.compile(
    r"var\s*\(\s*--[\w-]+\s*,\s*$",
    re.IGNORECASE,
)

# Neutrals / CSS keywords allowed without appearing in DESIGN tokens.
_NEUTRAL_COLORS = frozenset(
    {
        "#000",
        "#000000",
        "#fff",
        "#ffffff",
        "#fff0",
        "#ffffff00",
        "#0000",
        "#00000000",
    }
)

_lock = threading.Lock()


@dataclass(frozen=True)
class StyleConfirmation:
    style_id: str
    label: str
    source: str  # "ask_user" | "full_auto_default"


# conversation_id → StyleConfirmation (hot cache; durable source = journal / paused)
_LEDGER: dict[str, StyleConfirmation] = {}


@dataclass(frozen=True, slots=True)
class WebsiteStyleConfirmedFact:
    """Durable structured style pick for ``build_website`` gate rehydration."""

    style_id: str
    label: str
    source: str
    conversation_id: str = ""
    kind: ClassVar[FactKind] = FactKind.WEBSITE_STYLE_CONFIRMED

    def to_fact(self, ts: str | None = None) -> Fact:
        return Fact(
            kind=self.kind.value,
            payload={
                "style_id": self.style_id,
                "label": self.label,
                "source": self.source,
                "conversation_id": self.conversation_id,
            },
            ts=ts,
        )


def is_website_kickoff_text(*parts: str) -> bool:
    """True when kickoff framing looks like a site / landing-page ask."""
    blob = " ".join(p for p in parts if p)
    return bool(blob and _WEBSITE_KICKOFF_RE.search(blob))


def is_website_build_intent(*parts: str) -> bool:
    """True when text frames greenfield site / landing *construction*.

    Used by the delegate playbook-declaration hard gate (reject ``none`` under
    website build intent). Distinct from :func:`is_website_kickoff_text`: a bare
    mention of「官网」in an audit task does **not** count as build intent.
    """
    blob = " ".join(p for p in parts if p)
    return bool(blob and _WEBSITE_BUILD_INTENT_RE.search(blob))


def is_toolshed_build_intent(*parts: str) -> bool:
    """True when text frames greenfield console / toolshed *construction*."""
    blob = " ".join(p for p in parts if p)
    return bool(blob and _TOOLSHED_BUILD_INTENT_RE.search(blob))


def is_site_build_intent(*parts: str) -> bool:
    """Marketing website **or** toolshed console greenfield construction."""
    return is_website_build_intent(*parts) or is_toolshed_build_intent(*parts)


def is_website_followup_exempt(*parts: str) -> bool:
    """True when this delegate call is framed as audit / fix (not greenfield build)."""
    blob = " ".join(p for p in parts if p)
    return bool(blob and _WEBSITE_FOLLOWUP_EXEMPT_RE.search(blob))


def is_website_continuation_intent(*parts: str) -> bool:
    """True when user asks to continue / finish remaining *site* work.

    Requires a continuation phrase **and** a site / toolshed strong noun in the
    same blob (or the blob is already site kickoff / build framing). Bare
    「继续完成项目的开发」does **not** match.
    """
    blob = " ".join(p for p in parts if p)
    if not blob or not _WEBSITE_CONTINUATION_PHRASE_RE.search(blob):
        return False
    if _WEBSITE_CONTINUATION_SITE_ANCHOR_RE.search(blob):
        return True
    # User message already frames a site / toolshed ask (kickoff or greenfield).
    return is_website_kickoff_text(blob) or is_site_build_intent(blob)


def is_website_shaped_call(*parts: str) -> bool:
    """True when call payload looks like site / page construction (官网 / index.html…)."""
    blob = " ".join(p for p in parts if p)
    return bool(blob and _WEBSITE_SHAPED_CALL_RE.search(blob))


def website_kickoff_requires_styles_error() -> str:
    return (
        "建站 / 落地页 / 控制台开工提案卡必须提供非空 style_options（2–3 个风格候选）。"
        "请补 style_options 后重调 ask_user；选定风格会结构化记账并写入 site/DESIGN.md。"
    )


def build_website_missing_style_error() -> str:
    return (
        "建站 playbook（build_website / build_toolshed）需要先经 ask_user 开工卡确认风格"
        "（非空 style_options → 用户选定 style_id 已记账）。"
        "请先开开工提案卡选风格，或在 AutonomyPolicy.full_auto 下由机制落默认风格。"
    )


def style_confirmation_to_payload(conf: StyleConfirmation) -> dict[str, str]:
    return {
        "style_id": conf.style_id,
        "label": conf.label,
        "source": conf.source,
    }


def style_confirmation_from_payload(payload: dict[str, Any] | None) -> StyleConfirmation | None:
    if not isinstance(payload, dict):
        return None
    sid = str(payload.get("style_id") or "").strip()
    if not sid:
        return None
    return StyleConfirmation(
        style_id=sid,
        label=str(payload.get("label") or "").strip() or sid,
        source=str(payload.get("source") or "").strip() or "ask_user",
    )


def style_from_journal_entries(
    entries: list[dict[str, Any]] | None,
) -> StyleConfirmation | None:
    """Fold the last ``website_style_confirmed`` fact from a journal stream."""
    if not entries:
        return None
    last: StyleConfirmation | None = None
    kind = FactKind.WEBSITE_STYLE_CONFIRMED.value
    for entry in entries:
        if (entry.get("kind") or "") != kind:
            continue
        conf = style_confirmation_from_payload(entry.get("payload"))
        if conf is not None:
            last = conf
    return last


def _cache_put(conversation_id: str, conf: StyleConfirmation) -> StyleConfirmation:
    with _lock:
        _LEDGER[conversation_id] = conf
    return conf


def _cache_get(conversation_id: str) -> StyleConfirmation | None:
    with _lock:
        return _LEDGER.get(conversation_id)


def hydrate_style_confirmation(
    conversation_id: str,
    conf: StyleConfirmation,
) -> StyleConfirmation:
    """Fill the hot cache only (no journal append) — used by rehydrate paths."""
    cid = (conversation_id or "").strip()
    if not cid:
        raise ValueError("conversation_id required")
    return _cache_put(cid, conf)


def rehydrate_style_confirmation(
    conversation_id: str | None,
    *,
    entries: list[dict[str, Any]] | None = None,
    turn_paused_style: dict[str, Any] | None = None,
) -> StyleConfirmation | None:
    """Restore memory from ``turn_paused.website_style`` and/or journal facts.

    Priority: turn_paused snapshot → last ``website_style_confirmed`` in ``entries``.
    Returns the hydrated confirmation, or ``None`` when neither source has one.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    conf = style_confirmation_from_payload(turn_paused_style)
    if conf is None:
        conf = style_from_journal_entries(entries)
    if conf is None:
        return None
    return hydrate_style_confirmation(cid, conf)


def record_style_confirmation(
    conversation_id: str,
    *,
    style_id: str,
    label: str,
    source: str,
) -> StyleConfirmation:
    """Overwrite the conversation's confirmed style and append a durable journal fact."""
    cid = (conversation_id or "").strip()
    sid = (style_id or "").strip()
    if not cid or not sid:
        raise ValueError("conversation_id and style_id required")
    conf = StyleConfirmation(
        style_id=sid,
        label=(label or "").strip() or sid,
        source=source,
    )
    _cache_put(cid, conf)
    record_turn_fact(
        WebsiteStyleConfirmedFact(
            style_id=conf.style_id,
            label=conf.label,
            source=conf.source,
            conversation_id=cid,
        ).to_fact()
    )
    return conf


def get_style_confirmation(conversation_id: str | None) -> StyleConfirmation | None:
    """Hot cache, then ambient fact log (same-turn durable rehydrate without DB)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    hit = _cache_get(cid)
    if hit is not None:
        return hit
    log = current_fact_log.get()
    if log is None:
        return None
    conf = style_from_journal_entries(log.entries())
    if conf is None:
        return None
    return hydrate_style_confirmation(cid, conf)


def clear_style_confirmation(conversation_id: str | None) -> None:
    """Test helper — drop a conversation's hot-cache entry (journal untouched)."""
    cid = (conversation_id or "").strip()
    if not cid:
        return
    with _lock:
        _LEDGER.pop(cid, None)


def ensure_full_auto_default_style(conversation_id: str) -> StyleConfirmation:
    """Narrow full_auto exemption: ledger the default if none confirmed yet."""
    existing = get_style_confirmation(conversation_id)
    if existing is not None:
        return existing
    return record_style_confirmation(
        conversation_id,
        style_id=DEFAULT_STYLE_ID,
        label=DEFAULT_STYLE_LABEL,
        source="full_auto_default",
    )


async def load_style_confirmation_from_db(
    conversation_id: str | None,
) -> StyleConfirmation | None:
    """Cold path: scan recent turn journals for ``website_style_confirmed``.

    Used when the hot cache and ambient fact log miss (process restart / new turn).
    Hydrates memory on hit. Best-effort — DB gaps return ``None`` (gate fails cleanly).
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    hit = _cache_get(cid)
    if hit is not None:
        return hit
    try:
        from agentcore.db.base import async_session_factory
        from agentcore.db.repositories import TurnJournalRepository
    except Exception:
        return None
    try:
        async with async_session_factory() as session:
            repo = TurnJournalRepository(session)
            payload = await repo.find_latest_website_style(conversation_id=cid)
    except Exception:
        return None
    conf = style_confirmation_from_payload(payload)
    if conf is None:
        return None
    return hydrate_style_confirmation(cid, conf)


async def resolve_style_confirmation(
    conversation_id: str | None,
) -> StyleConfirmation | None:
    """Gate helper: memory / ambient journal → else durable DB scan."""
    conf = get_style_confirmation(conversation_id)
    if conf is not None:
        return conf
    return await load_style_confirmation_from_db(conversation_id)


def snapshot_website_style_for_pause(
    journal_entries: list[dict[str, Any]] | None,
    *,
    conversation_id: str | None = None,
) -> dict[str, str] | None:
    """Build ``turn_paused.website_style`` from journal fact or hot cache."""
    conf = style_from_journal_entries(journal_entries)
    if conf is None and conversation_id:
        conf = _cache_get((conversation_id or "").strip())
    if conf is None:
        return None
    return style_confirmation_to_payload(conf)


def _lookup_style_option(
    by_id: dict[str, dict[str, Any]],
    style_id: str,
) -> StyleConfirmation | None:
    sid = (style_id or "").strip()
    if not sid:
        return None
    for kid, opt in by_id.items():
        if kid.casefold() == sid.casefold():
            return StyleConfirmation(
                style_id=kid,
                label=str(opt.get("label") or kid),
                source="ask_user",
            )
    return None


def resolve_style_from_resume(
    style_options: list[dict[str, Any]] | None,
    *,
    style_id: str | None = None,
    selected: list[str] | None = None,
    note: str = "",
) -> StyleConfirmation | None:
    """Map structured resume wire onto a style_options entry.

    Priority: explicit ``style_id`` (must ∈ options) → else a legitimate ``sN`` /
    ``s_default`` token in ``selected`` that ∈ options. Prose ``note`` / label
    fuzzy match is **not** a success path (may log for observability only).
    """
    opts = [o for o in (style_options or []) if isinstance(o, dict) and o.get("id")]
    if not opts:
        return None
    by_id = {str(o["id"]).strip(): o for o in opts if str(o.get("id") or "").strip()}
    if not by_id:
        return None

    explicit = (style_id or "").strip()
    if explicit:
        hit = _lookup_style_option(by_id, explicit)
        if hit is not None:
            return hit
        # Invalid explicit id → reject (do not fall through to selected / note).
        return None

    for raw in selected or []:
        tok = str(raw or "").strip()
        if not tok or not _STYLE_ID_TOKEN_RE.fullmatch(tok):
            continue
        hit = _lookup_style_option(by_id, tok)
        if hit is not None:
            return hit

    # Observability only: note may still mention a label; never treat as confirmation.
    _ = note
    return None


def extract_style_id_from_design(text: str) -> str | None:
    """Parse ``用户选定风格 id`` from DESIGN.md body."""
    if not text:
        return None
    m = re.search(
        rf"{re.escape(STYLE_ID_HEADING)}\s*[:：]?\s*(\S+)?",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    same = (m.group(1) or "").strip()
    if same and _STYLE_ID_TOKEN_RE.fullmatch(same):
        return same
    after = text[m.end() :]
    for line in after.splitlines():
        cand = line.strip()
        if not cand:
            continue
        tok = _STYLE_ID_TOKEN_RE.search(cand)
        if tok:
            return tok.group(1)
        break
    return None


def extract_design_tokens(text: str) -> set[str]:
    """Hex colors declared in DESIGN.md (normalized lowercase)."""
    if not text:
        return set()
    return {h.casefold() for h in _HEX_COLOR_RE.findall(text)}


def _hex_is_css_var_fallback(text: str, start: int) -> bool:
    """True when ``text[start:]`` hex is the fallback arm of ``var(--token, #…)``."""
    window = text[max(0, start - 96) : start]
    return bool(_VAR_FALLBACK_PREFIX.search(window))


def find_scattered_colors(text: str, allowed: set[str]) -> list[str]:
    """Hex colors in implementation text not ⊆ DESIGN tokens (excl. neutrals).

    Ignores hex that appear only as ``var(--token, #fallback)`` defaults (catalog
    ``_shared.css`` bridge) — those are not brand scatter.
    """
    if not text:
        return []
    allowed_cf = {a.casefold() for a in allowed}
    neutrals = {n.casefold() for n in _NEUTRAL_COLORS}
    hits: list[str] = []
    seen: set[str] = set()
    for m in _HEX_COLOR_RE.finditer(text):
        if _hex_is_css_var_fallback(text, m.start()):
            continue
        raw = m.group(0)
        key = raw.casefold()
        if key in seen or key in neutrals or key in allowed_cf:
            continue
        if len(key) == 4:  # #rgb
            expanded = "#" + "".join(ch * 2 for ch in key[1:])
            if expanded in allowed_cf or expanded in neutrals:
                continue
        seen.add(key)
        hits.append(raw)
        if len(hits) >= 8:
            break
    return hits


def design_prompt_block(*, style: StyleConfirmation | None) -> str:
    """Inject into the design-node task book."""
    if style is None:
        style_line = (
            f"若上游已确认风格，将 id 原样写入「{STYLE_ID_HEADING}」；"
            f"full_auto 默认用 `{DEFAULT_STYLE_ID}`（{DEFAULT_STYLE_LABEL}）。"
        )
        sid = DEFAULT_STYLE_ID
    else:
        sid = style.style_id
        label = style.label
        style_line = f"用户选定风格 id=`{sid}`（{label}，来源 {style.source}）——必须原样写入。"
    return (
        f"【设计契约】用 file_write 落盘 `{DESIGN_MD_PATH}`，须含："
        f"色板 tokens（CSS 变量名 + hex）、字体、间距、对比度策略、禁止项、"
        f"以及章节「{STYLE_ID_HEADING}」下一行写 `{sid}`。"
        f"{style_line}"
        "骨架与分区实现只读本文件，禁止另起散色。"
    )

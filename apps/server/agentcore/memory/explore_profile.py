"""Cold-start explore act — project ``画像.md`` sufficiency + section-merge write.

Product exception to §1.5 (normally no mid-turn AI write of ``ai_maintained`` profile):
explore-act close-out may write the **project** layer only. Orthogonal to consolidation
``_is_cold_start`` (global preferences+profile empty). See 编排器 · 冷启动探索幕 /
记忆 §1.5. P1: optional project ``主题/<slug>.md`` whole-file replace (≤3 / call).
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.memory.locks import user_memory_lock
from agentcore.memory.store import (
    CORE_MEMORY_FILE,
    MemoryStore,
    memory_version,
    topic_path,
)
from agentcore.memory.user_memory import (
    _DEFAULT_PREAMBLE,
    _MAX_TOPIC_SLUG_LEN,
    _MemoryDoc,
    _parse,
    _render,
    _Section,
    strip_memory_chrome,
)

logger = get_logger(__name__)

_MAX_CAS_RETRIES = 3
MAX_EXPLORE_TOPICS = 3
_SLUG_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,38}$")


def profile_has_substance(markdown: str | None) -> bool:
    """True when project ``画像.md`` has real content (not chrome / empty headers only)."""
    raw = markdown or ""
    doc = _parse(raw)
    if any(b.strip() for s in doc.sections for b in s.bullets):
        return True
    body = strip_memory_chrome(raw).strip()
    if not body:
        return False
    # Freeform body with no ## sections still counts (rare hand-edit).
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith("##"):
            continue
        return True
    return False


def project_profile_is_empty(markdown: str | None) -> bool:
    """Inverse of :func:`profile_has_substance` — the explore-act「够用」skip probe."""
    return not profile_has_substance(markdown)


async def load_project_profile(
    store: MemoryStore, user_id: str, folder_id: str
) -> str:
    """Load project-layer ``画像.md`` ("" when missing)."""
    return await store.load(user_id, CORE_MEMORY_FILE, scope=folder_id)


def build_workspace_key(*, folder_id: str, binding: Any | None) -> str:
    """Stable workspace identity for explore-act 过期再探.

    Local: ``local:<root_id>:<subpath>``. Cloud (no binding): ``folder:<id>``.
    """
    if binding is not None:
        root_id = getattr(binding, "root_id", None) or ""
        subpath = getattr(binding, "subpath", None) or ""
        if root_id:
            return f"local:{root_id}:{subpath}"
    from agentcore.workspace.locate import format_workspace_id

    return format_workspace_id(folder_id=folder_id, conversation_id="")


async def resolve_folder_workspace_key(folder_id: str) -> str:
    """Load Folder binding and return :func:`build_workspace_key` (DB round-trip)."""
    from agentcore.conversation.scratch import resolve_conversation_local_binding
    from agentcore.db.base import async_session_factory
    from agentcore.db.repositories import FolderRepository

    async with async_session_factory() as session:
        folder = await FolderRepository(session).get_by_id_unscoped(folder_id)
        if not folder:
            return build_workspace_key(folder_id=folder_id, binding=None)
        binding = resolve_conversation_local_binding(
            local_root_id=folder.local_root_id,
            local_subpath=folder.local_subpath,
            label=folder.name or "workspace",
        )
        return build_workspace_key(folder_id=folder_id, binding=binding)


async def load_explore_workspace_key(
    store: MemoryStore, user_id: str, folder_id: str
) -> str | None:
    """Stored key from last explore-act write (``_memory_meta.json``), if any."""
    from agentcore.memory.episodic import load_scope_meta

    meta = await load_scope_meta(store, user_id, scope=folder_id)
    return meta.explore_workspace_key


async def record_explore_workspace_key(
    store: MemoryStore,
    user_id: str,
    folder_id: str,
    workspace_key: str,
) -> None:
    """Persist explore-act workspace identity alongside episodic meta (same sidecar)."""
    from agentcore.memory.episodic import load_scope_meta, save_scope_meta

    key = (workspace_key or "").strip()
    if not key:
        return
    async with user_memory_lock(user_id):
        meta = await load_scope_meta(store, user_id, scope=folder_id)
        if meta.explore_workspace_key == key:
            return
        meta.explore_workspace_key = key
        await save_scope_meta(store, user_id, meta, scope=folder_id)
        logger.info(
            "memory.explore_workspace_key_written",
            user_id=user_id,
            folder_id=folder_id,
            workspace_key=key,
        )


async def project_profile_explore_reason(
    store: MemoryStore,
    user_id: str,
    folder_id: str | None,
    *,
    current_workspace_key: str | None = None,
) -> str | None:
    """Auto-explore gate: ``\"empty\"`` | ``\"rebind\"`` | ``None``.

    Does **not** judge chitchat vs substance (prompt/routing). Bare chat never
    explores. Missing stored key on a non-empty profile → no hard rebind (legacy).
    """
    if not folder_id:
        return None
    current = await load_project_profile(store, user_id, folder_id)
    if project_profile_is_empty(current):
        return "empty"
    stored = await load_explore_workspace_key(store, user_id, folder_id)
    if not stored:
        return None
    live = current_workspace_key
    if live is None:
        live = await resolve_folder_workspace_key(folder_id)
    if live and live != stored:
        return "rebind"
    return None


async def project_profile_needs_explore(
    store: MemoryStore,
    user_id: str,
    folder_id: str | None,
    *,
    current_workspace_key: str | None = None,
) -> bool:
    """True when auto-explore should inject (empty profile or workspace rebind)."""
    reason = await project_profile_explore_reason(
        store,
        user_id,
        folder_id,
        current_workspace_key=current_workspace_key,
    )
    return reason is not None


def merge_profile_by_sections(old_md: str, new_md: str) -> str:
    """Section-anchored merge for explore-act writes (定案 §三).

    - Sections present in ``new_md`` with substance → replace that section's body.
    - Sections only in ``old_md`` (or empty in new) → keep old body.
    - Bootstrap when old is empty: render new (with default preamble if needed).
    - Never wipe the whole file down to a few empty lines when old had content.
    """
    if not (new_md or "").strip():
        return old_md or ""
    if project_profile_is_empty(old_md):
        doc = _parse(new_md)
        if not doc.preamble.strip():
            doc.preamble = _DEFAULT_PREAMBLE
        return _render(doc)

    old_doc = _parse(old_md)
    new_doc = _parse(new_md)
    merged = _MemoryDoc(preamble=old_doc.preamble or _DEFAULT_PREAMBLE, sections=[])

    {_normalize_section(s.name): s for s in old_doc.sections}
    new_by = {_normalize_section(s.name): s for s in new_doc.sections}
    # Preserve old section order; append brand-new sections from new.
    seen: set[str] = set()
    for section in old_doc.sections:
        key = _normalize_section(section.name)
        seen.add(key)
        incoming = new_by.get(key)
        if incoming is not None and _section_has_substance(incoming):
            merged.sections.append(
                _Section(name=incoming.name.strip() or section.name, bullets=list(incoming.bullets))
            )
        else:
            merged.sections.append(
                _Section(name=section.name, bullets=list(section.bullets))
            )
    for section in new_doc.sections:
        key = _normalize_section(section.name)
        if key in seen:
            continue
        if _section_has_substance(section):
            merged.sections.append(
                _Section(name=section.name.strip(), bullets=list(section.bullets))
            )
            seen.add(key)
    return _render(merged)


def _normalize_section(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def _section_has_substance(section: _Section) -> bool:
    return any(b.strip() for b in section.bullets)


async def write_project_profile_cas(
    *,
    store: MemoryStore,
    user_id: str,
    folder_id: str,
    new_markdown: str,
    baseline: str | None = None,
) -> tuple[bool, str, bool]:
    """Merge-write project ``画像.md`` under the per-user memory lock (CAS + retry).

    Returns ``(ok, resulting_markdown, conflict)``.
    ``conflict=True`` when a caller-supplied ``baseline`` no longer matches after retries.
    """
    if not folder_id:
        raise ValueError("folder_id required for project profile write")
    if project_profile_is_empty(new_markdown):
        return False, "", False

    async with user_memory_lock(user_id):
        for attempt in range(_MAX_CAS_RETRIES):
            current = await store.load(user_id, CORE_MEMORY_FILE, scope=folder_id)
            current_ver = memory_version(current)
            if baseline is not None and baseline != current_ver:
                if attempt + 1 < _MAX_CAS_RETRIES:
                    # Stale baseline: re-merge against live content (consolidation-style).
                    baseline = current_ver
                    continue
                return False, current, True
            merged = merge_profile_by_sections(current, new_markdown)
            if project_profile_is_empty(merged):
                return False, current, False
            if merged == current:
                return True, current, False
            await store.save(user_id, CORE_MEMORY_FILE, merged, scope=folder_id)
            logger.info(
                "memory.explore_profile_written",
                user_id=user_id,
                folder_id=folder_id,
                chars=len(merged),
            )
            return True, merged, False
    return False, "", True


def normalize_explore_topic_slug(raw: str | None) -> str | None:
    """Safe explore-act topic slug (short ASCII id) or None if unusable."""
    text = (raw or "").strip()
    if not text:
        return None
    # Reject path-ish input before stripping (defence in depth).
    if "/" in text or "\\" in text or ".." in text:
        return None
    slug = text.removesuffix(".md").strip().casefold()
    if not slug or len(slug) > _MAX_TOPIC_SLUG_LEN:
        return None
    if not _SLUG_ALLOWED_RE.match(slug):
        return None
    return slug


def parse_explore_topics(
    raw_topics: object, *, max_topics: int = MAX_EXPLORE_TOPICS
) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse tool ``topics`` arg → ``([(slug, content), ...], warnings)``.

    Drops empty/invalid entries; caps at ``max_topics`` (extras → warning, not written).
    """
    if raw_topics is None:
        return [], []
    if not isinstance(raw_topics, list):
        return [], ["topics 须为数组，已忽略"]
    warnings: list[str] = []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_topics:
        if len(out) >= max_topics:
            warnings.append(f"主题超过 {max_topics} 个，多余未写入（压回画像摘要）")
            break
        if not isinstance(item, dict):
            warnings.append("跳过非对象 topics 项")
            continue
        slug = normalize_explore_topic_slug(str(item.get("slug") or ""))
        content = str(item.get("content") or "").strip()
        if slug is None:
            warnings.append("跳过非法 slug")
            continue
        if not content:
            warnings.append(f"跳过空主题 {slug}")
            continue
        if slug in seen:
            warnings.append(f"重复 slug {slug}，后者覆盖前者")
            out = [(s, c) for s, c in out if s != slug]
        seen.add(slug)
        out.append((slug, content))
    return out, warnings


async def write_project_topics_replace(
    *,
    store: MemoryStore,
    user_id: str,
    folder_id: str,
    topics: list[tuple[str, str]],
) -> list[str]:
    """Whole-file replace project ``主题/<slug>.md`` notes (explore-act close-out).

    Returns list of written paths (``主题/<slug>.md``). Empty ``topics`` → no-op.
    """
    if not folder_id:
        raise ValueError("folder_id required for project topic write")
    if not topics:
        return []
    written: list[str] = []
    async with user_memory_lock(user_id):
        for slug, content in topics:
            path = topic_path(slug)
            await store.save(user_id, path, content.strip() + "\n", scope=folder_id)
            written.append(path)
            logger.info(
                "memory.explore_topic_written",
                user_id=user_id,
                folder_id=folder_id,
                slug=slug,
                chars=len(content),
            )
    return written

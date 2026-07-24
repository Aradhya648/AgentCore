"""Two-tier rule injection + cross-file budget (Agent记忆与知识系统 §二 / §5.7 跨文件预算).

The ``<rules>`` block now carries BOTH the user's own rules (``ai_maintained=false``) and the
AI-maintained long-term memory core (``ai_maintained=true``) — same carrier, distinguished by
authorship (§5.2). This module assembles that block:

- **两档措辞 (§二)**: user rules ride FIRST with authoritative wording (须遵守); AI memory rides
  after with soft wording (软性偏好, 可被覆盖). Authority is carried by the WORDING, not a
  separate structural channel.
- **跨文件预算 (§5.3 / §5.7)**: a single ``MAX_INSTRUCTION_DOCS`` / ``MAX_INSTRUCTION_CHARS``
  budget spans all always-injected rule docs, replacing the per-file memory cap. When the budget
  is tight GLOBAL docs survive first (「全局优先存活」), and within a scope the user's authoritative
  rules survive over soft AI memory.

Byte-stability: with no user rules and under budget, the composed memory body is identical to the
legacy ``load_injected_memory`` concatenation, so ``assemble_system_prompt`` takes its existing
memory-only ``<rules>`` path verbatim — the DeepSeek prefix cache and the memory-only prompt
tests are unaffected. The new combined path only engages once a user actually has rules (or the
budget trims), which is the new behavior this phase adds.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from agentcore.core.logging import get_logger
from agentcore.db.repositories import DocumentRepository
from agentcore.memory.injection import _PROJECT_MEMORY_LABEL
from agentcore.memory.store import ALWAYS_MEMORY_FILES, CORE_MEMORY_FILE, MemoryStore
from agentcore.memory.user_memory import strip_memory_chrome

logger = get_logger(__name__)

# Labels the project-layer user rules inside the shared block (mirrors the memory project label).
_USER_RULE_PROJECT_LABEL = "（以下为「当前项目」专属规则，仅在本项目内适用）"

_RULE_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _normalize_rule(text: str) -> str:
    """Whitespace-collapsed, casefolded key for user-rule dedup."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def append_user_rule_bullet(current_markdown: str, content: str) -> tuple[str, bool]:
    """Append ``content`` as a rule bullet with normalized dedup. Returns ``(new_md, changed)``.

    User rules are a plain bullet list with NO AI-maintained chrome (they are user-owned, §5.2).
    A normalized duplicate is a no-op — re-remembering the same rule does not grow the doc.
    """
    text = re.sub(r"\s+", " ", content).strip()
    if not text:
        return current_markdown, False
    key = _normalize_rule(text)
    for line in current_markdown.splitlines():
        match = _RULE_BULLET_RE.match(line)
        existing = match.group(1) if match else line
        if _normalize_rule(existing) == key:
            return current_markdown, False
    body = current_markdown.rstrip()
    return (f"{body}\n" if body else "") + f"- {text}\n", True


async def append_user_rule(
    repo: DocumentRepository, user_id: str, *, folder_id: str | None, content: str
) -> bool:
    """Append a user rule to the scope's canonical user-rule doc (``remember`` directive path).

    Create-on-write; normalized dedup; returns whether anything changed. This is the「用户明确
    下指令 → 落用户规则」half of the ``remember`` split (§5.7 用户规则入口①) — a ``rule`` doc
    with ``ai_maintained=false``, so the offline consolidation never rewrites it.
    """
    doc = await repo.get_user_rules_doc(user_id, folder_id)
    current = doc.content if doc is not None else ""
    new_md, changed = append_user_rule_bullet(current, content)
    if not changed:
        return False
    await repo.upsert_user_rules_doc(user_id, folder_id, new_md)
    return True


@dataclass(frozen=True)
class RuleFragment:
    """One always-injected rule doc, ready to place in ``<rules>``.

    ``scope`` is ``'global'`` or ``'project'`` (global survives budget first, §5.3);
    ``authority`` is ``'user'`` (authoritative user rule) or ``'ai'`` (soft memory);
    ``body`` is the fully-rendered text (chrome-stripped, project-labeled when project-scoped).
    """

    scope: str
    authority: str
    body: str

    @property
    def _keep_rank(self) -> tuple[int, int]:
        # Budget keep-priority: global before project, then user before AI within a scope —
        # so a tight budget drops project AI memory first and global user rules last.
        return (0 if self.scope == "global" else 1, 0 if self.authority == "user" else 1)


def compose_injected_rules(
    fragments: Sequence[RuleFragment], *, max_docs: int, max_chars: int
) -> tuple[str, str]:
    """Budget + compose rule fragments into ``(user_rules_markdown, memory_markdown)``.

    Greedily admits fragments in keep-priority order (global-first, user-before-AI) until the
    doc-count or char budget is hit — a fragment that would overflow is skipped, lower-priority
    ones still get a chance to fit. Survivors are then split by authorship and joined in DISPLAY
    order (global before project within each), so the memory body matches the legacy concatenation
    exactly when everything survives. A non-positive budget means「no limit」(admit all).
    """
    ordered = sorted(enumerate(fragments), key=lambda iv: (iv[1]._keep_rank, iv[0]))
    doc_cap = max_docs if max_docs and max_docs > 0 else None
    char_cap = max_chars if max_chars and max_chars > 0 else None
    kept: set[int] = set()
    used_chars = 0
    for idx, frag in ordered:
        if doc_cap is not None and len(kept) >= doc_cap:
            break
        length = len(frag.body)
        if char_cap is not None and used_chars + length > char_cap:
            continue
        kept.add(idx)
        used_chars += length
    # Display order = original fragment order (built global→project within each authority tier).
    user_bodies = [f.body for i, f in enumerate(fragments) if i in kept and f.authority == "user"]
    memory_bodies = [f.body for i, f in enumerate(fragments) if i in kept and f.authority == "ai"]
    return "\n\n".join(user_bodies), "\n\n".join(memory_bodies)


async def _memory_fragments(
    store: MemoryStore, user_id: str, *, folder_id: str | None
) -> list[RuleFragment]:
    """The AI-memory core as fragments, rendered exactly as the legacy memory concatenation.

    GLOBAL 偏好.md + 画像.md (in ``ALWAYS_MEMORY_FILES`` order, chrome-stripped) then — for a
    project conversation — that project's 画像.md, project-labeled (§二 stable global prefix).
    """
    frags: list[RuleFragment] = []
    for file in ALWAYS_MEMORY_FILES:
        body = strip_memory_chrome(await store.load(user_id, file))
        if body:
            frags.append(RuleFragment(scope="global", authority="ai", body=body))
    if folder_id:
        project_body = strip_memory_chrome(
            await store.load(user_id, CORE_MEMORY_FILE, scope=folder_id)
        )
        if project_body:
            frags.append(
                RuleFragment(
                    scope="project",
                    authority="ai",
                    body=f"{_PROJECT_MEMORY_LABEL}\n{project_body}",
                )
            )
    return frags


async def _user_rule_fragments(
    repo: DocumentRepository, user_id: str, *, folder_id: str | None
) -> list[RuleFragment]:
    """The user's own always-injected rule docs (``ai_maintained=false``) as fragments.

    GLOBAL rules first, then — for a project conversation — that project's rules, project-labeled.
    Injected verbatim (user-authored content): only surrounding whitespace is trimmed.
    """
    frags: list[RuleFragment] = []
    for doc in await repo.list_injectable_rules(user_id, None, ai_maintained=False):
        body = doc.content.strip()
        if body:
            frags.append(RuleFragment(scope="global", authority="user", body=body))
    if folder_id:
        for doc in await repo.list_injectable_rules(user_id, folder_id, ai_maintained=False):
            body = doc.content.strip()
            if body:
                frags.append(
                    RuleFragment(
                        scope="project",
                        authority="user",
                        body=f"{_USER_RULE_PROJECT_LABEL}\n{body}",
                    )
                )
    return frags


async def assemble_injected_rules(
    store: MemoryStore,
    repo: DocumentRepository,
    user_id: str,
    *,
    folder_id: str | None,
    enabled: bool,
    max_docs: int,
    max_chars: int,
) -> tuple[str, str]:
    """Load + budget + compose this turn's ``<rules>`` fragments (§二 / §5.7).

    Returns ``(user_rules_markdown, memory_markdown)`` for ``assemble_system_prompt``. AI memory
    is gated by the master switch (off ⇒ no memory fragments); USER rules are the user's own
    authoritative instructions and are NOT memory, so they are injected regardless of the switch
    (turning off「AI 记忆」silences AI-maintained memory, not the user's own rules). Ordering
    within the fragment list is global→project per authorship so the budget's display order and
    the legacy byte layout line up.
    """
    fragments: list[RuleFragment] = []
    fragments.extend(await _user_rule_fragments(repo, user_id, folder_id=folder_id))
    if enabled:
        fragments.extend(await _memory_fragments(store, user_id, folder_id=folder_id))
    return compose_injected_rules(fragments, max_docs=max_docs, max_chars=max_chars)


async def assemble_turn_rules(
    store: MemoryStore,
    user_id: str,
    *,
    folder_id: str | None,
    enabled: bool,
    max_docs: int,
    max_chars: int,
) -> tuple[str, str]:
    """Turn-time convenience over :func:`assemble_injected_rules` (the pipeline entry point).

    AI memory is read through the given ``store`` (the patchable pipeline seam); user rules are
    read through a fresh document session. User-rule loading degrades to「no rules」on ANY error
    (missing DB in a unit test, transient failure) so memory injection can never break a turn —
    matching the rest of the memory system's defensive posture. Byte-stability holds: with no
    user rules the memory body is identical to the legacy concatenation.
    """
    from agentcore.db.base import async_session_factory

    user_fragments: list[RuleFragment] = []
    try:
        async with async_session_factory() as session:
            user_fragments = await _user_rule_fragments(
                DocumentRepository(session), user_id, folder_id=folder_id
            )
    except Exception as e:  # noqa: BLE001 - user rules must never break a turn's assembly
        logger.warning("memory.user_rules_load_failed", user_id=user_id, error=str(e))

    fragments = list(user_fragments)
    if enabled:
        fragments.extend(await _memory_fragments(store, user_id, folder_id=folder_id))
    return compose_injected_rules(fragments, max_docs=max_docs, max_chars=max_chars)

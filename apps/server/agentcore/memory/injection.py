"""Assemble a user's long-term memory for prompt injection (Agent记忆与知识系统 §二).

The always-injected core spans two GLOBAL files (偏好.md + 画像.md) plus — for a conversation
bound to a project — that project's 画像.md. They are concatenated into ONE ``<rules>`` memory
body, GLOBAL first (the stable prefix that rides DeepSeek's cache), the project layer
appended after a short label so the model reads those bullets as project-scoped. On-demand
TOPIC names are merged across both scopes for the CEO's 记忆主题目录.

Both are gated by the per-user memory master switch (§1.6): off ⇒ "" / [] so zero memory
surfaces — the same privacy off-ramp as the rest of the memory system.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentcore.core.logging import get_logger
from agentcore.memory.store import (
    ALWAYS_MEMORY_FILES,
    CORE_MEMORY_FILE,
    MemoryScope,
    MemoryStore,
    is_topic_path,
    topic_slug,
)
from agentcore.memory.user_memory import strip_memory_chrome, topic_summary_line

logger = get_logger(__name__)

# Labels the project layer inside the shared <rules> block so the model reads those bullets
# as "current project only" (a global vs project conflict resolves by wording + proximity,
# §3.2 — no hard-override structure; the user's explicit instruction still wins).
_PROJECT_MEMORY_LABEL = "（以下为「当前项目」专属记忆，仅在本项目内适用）"

# Appended when an always-injected memory file is capped (COST-001). Fixed text so the
# truncated body stays deterministic — same input → same output → DeepSeek prefix cache holds.
_MEMORY_TRUNCATION_NOTICE = "\n…（此记忆文件过长，已截断；建议精简）"


def _cap_memory_body(
    body: str, cap: int | None, *, user_id: str, file: str, scope: str
) -> str:
    """Deterministically cap one memory file's body to ``cap`` chars (COST-001 读侧 backstop).

    Memory rides the stable prefix (SectionOrder.MEMORY), so capping MUST be deterministic:
    a head slice + a FIXED notice → identical bytes for identical input, keeping the prefix
    cache intact. The write-side ``memory_section_bullet_cap`` already bounds normal growth;
    this only fires on abnormal bloat. ``cap`` None/≤0 ⇒ unbounded (no-op).
    """
    if cap is None or cap <= 0 or len(body) <= cap:
        return body
    logger.warning(
        "memory.injection_truncated",
        user_id=user_id,
        file=file,
        scope=scope,
        original_chars=len(body),
        cap=cap,
    )
    return body[:cap] + _MEMORY_TRUNCATION_NOTICE


async def load_injected_memory(
    store: MemoryStore,
    user_id: str,
    *,
    folder_id: str | None,
    enabled: bool,
    file_char_cap: int | None = None,
) -> str:
    """Build the combined memory body injected into this turn's ``<rules>`` (or "").

    Each file's human chrome (title + note) is stripped PER FILE before concatenation —
    stripping once over the joined text would only shed the first file's leading H1 and
    leave the others' titles as mid-prompt noise. GLOBAL preferences + profile come first
    (stable prefix), then the project profile when ``folder_id`` is set.

    ``folder_id`` is the conversation's manual sidebar group (D4 方案 1,
    folder-refactor-design §8): truthy ⇒ load that group's project-layer 画像.md; NULL
    (bare chat) ⇒ global only. Auto-promote folders no longer exist post-migration.

    ``file_char_cap`` deterministically caps EACH file's body (COST-001 读侧 backstop) — see
    :func:`_cap_memory_body`; ``None`` (default) = unbounded, preserving callers/tests that
    don't pass it.
    """
    if not enabled:
        return ""
    parts: list[str] = []
    for file in ALWAYS_MEMORY_FILES:
        body = strip_memory_chrome(await store.load(user_id, file))
        if body:
            parts.append(
                _cap_memory_body(body, file_char_cap, user_id=user_id, file=file, scope="global")
            )
    if folder_id:
        project_body = strip_memory_chrome(
            await store.load(user_id, CORE_MEMORY_FILE, scope=folder_id)
        )
        if project_body:
            project_body = _cap_memory_body(
                project_body, file_char_cap, user_id=user_id, file=CORE_MEMORY_FILE, scope=folder_id
            )
            parts.append(f"{_PROJECT_MEMORY_LABEL}\n{project_body}")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class MemoryTopic:
    """One entry in the CEO's 记忆主题目录: a consultable topic note's name + 1-line summary.

    ``name`` is the slug the CEO passes to ``consult_memory``; ``summary`` is the note's first
    substantive line (记忆系统 §1.4) to help it judge WHEN a topic is relevant — "" when the
    note is empty / chrome-only (the directory then shows just the name).
    """

    name: str
    summary: str


async def _scope_topics(
    store: MemoryStore, user_id: str, scope: MemoryScope
) -> list[tuple[str, str]]:
    """The (name, one-line summary) of every TOPIC note in one scope (记忆主题目录 fodder)."""
    out: list[tuple[str, str]] = []
    for meta in await store.list(user_id, scope=scope):
        if not is_topic_path(meta.path):
            continue
        body = await store.load(user_id, meta.path, scope=scope)
        out.append((topic_slug(meta.path), topic_summary_line(body)))
    return out


async def load_memory_topics(
    store: MemoryStore, user_id: str, *, folder_id: str | None, enabled: bool
) -> list[MemoryTopic]:
    """Merge global + project on-demand TOPIC notes for the CEO's 记忆主题目录 (or []).

    Each topic rides the prompt as its NAME plus a one-line summary (记忆系统 §1.4: the note's
    first substantive line) — enough for the model to decide WHEN to pull a note's full body
    via ``consult_memory`` (which searches both scopes); the body itself never rides the常驻
    prefix. De-duplicated by name and sorted for a stable prefix; a topic that exists in both
    scopes appears once (the GLOBAL summary wins, matching the stable-prefix layer).

    ``folder_id`` selects the manual group whose project-layer topics to merge (D4 方案 1);
    NULL ⇒ global topics only.
    """
    if not enabled:
        return []
    summaries: dict[str, str] = {}
    for name, summary in await _scope_topics(store, user_id, None):
        summaries.setdefault(name, summary)
    if folder_id:
        for name, summary in await _scope_topics(store, user_id, folder_id):
            summaries.setdefault(name, summary)
    return [MemoryTopic(name=name, summary=summaries[name]) for name in sorted(summaries)]

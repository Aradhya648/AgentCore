"""Episodic (session-summary) memory layer.

Each settled conversation writes one ≤N-char summary into the user's memory folder
under ``情景/<id>.md``. Summaries are append-only, never deduped, never injected into
prompts — they only feed the later semantic consolidation pass.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from agentcore.core.logging import get_logger
from agentcore.llm import LLMMessage, LLMProvider
from agentcore.llm.profiles import build_request, get_profile
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.memory.conversation_title import ChatMessage
from agentcore.memory.store import (
    EPISODIC_DIR,
    MEMORY_META_FILE,
    MemoryScope,
    MemoryStore,
    episodic_path,
    is_episodic_path,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class EpisodeRecord:
    """One undigested (or any) episodic session summary."""

    id: str
    conversation_id: str
    summary: str
    created_at: str  # ISO


@dataclass
class ScopeMemoryMeta:
    """Per-(user, scope) sidecar: digested episode ids + last semantic success time.

    ``explore_workspace_key`` records the workspace identity last written by the
    cold-start explore act (过期再探); absent on legacy scopes.
    """

    digested_ids: set[str]
    last_semantic_at: datetime | None
    explore_workspace_key: str | None = None

    def to_json(self) -> str:
        payload: dict = {
            "digested_ids": sorted(self.digested_ids),
            "last_semantic_at": (
                self.last_semantic_at.astimezone(UTC).isoformat()
                if self.last_semantic_at
                else None
            ),
        }
        if self.explore_workspace_key:
            payload["explore_workspace_key"] = self.explore_workspace_key
        return json.dumps(payload, ensure_ascii=False)


def _parse_meta(raw: str) -> ScopeMemoryMeta:
    if not raw.strip():
        return ScopeMemoryMeta(digested_ids=set(), last_semantic_at=None)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ScopeMemoryMeta(digested_ids=set(), last_semantic_at=None)
    digested = {str(x) for x in (data.get("digested_ids") or []) if str(x).strip()}
    last_raw = data.get("last_semantic_at")
    last: datetime | None = None
    if isinstance(last_raw, str) and last_raw.strip():
        try:
            last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
        except ValueError:
            last = None
    key_raw = data.get("explore_workspace_key")
    key = str(key_raw).strip() if isinstance(key_raw, str) and key_raw.strip() else None
    return ScopeMemoryMeta(
        digested_ids=digested,
        last_semantic_at=last,
        explore_workspace_key=key,
    )


def _render_episode_body(*, conversation_id: str, summary: str, created_at: str) -> str:
    """Markdown body with a tiny machine header; human-readable summary below."""
    return (
        f"<!-- conversation_id: {conversation_id} -->\n"
        f"<!-- created_at: {created_at} -->\n\n"
        f"{summary.strip()}\n"
    )


def _parse_episode_body(episode_id: str, body: str) -> EpisodeRecord | None:
    conversation_id = ""
    created_at = ""
    lines = body.splitlines()
    text_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<!-- conversation_id:") and stripped.endswith("-->"):
            conversation_id = stripped[len("<!-- conversation_id:") : -3].strip()
            continue
        if stripped.startswith("<!-- created_at:") and stripped.endswith("-->"):
            created_at = stripped[len("<!-- created_at:") : -3].strip()
            continue
        text_lines.append(line)
    summary = "\n".join(text_lines).strip()
    if not summary:
        return None
    return EpisodeRecord(
        id=episode_id,
        conversation_id=conversation_id,
        summary=summary,
        created_at=created_at or datetime.now(UTC).isoformat(),
    )


async def load_scope_meta(
    store: MemoryStore, user_id: str, *, scope: MemoryScope = None
) -> ScopeMemoryMeta:
    raw = await store.load(user_id, MEMORY_META_FILE, scope=scope)
    return _parse_meta(raw)


async def save_scope_meta(
    store: MemoryStore,
    user_id: str,
    meta: ScopeMemoryMeta,
    *,
    scope: MemoryScope = None,
) -> None:
    await store.save(user_id, MEMORY_META_FILE, meta.to_json() + "\n", scope=scope)


def clamp_summary(text: str, max_chars: int) -> str:
    """Hard-cap an episodic summary (whitespace-normalized)."""
    cleaned = " ".join(text.split()).strip()
    if max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


async def append_episode(
    store: MemoryStore,
    *,
    user_id: str,
    conversation_id: str,
    summary: str,
    scope: MemoryScope = None,
    max_chars: int = 200,
) -> EpisodeRecord:
    """Append one session summary. Never dedups. Returns the stored record."""
    episode_id = uuid.uuid4().hex
    created_at = datetime.now(UTC).isoformat()
    clamped = clamp_summary(summary, max_chars)
    body = _render_episode_body(
        conversation_id=conversation_id, summary=clamped, created_at=created_at
    )
    await store.save(user_id, episodic_path(episode_id), body, scope=scope)
    logger.info(
        "memory.episodic_written",
        user_id=user_id,
        conversation_id=conversation_id,
        episode_id=episode_id,
        chars=len(clamped),
        scope=scope or "global",
    )
    return EpisodeRecord(
        id=episode_id,
        conversation_id=conversation_id,
        summary=clamped,
        created_at=created_at,
    )


async def list_undigested_episodes(
    store: MemoryStore, user_id: str, *, scope: MemoryScope = None
) -> list[EpisodeRecord]:
    """Episodes not yet consumed by a successful semantic consolidation (oldest first)."""
    meta = await load_scope_meta(store, user_id, scope=scope)
    out: list[EpisodeRecord] = []
    for m in await store.list(user_id, scope=scope):
        if not is_episodic_path(m.path):
            continue
        episode_id = m.path[len(EPISODIC_DIR) + 1 :].removesuffix(".md")
        if episode_id in meta.digested_ids:
            continue
        body = await store.load(user_id, m.path, scope=scope)
        rec = _parse_episode_body(episode_id, body)
        if rec is not None:
            out.append(rec)
    out.sort(key=lambda r: r.created_at)
    return out


async def mark_episodes_digested(
    store: MemoryStore,
    user_id: str,
    episode_ids: list[str],
    *,
    scope: MemoryScope = None,
    consolidated_at: datetime | None = None,
) -> None:
    """Mark episodes as digested and stamp last successful semantic consolidation time."""
    if not episode_ids and consolidated_at is None:
        return
    meta = await load_scope_meta(store, user_id, scope=scope)
    meta.digested_ids.update(episode_ids)
    meta.last_semantic_at = consolidated_at or datetime.now(UTC)
    await save_scope_meta(store, user_id, meta, scope=scope)


_EPISODIC_SYSTEM = """\
Summarize this conversation for a later long-term-memory consolidation pass.
Write ONE short paragraph (or a few short sentences) in the user's language covering:
what the user wanted, durable facts/preferences that surfaced, and any correction the
user made. Omit one-off task details and tool noise. Output ONLY the summary text —
no JSON, no title, no bullet list. Keep it under the character budget given below.

Preference / habit rule (strict):
- User preferences and work habits may ONLY come from the user's explicit statements
  or corrections (e.g. "请用中文", "以后别用表格", "我说的是 pnpm 不是 npm").
- Do NOT infer preferences from the task topic, request genre, or one-off ask shape
  (e.g. asking for a mock trial / legal debate / multi-lens research does NOT mean
  "用户偏好法律分析" or "偏好法律对抗形式").
- If no explicit preference/correction appeared, omit preference wording entirely —
  summarize the request only.
"""

_EPISODIC_TIMEOUT_SECONDS = 20.0


class EpisodicSummarizer(Protocol):
    async def summarize(
        self, messages: Sequence[ChatMessage], *, max_chars: int
    ) -> str: ...


class LLMEpisodicSummarizer:
    """Flash-model session summarizer for the episodic layer."""

    def __init__(
        self, provider: LLMProvider, *, role: str = "memory", model: str | None = None
    ) -> None:
        self._provider = provider
        self._profile = get_profile(role)
        from agentcore.config import settings

        self._model = model or settings.platform_model
        self.last_usage: TokenUsage = TokenUsage()
        self.last_model: str = ""

    async def summarize(
        self, messages: Sequence[ChatMessage], *, max_chars: int
    ) -> str:
        convo = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        user_prompt = (
            f"# Character budget\n{max_chars}\n\n# Conversation\n{convo}\n\n"
            "Write the session summary now."
        )
        request = build_request(
            self._profile,
            [
                LLMMessage(role="system", content=_EPISODIC_SYSTEM),
                LLMMessage(role="user", content=user_prompt),
            ],
            stream=False,
            model=self._model,
        )
        try:
            response = await asyncio.wait_for(
                self._provider.complete(request), timeout=_EPISODIC_TIMEOUT_SECONDS
            )
        except TimeoutError:
            logger.warning("memory.episodic_summary_timeout")
            return ""
        self.last_usage = response.usage
        self.last_model = response.model or self._model or ""
        return clamp_summary(response.content or "", max_chars)


def fallback_episode_summary(
    messages: Sequence[ChatMessage], *, max_chars: int = 200
) -> str:
    """Deterministic fallback when the LLM summary is empty: first user turns, clamped."""
    bits: list[str] = []
    for m in messages:
        if m.get("role") == "user" and str(m.get("content") or "").strip():
            bits.append(str(m["content"]).strip())
        if len(bits) >= 3:
            break
    return clamp_summary(" / ".join(bits) if bits else "（本场对话暂无摘要）", max_chars)


def should_run_semantic(
    *,
    undigested_count: int,
    last_semantic_at: datetime | None,
    min_episodes: int,
    max_age_hours: float,
    now: datetime | None = None,
    oldest_undigested_at: datetime | None = None,
) -> bool:
    """True when undigested ≥ min_episodes OR age since last success ≥ max_age_hours.

    Zero undigested ⇒ False (nothing to merge). When there has never been a successful
    semantic pass, ``oldest_undigested_at`` anchors the age window so a single session
    is not consolidated immediately — it waits 24h (or hits the count threshold).
    """
    if undigested_count <= 0:
        return False
    if min_episodes > 0 and undigested_count >= min_episodes:
        return True
    if max_age_hours <= 0:
        return False
    clock = now or datetime.now(UTC)
    anchor = last_semantic_at or oldest_undigested_at
    if anchor is None:
        return False
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return (clock - anchor) >= timedelta(hours=max_age_hours)

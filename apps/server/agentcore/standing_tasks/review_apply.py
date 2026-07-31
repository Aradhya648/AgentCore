"""Apply daily-review ask_user selections server-side (confirm →落盘)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import DocumentRepository
from agentcore.memory.document_store import DocumentMemoryStore
from agentcore.memory.locks import user_memory_lock
from agentcore.memory.rules_injection import append_user_rule
from agentcore.memory.semantic import apply_explicit_memory_ops
from agentcore.memory.store import (
    CORE_MEMORY_FILE,
    PREFERENCES_MEMORY_FILE,
    topic_path,
)
from agentcore.memory.user_memory import (
    PREFERENCES_SECTIONS,
    PROFILE_SECTIONS,
    MemoryAction,
    MemoryOp,
)
from agentcore.tools.builtin.ask_user.schema import option_label
from agentcore.workspace.locate import build_server_workspace, workspace_storage_key
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.stage_dirs import REVIEWS_DIR

logger = get_logger(__name__)

ReviewKind = Literal["preference", "profile", "topic", "rule", "doc"]

_REVIEW_KINDS: frozenset[str] = frozenset(
    {"preference", "profile", "topic", "rule", "doc"}
)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_BODY = 4000


@dataclass(frozen=True, slots=True)
class ReviewProposal:
    kind: ReviewKind
    label: str
    body: str
    slug: str | None = None
    section: str | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewApplyResult:
    applied: int
    skipped: int
    errors: tuple[str, ...] = ()


def option_to_review_proposal(opt: dict[str, Any]) -> ReviewProposal | None:
    """Parse a daily_review option into a typed proposal; None if malformed."""
    kind = str(opt.get("review_kind") or "").strip()
    if kind not in _REVIEW_KINDS:
        return None
    label = option_label(opt)
    body = str(opt.get("body") or opt.get("detail") or "").strip()
    if not label or not body:
        return None
    body = body[:_MAX_BODY]
    slug = str(opt.get("slug") or "").strip() or None
    section = str(opt.get("section") or "").strip() or None
    path = str(opt.get("path") or "").strip() or None
    if kind == "topic" and (not slug or not _SLUG_RE.match(slug)):
        return None
    if kind == "preference" and section and section not in PREFERENCES_SECTIONS:
        section = "沟通偏好"
    if kind == "profile" and section and section not in PROFILE_SECTIONS:
        section = "关于用户的事实"
    if kind == "preference" and not section:
        section = "沟通偏好"
    if kind == "profile" and not section:
        section = "关于用户的事实"
    if kind == "doc" and not path:
        path = f"{REVIEWS_DIR}/{date.today().isoformat()}.md"
    return ReviewProposal(
        kind=kind,  # type: ignore[arg-type]
        label=label,
        body=body,
        slug=slug,
        section=section,
        path=path,
    )


async def apply_daily_review_selections(
    *,
    user_id: str,
    folder_id: str,
    conversation_id: str,
    questions: list[dict[str, Any]],
    selected_labels: list[str],
) -> ReviewApplyResult:
    """Apply checked daily_review proposals. Safe to call from recover settle."""
    selected = {s.strip() for s in selected_labels if s and s.strip()}
    proposals: list[ReviewProposal] = []
    for q in questions:
        for o in q.get("options") or []:
            if not isinstance(o, dict):
                continue
            if option_label(o) not in selected:
                continue
            prop = option_to_review_proposal(o)
            if prop:
                proposals.append(prop)

    if not proposals:
        return ReviewApplyResult(applied=0, skipped=0)

    applied = 0
    skipped = 0
    errors: list[str] = []

    mem_ops: list[MemoryOp] = []
    rules: list[ReviewProposal] = []
    docs: list[ReviewProposal] = []
    for p in proposals:
        if p.kind in ("preference", "profile", "topic"):
            mem_ops.append(_to_memory_op(p, folder_id=folder_id))
        elif p.kind == "rule":
            rules.append(p)
        else:
            docs.append(p)

    if mem_ops:
        async with user_memory_lock(user_id):
            store = DocumentMemoryStore()
            ok = await apply_explicit_memory_ops(
                user_id=user_id, ops=mem_ops, store=store
            )
            if ok:
                applied += len(mem_ops)
            else:
                skipped += len(mem_ops)
                errors.append("记忆写入未生效")

    if rules:
        async with user_memory_lock(user_id), async_session_factory() as session:
            repo = DocumentRepository(session)
            for p in rules:
                try:
                    changed = await append_user_rule(
                        repo, user_id, folder_id=None, content=p.body
                    )
                    if changed:
                        applied += 1
                    else:
                        skipped += 1
                except Exception as e:  # noqa: BLE001
                    skipped += 1
                    errors.append(f"规则「{p.label}」失败")
                    logger.warning(
                        "standing.daily_review.rule_failed",
                        user_id=user_id,
                        error=str(e),
                    )

    if docs:
        key = workspace_storage_key(
            user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
        )
        async with workspace_lock(key):
            backend = build_server_workspace(
                user_id=user_id,
                folder_id=folder_id,
                conversation_id=conversation_id,
            )
            for p in docs:
                path = p.path or f"{REVIEWS_DIR}/{date.today().isoformat()}.md"
                try:
                    data = p.body.encode("utf-8")
                    if not data.endswith(b"\n"):
                        data += b"\n"
                    await backend.write_bytes(path, data)
                    applied += 1
                except Exception as e:  # noqa: BLE001
                    skipped += 1
                    errors.append(f"文档「{p.label}」失败")
                    logger.warning(
                        "standing.daily_review.doc_failed",
                        user_id=user_id,
                        path=path,
                        error=str(e),
                    )

    logger.info(
        "standing.daily_review.applied",
        user_id=user_id,
        applied=applied,
        skipped=skipped,
        at=datetime.now(UTC).isoformat(),
    )
    return ReviewApplyResult(
        applied=applied, skipped=skipped, errors=tuple(errors)
    )


def _to_memory_op(p: ReviewProposal, *, folder_id: str) -> MemoryOp:
    if p.kind == "preference":
        return MemoryOp(
            action=MemoryAction.ADD,
            section=p.section or "沟通偏好",
            content=p.body,
            file=PREFERENCES_MEMORY_FILE,
            scope=None,
        )
    if p.kind == "profile":
        section = p.section or "关于用户的事实"
        # 项目约束 stays project-scoped when standing task has a folder.
        scope = folder_id if section == "项目约束" else None
        return MemoryOp(
            action=MemoryAction.ADD,
            section=section,
            content=p.body,
            file=CORE_MEMORY_FILE,
            scope=scope,
        )
    # topic
    return MemoryOp(
        action=MemoryAction.ADD,
        section="要点",
        content=p.body,
        file=topic_path(p.slug or "review"),
        scope=folder_id,
    )

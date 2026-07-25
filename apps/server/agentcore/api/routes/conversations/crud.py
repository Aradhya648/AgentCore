"""Conversation CRUD: create / list / grouped / get / update / delete / export.

Every route requires an authenticated user and is scoped to that user's own
conversations: reads/writes pass ``user_id`` into the repository so a non-owner
receives 404 (never another user's data — IDOR-safe).

Project membership is birth-time only (``folder_id`` on create); there is no
PATCH …/folder — sessions keep their birth project for life.
"""

import json

from fastapi import APIRouter, Depends, Query, Response

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_conversation_share_repo,
    get_folder_repo,
    get_message_repo,
    get_turn_journal_repo,
)
from agentcore.api.download_headers import download_headers
from agentcore.api.schemas import (
    ConversationListResponse,
    ConversationSummary,
    CreateConversationRequest,
    FolderGroup,
    GroupedConversationsResponse,
    PermissionPresetUpdate,
    StatusResponse,
    UpdateConversationRequest,
)
from agentcore.conversation.common import default_permission_preset_for_user
from agentcore.conversation.export import (
    conversation_to_json,
    conversation_to_markdown,
)
from agentcore.core.errors import NotFoundError
from agentcore.core.logging import get_logger
from agentcore.db.models import Conversation
from agentcore.db.repositories import (
    ConversationRepository,
    ConversationShareRepository,
    FolderRepository,
    MessageRepository,
    TurnJournalRepository,
)

from ._helpers import _get_owned_conversation

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _summary_with_count(conv: Conversation, counts: dict[str, int]) -> ConversationSummary:
    """Build a conversation summary, filling ``message_count`` from a counts map.

    The list/grouped endpoints precompute counts in one query (see
    ``MessageRepository.counts_for_conversations``) and pass the map here so the
    sidebar gets each chat's count without an N+1; absent ids default to 0.
    """
    summary = ConversationSummary.model_validate(conv)
    summary.message_count = counts.get(conv.id, 0)
    return summary


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    user: AuthUser,
    repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
):
    # A non-null target folder must be one of the user's own live folders (else
    # 404), mirroring the move endpoint so a chat can never be born in someone
    # else's or a deleted folder.
    if body.folder_id is not None:
        folder = await folder_repo.get_by_id(body.folder_id, user_id=user.user_id)
        if not folder:
            raise NotFoundError("文件夹不存在")
    # Session permission mode: explicit body wins; else seed from user autonomy default.
    if body.permission_preset is not None:
        preset = body.permission_preset.value
    else:
        preset = (await default_permission_preset_for_user(repo._session, user.user_id)).value
    conv = await repo.create(
        user_id=user.user_id,
        title=body.title,
        folder_id=body.folder_id,
        # Project chats inherit the project's workspace — never write session-level
        # local_* / container columns. 裸聊 keeps desktop local-first intent.
        local_container_root_id=(body.local_container_root_id if body.folder_id is None else None),
        permission_preset=preset,
    )
    return ConversationSummary.model_validate(conv)


@router.post("/{conversation_id}/duplicate", response_model=ConversationSummary, status_code=201)
async def duplicate_conversation(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
):
    """Clone a conversation into a brand-new one carrying a copy of its transcript (克隆对话).

    Owner-scoped (404 for a non-owner / missing source). The copy inherits the source's
    folder (so it stays in the same project/workspace) and local-first intent, with a
    「… 副本」title, then bulk-copies the source's messages via
    ``MessageRepository.copy_all`` (content-level fields only — see that method for what is
    intentionally not carried over, e.g. the team-graph replay journal). Returns the new
    conversation summary with its (copied) message count so the sidebar can insert it.
    """
    src = await conv_repo.get_by_id(conversation_id, user_id=user.user_id)
    if not src:
        raise NotFoundError("对话不存在")
    base = (src.title or "").strip()
    title = (f"{base} 副本" if base else "副本")[:500]
    new_conv = await conv_repo.create(
        user_id=user.user_id,
        title=title,
        folder_id=src.folder_id,
        local_container_root_id=src.local_container_root_id,
        permission_preset=src.permission_preset,
        deep_research_auto=bool(getattr(src, "deep_research_auto", False)),
    )
    count = await msg_repo.copy_all(conversation_id, new_conv.id)
    summary = ConversationSummary.model_validate(new_conv)
    summary.message_count = count
    return summary


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    user: AuthUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    archived: bool = Query(
        False, description="True 返回已归档对话（「已归档」视图）；默认仅返回未归档"
    ),
    repo: ConversationRepository = Depends(get_conversation_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
):
    offset = (page - 1) * page_size
    conversations, total = await repo.list_by_user(
        user.user_id, limit=page_size, offset=offset, archived=archived
    )
    counts = await msg_repo.counts_for_conversations([c.id for c in conversations])
    return ConversationListResponse(
        data=[_summary_with_count(c, counts) for c in conversations],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/grouped", response_model=GroupedConversationsResponse)
async def list_conversations_grouped(
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
):
    """Folders + their conversations + the ungrouped remainder (sidebar).

    Declared before ``/{conversation_id}`` so "grouped" isn't captured as an id.
    A conversation whose folder is missing/deleted falls back to ungrouped.
    """
    folders = await folder_repo.list_by_user(user.user_id)
    conversations = await conv_repo.list_all_by_user(user.user_id)
    counts = await msg_repo.counts_for_conversations([c.id for c in conversations])

    buckets: dict[str, list[ConversationSummary]] = {f.id: [] for f in folders}
    ungrouped: list[ConversationSummary] = []
    for conv in conversations:
        summary = _summary_with_count(conv, counts)
        if conv.folder_id in buckets:
            buckets[conv.folder_id].append(summary)
        else:
            ungrouped.append(summary)

    return GroupedConversationsResponse(
        folders=[
            FolderGroup(
                id=f.id,
                name=f.name,
                mode="local" if f.local_root_id else "cloud",
                local_root_id=f.local_root_id,
                local_subpath=f.local_subpath,
                conversations=buckets[f.id],
            )
            for f in folders
        ],
        ungrouped=ungrouped,
    )


@router.get("/{conversation_id}", response_model=ConversationSummary)
async def get_conversation(
    conversation_id: str,
    user: AuthUser,
    repo: ConversationRepository = Depends(get_conversation_repo),
):
    conv = await repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    return ConversationSummary.model_validate(conv)


@router.put("/{conversation_id}/permission-preset", response_model=ConversationSummary)
async def set_permission_preset(
    conversation_id: str,
    body: PermissionPresetUpdate,
    user: AuthUser,
    repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Switch the session permission mode (降档/升档确认由客户端负责).

    Takes effect on the next turn / durable resume (gate is built at turn entry).
    """
    conv = await repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    previous = conv.permission_preset
    next_preset = body.permission_preset.value
    if previous != next_preset:
        updated = await repo.set_permission_preset(
            conversation_id, user_id=user.user_id, permission_preset=next_preset
        )
        if not updated:
            raise NotFoundError("对话不存在")
        conv = updated
        logger.info(
            "conversation.permission_preset_changed",
            conversation_id=conversation_id,
            previous=previous,
            permission_preset=next_preset,
        )
        from agentcore.runtime.audit.permission_events import (
            record_permission_preset_change,
        )

        await record_permission_preset_change(
            user_id=user.user_id,
            conversation_id=conversation_id,
            previous=previous,
            next_preset=next_preset,
        )
    return ConversationSummary.model_validate(conv)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def update_conversation(
    conversation_id: str,
    body: UpdateConversationRequest,
    user: AuthUser,
    repo: ConversationRepository = Depends(get_conversation_repo),
):
    # Patch only the fields the client sent: an omitted field is left untouched.
    fields = body.model_fields_set
    conv = await repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    if "title" in fields and body.title is not None:
        conv = await repo.update_title(conversation_id, body.title, user_id=user.user_id)
    # Sidebar housekeeping toggles (对话基础功能补齐): pin floats the row to the top,
    # archive hides it from the live list (both reversible, no tri-state → a null is
    # ignored as「unchanged」).
    if "pinned" in fields and body.pinned is not None:
        conv = await repo.set_pinned(conversation_id, body.pinned, user_id=user.user_id)
    if "archived" in fields and body.archived is not None:
        conv = await repo.set_archived(conversation_id, body.archived, user_id=user.user_id)
    if "deep_research_auto" in fields and body.deep_research_auto is not None:
        updated = await repo.set_deep_research_auto(
            conversation_id, body.deep_research_auto, user_id=user.user_id
        )
        if updated:
            conv = updated
    # 会话级模型组合: explicit profile_id pins a combination; null clears → account default.
    if "model_profile_id" in fields:
        profile_id = body.model_profile_id
        if profile_id is not None:
            from agentcore.llm.model_profiles import LlmModelProfileService

            await LlmModelProfileService(repo._session).ensure_profile_usable(
                user.user_id, profile_id
            )
        updated = await repo.set_model_profile(
            conversation_id, profile_id, user_id=user.user_id
        )
        if updated:
            conv = updated
    return ConversationSummary.model_validate(conv)


@router.delete("/{conversation_id}", response_model=StatusResponse)
async def delete_conversation(
    conversation_id: str,
    user: AuthUser,
    repo: ConversationRepository = Depends(get_conversation_repo),
    share_repo: ConversationShareRepository = Depends(get_conversation_share_repo),
):
    deleted = await repo.soft_delete(conversation_id, user_id=user.user_id)
    if not deleted:
        raise NotFoundError("对话不存在")
    # Cascade-revoke any public share links (分享对话): deleting a conversation must
    # kill its read-only links so a stale snapshot can't outlive it. Owner already
    # proven by the soft_delete above, so a blanket per-conversation revoke is safe.
    await share_repo.revoke_all_for_conversation(conversation_id)
    # W3/P1: drop session external grants + organize plan/journal.
    from agentcore.workspace import grant_store, organize_journal, organize_plan_store

    grant_store.clear_conversation(conversation_id)
    organize_plan_store.clear_conversation(conversation_id)
    organize_journal.clear_conversation(conversation_id)
    # L3 team-browser: tear down any live sandbox session (no-op when none exists;
    # teardown errors are swallowed+logged inside the registry, never fail the delete).
    from agentcore.runtime.browser import default_browser_session_registry

    await default_browser_session_registry().close(conversation_id)
    return StatusResponse()


def _download_headers(filename: str) -> dict[str, str]:
    """Content-Disposition for export downloads (RFC 5987); see ``download_headers``."""
    return download_headers(filename, fallback="conversation")


def _safe_export_stem(title: str, conversation_id: str) -> str:
    """A filesystem-safe base name for an export file, derived from the title.

    Strips path separators / control chars and caps the length; falls back to the
    conversation id when the title is empty or strips to nothing.
    """
    cleaned = "".join(
        ch for ch in (title or "") if ch.isprintable() and ch not in '/\\:*?"<>|'
    ).strip()
    cleaned = cleaned[:80].strip()
    return cleaned or f"conversation-{conversation_id[:8]}"


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: str,
    user: AuthUser,
    format: str = Query("md", pattern="^(md|json)$"),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
    journal_repo: TurnJournalRepository = Depends(get_turn_journal_repo),
):
    """Export a conversation's full transcript as a download (导出对话).

    Reads the WHOLE transcript server-side (not a scroll window, so nothing is
    missed) and renders it owner-scoped (404 for a non-owner). ``format=md`` is a
    clean, content-only Markdown record (the default a user reads / pastes);
    ``format=json`` is a full-fidelity dump for power users / re-import. JSON
    projects ``finish_reason`` from turn journal / usage when available. Spend is
    never exported — it lives in the cost ledger, not the message body.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    messages = await msg_repo.list_all_for_conversation(conversation_id)
    stem = _safe_export_stem(conv.title, conversation_id)
    if format == "json":
        journal_map = await journal_repo.load_map([m.id for m in messages])
        payload = conversation_to_json(conv, messages, journal_map=journal_map)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers=_download_headers(f"{stem}.json"),
        )
    content = conversation_to_markdown(conv, messages)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers=_download_headers(f"{stem}.md"),
    )

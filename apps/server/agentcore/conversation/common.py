"""Shared helpers for conversation turn orchestration."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.gate import run_background_llm
from agentcore.core.errors import LLMAuthError
from agentcore.core.log_context import log_context
from agentcore.core.logging import get_logger
from agentcore.core.text import clip_preview
from agentcore.db.base import async_session_factory
from agentcore.db.models import Conversation
from agentcore.db.repositories import ConversationRepository, UserRepository
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.factory import build_provider
from agentcore.llm.profiles import TurnProfiles
from agentcore.llm.provider.protocol import LLMProvider
from agentcore.llm.resolve import (
    resolve_account_worker_selection,
    resolve_conversation_model_selection,
    resolve_credentials,
    resolve_turn_model,
)
from agentcore.memory import (
    TITLE_MAX_CHARS,
    ChatMessage,
    FollowupInput,
    LLMFollowupsGenerator,
    LLMTitleGenerator,
    TitleInput,
    TitleResult,
)
from agentcore.runtime.events import EventSink, title_generated
from agentcore.workspace.locate import LocalBinding

logger = get_logger(__name__)

# Fire-and-forget early title mint (cloud SSE). In-process like schedule_compaction:
# ``_inflight`` dedupes a burst; ``_tasks`` holds refs so a pass is not GC'd mid-flight.
_title_inflight: set[str] = set()
_title_tasks: set[asyncio.Task] = set()


def log_cost_recorded(conversation_id: str, message_id: str | None, cost_runs: list[dict]) -> None:
    """Emit ``cost.recorded`` after a turn's ledger rows persist successfully.

    ``by_role`` breaks spend by structural role (captain / member / vision / …)
    so ``log_stats`` and timeline triage can split team burn without joining DB.
    """
    total_nano = sum(int(r.get("cost_total_nano", 0) or 0) for r in cost_runs)
    models = sorted({str(r.get("model", "?")) for r in cost_runs if r.get("model")})
    by_role: dict[str, dict[str, int]] = {}
    for row in cost_runs:
        role = str(row.get("role") or "?")
        bucket = by_role.setdefault(role, {"runs": 0, "total_nano": 0, "input": 0, "output": 0})
        bucket["runs"] += 1
        bucket["total_nano"] += int(row.get("cost_total_nano", 0) or 0)
        tokens = row.get("tokens") or {}
        bucket["input"] += int(tokens.get("input", 0) or 0)
        bucket["output"] += int(tokens.get("output", 0) or 0)
    logger.info(
        "cost.recorded",
        conversation_id=conversation_id,
        message_id=message_id,
        runs=len(cost_runs),
        total_nano=total_nano,
        total_usd=round(total_nano / 1e9, 6),
        models=models,
        by_role=by_role,
    )


def fallback_title(user_message: str) -> str:
    """Naive title: the first user message, truncated."""
    title = user_message.strip()
    return title[:TITLE_MAX_CHARS] + "…" if len(title) > TITLE_MAX_CHARS else title


# Turn-log message previews: enough of the user prompt / assistant reply to triage
# 「问了什么 / 答得如何」straight from a log line (no DB round-trip), while staying a
# bounded snippet — never the full 正文 (logging.mdc 铁律). ~200 chars ≈ a first paragraph.
LOG_PREVIEW_CHARS = 200


def preview(text: str, *, limit: int = LOG_PREVIEW_CHARS) -> str:
    """Single-line, length-capped preview of message text for a log field."""
    return clip_preview(text, limit)


async def resolve_local_binding(session: AsyncSession, conv: Conversation) -> LocalBinding | None:
    """Resolve a turn's local-mode binding (项目即工作区).

    - **Project chat** (``folder_id`` set): inherit the project's ``local_root_id`` /
      ``local_subpath``. Cloud projects (both NULL) → ``None``.
    - **裸聊**: ``local_root_id`` (explicit) or ``local_container_root_id`` (desktop
      local-first intent). Empty ``local_subpath`` resolves to
      ``conversations/<conversation_id>`` under the container (per-对话隔离；懒建).
      Cloud SSE turns honor both so sidecar-written files stay visible when the
      turn falls back from sidecar to cloud.
    """
    from agentcore.conversation.scratch import (
        bare_chat_local_subpath,
        resolve_conversation_local_binding,
    )
    from agentcore.db.repositories import FolderRepository

    if conv.folder_id:
        folder = await FolderRepository(session).get_by_id_unscoped(conv.folder_id)
        if not folder:
            return None
        return resolve_conversation_local_binding(
            local_root_id=folder.local_root_id,
            local_subpath=folder.local_subpath,
            label=folder.name or "workspace",
        )

    root_id = conv.local_root_id or conv.local_container_root_id
    subpath = conv.local_subpath or (bare_chat_local_subpath(conv.id) if root_id else None)
    return resolve_conversation_local_binding(
        local_root_id=root_id,
        local_subpath=subpath,
        label="workspace",
    )


async def generate_title(
    *,
    provider: LLMProvider,
    conversation_id: str,
    user_message: str,
    assistant_reply: str,
    model: str | None = None,
) -> TitleResult:
    """Best-effort title via the fast model; falls back to truncation.

    ``LLMTitleGenerator`` already retries once on an empty model body (timeout
    does not retry). An empty result after that — or any non-auth call-level
    error — degrades to ``fallback_title`` (first user message, ≤30 chars).

    ``LLMAuthError`` is **re-raised** so ``run_background_llm`` can try user BYOK.
    """
    fallback = fallback_title(user_message)
    if not user_message.strip():
        return TitleResult(title=fallback)

    messages: list[ChatMessage] = [{"role": "user", "content": user_message}]
    if assistant_reply.strip():
        messages.append({"role": "assistant", "content": assistant_reply})

    try:
        result = await LLMTitleGenerator(provider, model=model).generate(
            TitleInput(conversation_id=conversation_id, messages=messages)
        )
        title = result.title or fallback
        return TitleResult(title=title)
    except LLMAuthError:
        # Must surface so ``run_background_llm`` can try user BYOK once.
        raise
    except Exception as e:
        from agentcore.llm.background_failure import classify_background_llm_failure

        logger.warning(
            "chat.title_failed",
            conversation_id=conversation_id,
            error=str(e),
            reason=classify_background_llm_failure(e),
        )
        return TitleResult(title=fallback)


async def _mint_title_background(
    *,
    conversation_id: str,
    user_id: str,
    user_message: str,
    sink: EventSink,
) -> None:
    """Cloud early-title runner: user-message-only LLM mint → conditional write → SSE.

    Never raises. Skips when the conversation already has a title (user rename race).
    Emit is best-effort — a closed sink (short-lived / failed turn) must not undo a
    successful DB write.
    """
    try:
        async with async_session_factory() as session:
            conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
            if conv is None or (conv.title and str(conv.title).strip()):
                return

        async def _runner(credentials: LLMCredentials) -> TitleResult:
            model = resolve_turn_model(credentials)
            provider = build_provider(credentials, purpose="platform_internal")
            try:
                # Cloud early path: first user message only — do not wait for assistant reply.
                return await generate_title(
                    provider=provider,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    assistant_reply="",
                    model=model,
                )
            finally:
                await provider.close()

        result = await run_background_llm(user_id, purpose="title", runner=_runner)
        # No platform/BYOK key, platform quota exhausted, or auth failed both sides
        # → degrade to truncation.
        minted_title = (
            result.value.title if result is not None else fallback_title(user_message)
        )

        if not minted_title:
            return

        async with async_session_factory() as session:
            updated = await ConversationRepository(session).update_title_if_empty(
                conversation_id, minted_title
            )
        if updated is None:
            return

        with contextlib.suppress(Exception):
            sink.emit(title_generated(minted_title, conversation_id=conversation_id))
    except Exception as e:
        from agentcore.llm.background_failure import classify_background_llm_failure

        logger.warning(
            "chat.title_schedule_failed",
            conversation_id=conversation_id,
            error=str(e),
            reason=classify_background_llm_failure(e),
        )
    finally:
        _title_inflight.discard(conversation_id)


def schedule_title_generation(
    *,
    conversation_id: str,
    user_id: str,
    user_message: str,
    sink: EventSink,
) -> None:
    """Fire-and-forget early title mint for a cloud SSE turn (sync schedule only).

    Call after the first user message is persisted (``turn_saved``), in parallel with
    the turn pipeline. No-op when a mint for this conversation is already in flight.
    """
    if conversation_id in _title_inflight:
        return
    _title_inflight.add(conversation_id)
    # Scheduled BEFORE the turn's log_context binds (parallel with the pipeline),
    # so the task inherits no correlation keys — its llm.call (scenario=title)
    # logged fully bare (verified in dev.jsonl). Bind the conversation handle at
    # creation; contextvars are copied into the task. Deliberately no trace_id:
    # the mint is conversation-level, not part of one turn's trace.
    with log_context(conversation_id=conversation_id, user_id=user_id):
        task = asyncio.ensure_future(
            _mint_title_background(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message=user_message,
                sink=sink,
            )
        )
    _title_tasks.add(task)
    task.add_done_callback(_title_tasks.discard)


@dataclass(frozen=True)
class FollowupsMintResult:
    """Minted chips plus optional soft-unavailable reason (None = legitimate empty)."""

    items: list[str]
    unavailable_reason: str | None = None


async def generate_followups(
    *,
    provider: LLMProvider | None,
    conversation_id: str,
    user_message: str,
    assistant_reply: str,
    model: str | None = None,
    motion_card: dict | None = None,
) -> FollowupsMintResult:
    """Best-effort turn-level「下一步」suggestions; never raises except ``LLMAuthError``.

    Pure garnish (CEO→user quick-reply chips). Non-auth failures collapse to empty
    chips + ``unavailable_reason``. ``LLMAuthError`` re-raises so
    ``run_background_llm`` can try user BYOK once.

    When ``motion_card`` is a compliant worker proposition card, a deterministic「开辩」
    chip is always prepended (even if the LLM path yields nothing).
    """
    from agentcore.llm.background_failure import classify_background_llm_failure
    from agentcore.memory.followups import (
        format_motion_card_followup,
        merge_motion_card_followup,
    )

    if not assistant_reply.strip():
        return FollowupsMintResult(items=[])

    injected: str | None = None
    if isinstance(motion_card, dict):
        motion = str(motion_card.get("motion") or "").strip()
        if motion:
            injected = format_motion_card_followup(motion_card)

    messages: list[ChatMessage] = []
    if user_message.strip():
        messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": assistant_reply})

    llm_items: list[str] = []
    fail_reason: str | None = None
    if provider is not None:
        try:
            llm_items = await LLMFollowupsGenerator(provider, model=model).generate(
                FollowupInput(conversation_id=conversation_id, messages=messages)
            )
        except LLMAuthError:
            # Must surface so ``run_background_llm`` can try user BYOK once.
            raise
        except Exception as e:
            fail_reason = classify_background_llm_failure(e)
            logger.warning(
                "chat.followups_failed",
                conversation_id=conversation_id,
                error=str(e),
                reason=fail_reason,
            )
            llm_items = []

    items = merge_motion_card_followup(injected, llm_items)
    if items:
        return FollowupsMintResult(items=items)
    return FollowupsMintResult(items=[], unavailable_reason=fail_reason)


async def resolve_turn_profiles(
    session: AsyncSession,
    conv: Conversation,
    user_id: str,
    credentials: LLMCredentials | None = None,
) -> TurnProfiles:
    """Resolve model + static profiles for this turn.

    Expands the conversation's model combination profile (or account default) into
    main + optional worker override. Empty worker slot → workers follow main.
    Cross-origin / cross-provider worker credentials land in ``agent_provider_id``.
    """
    from agentcore.llm.profiles import PLATFORM_PROVIDER_SENTINEL

    if credentials is None:
        credentials = await resolve_credentials(session, user_id, "user_facing")
    selection = await resolve_conversation_model_selection(session, conv, user_id)
    overrides: dict[str, str] = {}
    agent_provider_id: str | None = None
    worker = await resolve_account_worker_selection(session, user_id, conv=conv)
    if worker is not None and (
        worker.model != selection.model
        or worker.origin != selection.origin
        or worker.provider_id != selection.provider_id
    ):
        overrides["agent"] = worker.model
        if worker.origin != selection.origin or worker.provider_id != selection.provider_id:
            agent_provider_id = (
                PLATFORM_PROVIDER_SENTINEL
                if worker.origin == "platform"
                else worker.provider_id
            )
    return TurnProfiles(
        model=selection.model,
        model_overrides=overrides,
        agent_provider_id=agent_provider_id,
    )


# Legacy name used by conversation service exports.
resolve_profile_set = resolve_turn_profiles


async def resolve_memory_enabled(session: AsyncSession, user_id: str) -> bool:
    """Long-term memory is product-always-on (定案 A); never read ``users.memory_enabled``.

    ``session`` / ``user_id`` kept so call sites stay unchanged. Runtime may still
    pass ``memory_enabled=False`` internally (unit tests / suspension frames).
    """
    _ = (session, user_id)
    return True


async def resolve_conversation_history_access(
    session: AsyncSession, user_id: str
) -> bool:
    """Conversation-log access is product-always-on (定案 A); never read the user column.

    ``session`` / ``user_id`` kept so call sites stay unchanged. Runtime may still
    pass ``conversation_history_access=False`` internally (unit tests).
    """
    _ = (session, user_id)
    return True


async def resolve_autonomy_policy(session: AsyncSession, user_id: str):
    """User-global *default recipe* AutonomyPolicy (seeds new conversations only).

    Runtime gates must use :func:`resolve_permission_axes` / the conversation
    column — not this. Kept for settings API and create-time seeding.
    """
    from agentcore.core.types import AutonomyPolicy

    user = await UserRepository(session).get_by_id(user_id)
    raw = (user.autonomy_policy if user else None) or AutonomyPolicy.LESS_INTERRUPT.value
    try:
        return AutonomyPolicy(raw)
    except ValueError:
        return AutonomyPolicy.LESS_INTERRUPT


def parse_permission_axes(raw: dict | None):
    """Coerce a stored / wire permission_axes mapping; unknown → less_interrupt defaults."""
    from agentcore.core.types import PermissionAxes

    return PermissionAxes.from_mapping(raw)


async def resolve_permission_axes(session: AsyncSession, conversation_id: str):
    """This turn's permission axes — conversation column is the single source of truth."""
    from agentcore.db.repositories import ConversationRepository

    conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
    return parse_permission_axes(conv.permission_axes if conv else None)


async def default_permission_axes_for_user(session: AsyncSession, user_id: str):
    """Map the user's autonomy recipe → PermissionAxes for a new conversation."""
    from agentcore.core.types import recipe_to_axes

    return recipe_to_axes(await resolve_autonomy_policy(session, user_id))


# Back-compat aliases used by older call sites during the axes migration.
resolve_permission_preset = resolve_permission_axes
default_permission_preset_for_user = default_permission_axes_for_user
parse_permission_preset = parse_permission_axes

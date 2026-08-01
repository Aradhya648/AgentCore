"""Production crash-lease DelegateTool factory (wired at process startup).

Rebuilds LLM credentials / workspace / profiles via the same ambient resolution as
resume, then calls :func:`wire_crash_turn` (sibling of ``wire_resume_turn``). Any
rebuild failure returns ``None`` so the sweeper falls through to existing salvage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import agentcore.runtime.pipeline as pipeline_pkg
from agentcore.config import settings
from agentcore.conversation.common import (
    resolve_conversation_history_access,
    resolve_local_binding,
    resolve_memory_enabled,
    resolve_permission_axes,
    resolve_profile_set,
)
from agentcore.conversation.turn_backend import build_turn_backend
from agentcore.conversation.turn_runner import session_callbacks, suspension_callbacks
from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import BoardRepository, ConversationRepository
from agentcore.llm.credentials import bind_credential_pricing_context
from agentcore.llm.profiles import turn_profiles_for_turn
from agentcore.llm.resolve import resolve_credentials
from agentcore.memory import assemble_turn_rules, default_memory_store, load_memory_topics
from agentcore.runtime.context import build_workspace_context
from agentcore.runtime.facts import FactKind
from agentcore.runtime.pipeline.resume.wire import wire_crash_turn
from agentcore.runtime.resolve.prompt import (
    assemble_system_prompt,
    compose_worker_base_prompt,
)
from agentcore.runtime.runs.types import RunKind
from agentcore.tools.sandbox.exec_languages import resolve_exec_languages

if TYPE_CHECKING:
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.leases.model import TurnLeaseRow
    from agentcore.runtime.turn_state import TurnState
    from agentcore.tools.builtin.delegate import DelegateTool

logger = get_logger(__name__)

def _user_message_from_journal(entries: tuple[dict[str, Any], ...] | list[dict]) -> str | None:
    """Extract the turn's user line from ``turn_started`` (required for worker playbooks)."""
    for entry in entries:
        if (entry.get("kind") or "") != FactKind.TURN_STARTED.value:
            continue
        payload = entry.get("payload") or {}
        user_message = payload.get("user_message")
        if isinstance(user_message, str) and user_message.strip():
            return user_message
        return ""
    return None

def _captain_run_id_from_journal(
    entries: tuple[dict[str, Any], ...] | list[dict],
) -> str | None:
    for entry in entries:
        if (entry.get("kind") or "") != "run_started":
            continue
        payload = entry.get("payload") or {}
        if payload.get("kind") == RunKind.CAPTAIN.value:
            run_id = payload.get("run_id")
            if isinstance(run_id, str) and run_id:
                return run_id
    return None

async def production_crash_delegate_factory(
    lease: TurnLeaseRow,
    state: TurnState,
    *,
    sink: EventSink,
) -> DelegateTool | None:
    """Rebuild a live ``DelegateTool`` for crash redrive, or ``None`` on any failure."""
    message_id = lease.message_id
    conversation_id = lease.conversation_id
    user_id = lease.user_id
    try:
        user_message = _user_message_from_journal(state.entries)
        if user_message is None:
            raise ValueError("journal missing turn_started user_message")

        async with async_session_factory() as session:
            conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
            if conv is None:
                raise ValueError("conversation not found")
            folder_id = conv.folder_id
            local_binding = await resolve_local_binding(session, conv)
            llm_credentials = await resolve_credentials(session, user_id, "user_facing")
            if llm_credentials is None:
                raise ValueError("llm credentials unavailable")
            profile_set = await resolve_profile_set(
                session, conv, user_id, credentials=llm_credentials
            )
            memory_enabled = await resolve_memory_enabled(session, user_id)
            conversation_history_access = await resolve_conversation_history_access(
                session, user_id
            )
            permission_axes = await resolve_permission_axes(session, conversation_id)
            board = await BoardRepository(session).get_by_conversation_id(
                conversation_id, user_id=user_id
            )
            board_id = board.id if board else None


        profiles = turn_profiles_for_turn(profile_set, llm_credentials)
        bind_credential_pricing_context(llm_credentials)
        # mypy Protocol/async-gen mismatch (prepare/resume are quarantined; this module is not).
        llm = await pipeline_pkg.build_turn_router(
            llm_credentials, user_id=user_id, profiles=profiles
        )

        backend = await build_turn_backend(
            user_id=user_id,
            conversation_id=conversation_id,
            folder_id=folder_id,
            sink=sink,
            local_binding=local_binding,
        )
        session_saver, session_loader = session_callbacks(conversation_id)
        suspension_saver, suspension_deleter = suspension_callbacks()

        # Fresh worker base (no suspension frame): same helpers as prepare_fresh_turn,
        # attachments empty — unfinished nodes carry their own task text in the plan.
        memory_store = default_memory_store()
        user_rules_markdown, memory_markdown = await assemble_turn_rules(
            memory_store,
            user_id,
            folder_id=folder_id,
            enabled=memory_enabled,
            max_docs=settings.max_instruction_docs,
            max_chars=settings.max_instruction_chars,
        )
        memory_topics = await load_memory_topics(
            memory_store, user_id, folder_id=folder_id, enabled=memory_enabled
        )
        exec_languages = await resolve_exec_languages(backend)
        # Crash rebuild has no live client header → fail-closed (no Host pretence).
        workspace_facts = build_workspace_context(
            backend,
            desktop_online=False,
            exec_languages=exec_languages,
        )
        system_prompt = assemble_system_prompt(
            memory_markdown=memory_markdown,
            user_rules_markdown=user_rules_markdown,
            workspace_context=workspace_facts,
        )
        base_system_prompt = compose_worker_base_prompt(
            system_prompt,
            memory_topics=memory_topics,
            memory_enabled=memory_enabled,
            attachment_context="",
        )

        captain_run_id = _captain_run_id_from_journal(state.entries) or new_id()
        wired = await wire_crash_turn(
            llm=llm,
            sink=sink,
            backend=backend,
            board_id=board_id,
            conversation_id=conversation_id,
            message_id=message_id,
            captain_run_id=captain_run_id,
            user_id=user_id,
            folder_id=folder_id,
            memory_enabled=memory_enabled,
            conversation_history_access=conversation_history_access,
            base_system_prompt=base_system_prompt,
            user_message=user_message,
            journal_entries=list(state.entries),
            profiles=profiles,
            permission_axes=permission_axes,
            session_saver=session_saver,
            session_loader=session_loader,
            suspension_saver=suspension_saver,
            suspension_deleter=suspension_deleter,
            has_memory_topics=bool(memory_topics),
        )
        logger.info(
            "recover.crash_delegate_ready",
            message_id=message_id,
            conversation_id=conversation_id,
            unfinished=len(state.unfinished_run_ids),
        )
        return wired.delegate_tool
    except Exception as e:  # noqa: BLE001 — any rebuild miss → salvage, no extra fallback
        logger.warning(
            "recover.crash_delegate_rebuild_failed",
            message_id=message_id,
            conversation_id=conversation_id,
            unfinished=len(state.unfinished_run_ids),
            error=str(e),
        )
        return None

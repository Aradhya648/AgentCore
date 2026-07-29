"""Resolve prepare phase: CEO toolset assembly and attachment context."""

from __future__ import annotations

from typing import Any

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.llm.profiles import TurnProfiles as ProfileSet
from agentcore.memory import default_memory_store
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.events import (
    EventSink,
)
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.runtime.sessions import (
    SessionLoader,
    SessionSaver,
)
from agentcore.runtime.skills import (
    SkillRegistry,
)
from agentcore.runtime.suspension import (
    SuspensionDeleter,
    SuspensionSaver,
)
from agentcore.tools.builtin import (
    build_ceo_tool_registry,
)
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.builtin.consult_memory import ConsultMemoryTool
from agentcore.tools.builtin.consult_skill import ConsultSkillTool
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.builtin.read_conversation import ReadConversationTool
from agentcore.tools.builtin.remember import RememberTool
from agentcore.tools.builtin.search_conversations import SearchConversationsTool
from agentcore.tools.builtin.update_project_profile import UpdateProjectProfileTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.workspace.attachment_parse import (
    ATTACHMENT_INLINE_MAX_CHARS,
    truncate_for_prompt,
)

logger = get_logger(__name__)

# Soft-miss / gate-off notes for conversation attachments (跨会话对话日志访问定案 P1).
# Never fall back to client shallow ``text`` — that would silently fake a deep read.
_CONV_ATTACH_SOFT_MISS = (
    "无法打开该对话（可能不存在、已删除、为 handoff，或不在可访问范围内）。"
)
_CONV_ATTACH_GATE_OFF = (
    "跨会话对话日志访问已关闭（conversation_history_access=off），"
    "服务端拒绝深读该对话；未注入客户端浅文。"
    "请在设置中开启「允许 AI 查阅历史对话」后重试。"
)
_CONV_ATTACH_NO_ID = "缺少 conversation_id，无法服务端深读；未注入客户端浅文。"
_CONV_ATTACH_HOST = (
    "那是本回合正在进行的宿主会话——请直接看本会话工作记忆，无需附件深读。"
)
_CONV_ATTACH_TRUNC_NOTE = (
    "\n\n… [truncated for prompt; 完整日志请派查阅 Worker `read_conversation` 续读"
    "（conversation_id={cid}{cursor_part}）]"
)


def _wire_worker_memory_tools(
    worker_tools: ToolRegistry,
    *,
    memory_enabled: bool = True,
    folder_id: str | None = None,
    has_memory_topics: bool = False,
) -> None:
    """Register ``consult_memory`` on the delegated worker toolset when memory is on
    AND the turn has at least one consultable TOPIC note.

    Same store + project scope as the CEO path (``folder_id`` ⇒ project-then-global
    resolution). Off or empty topics ⇒ not wired — mirrors ``_assemble_ceo_toolset``
    (caller-supplied ``memory_enabled`` + empty-catalog alignment: no directory ⇒ no tool).
    """
    if memory_enabled and has_memory_topics:
        worker_tools.register(
            ConsultMemoryTool(store=default_memory_store(), folder_id=folder_id)
        )


def _wire_worker_conversation_log_tools(
    worker_tools: ToolRegistry,
    *,
    conversation_history_access: bool = True,
    folder_id: str | None = None,
) -> None:
    """Register cross-session log tools when the privacy gate is on.

    ``search_conversations`` / ``read_conversation`` are ``manual_wire`` worker-only
    tools — never auto-registered by ``build_worker_registry``, never on the CEO
    toolset. Gate off ⇒ not wired (跨会话对话日志访问定案).
    """
    if not conversation_history_access:
        return
    worker_tools.register(SearchConversationsTool(folder_id=folder_id))
    worker_tools.register(ReadConversationTool())


def _assemble_ceo_toolset(
    *,
    llm,
    sink: EventSink,
    base_system_prompt: str,
    user_message: str,
    history: list[dict],
    worker_tools: ToolRegistry,
    base_tool_context: ToolContext,
    profiles: ProfileSet,
    approval_gate: ApprovalGate | None,
    session_store,
    session_saver: SessionSaver | None,
    session_loader: SessionLoader | None,
    conversation_id: str,
    captain_run_id: str,
    checkpoint_enabled: bool,
    message_id: str,
    suspension_saver: SuspensionSaver | None,
    suspension_deleter: SuspensionDeleter | None,
    backend_location: str,
    skill_registry: SkillRegistry,
    memory_enabled: bool = True,
    conversation_history_access: bool = True,
    folder_id: str | None = None,
    has_memory_topics: bool = False,
    permission_axes=None,
    advertise_bind_local_folder: bool = False,
    desktop_online: bool = False,
) -> tuple[DelegateTool, Any, ToolRegistry]:
    """Wire the CEO coordinator's toolset (delegate + read/retrieval +
    consult_skill + an optional consult_memory + an optional ask_user), shared by a
    fresh turn and a 2b resume.

    The CEO is a COORDINATOR: it holds only the read/retrieval built-ins plus the
    orchestration primitives, never the mutation tools (those live with workers via
    ``delegate``). ``base_system_prompt`` is the CLEAN prompt handed to delegate
    (reused verbatim by workers — no CEO-chat hints). ``skill_registry`` backs
    the CEO-only ``consult_skill`` tool (提示词瘦身 P2): the advanced-mechanism guidance
    is pulled on demand instead of riding the prompt every turn. ``message_id`` + the
    suspension closures arm durable plan_review pauses (结构化挂起 2b) on the
    top-level delegate. Returns ``(delegate_tool, debate_tool, chat_tools)`` — the
    tools whose accumulated usage/ledger/citations the caller folds into the turn totals.
    ``debate_tool`` is always constructed and registered (same always-on tier as ``delegate``).
    """
    delegate_tool = DelegateTool(
        llm=llm,
        sink=sink,
        system_prompt=base_system_prompt,
        user_message=user_message,
        history=history,
        tools=worker_tools,
        base_tool_context=base_tool_context,
        captain_run_id=captain_run_id,
        approval_gate=approval_gate,
        profile_set=profiles,
        session_store=session_store,
        session_saver=session_saver,
        session_loader=session_loader,
        conversation_id=conversation_id,
        registry=default_interaction_registry(),
        checkpoint_timeout_seconds=settings.checkpoint_timeout_seconds,
        checkpoint_enabled=checkpoint_enabled,
        message_id=message_id,
        suspension_saver=suspension_saver,
        suspension_deleter=suspension_deleter,
        folder_id=folder_id,
        memory_enabled=memory_enabled,
        conversation_history_access=conversation_history_access,
        permission_axes=permission_axes,
    )
    chat_tools = build_ceo_tool_registry(
        desktop_online=desktop_online,
        permission_axes=permission_axes,
        backend_location=backend_location,
    )
    chat_tools.register(delegate_tool)
    # debate (辩论编排原语): the CEO's对抗性多视角思考 primitive, sibling to delegate —
    # ALWAYS registered (拍板: 模型须能从闲聊开辩), schema 只留短触发 (长文在
    # debate_and_review skill). 非终结且把辩手/主持人的 usage/ledger/citations 累加
    # 在实例上, 由本回合折回总账。→ docs/03-AI核心/辩论编排设计.md
    # Membership / audience live on tool ``registration`` (tools.registration);
    # construction stays here because Delegate/Debate need heavy turn deps.
    # Lazy import: debate package may be mid-edit by a parallel agent.
    from agentcore.tools.builtin.debate import DebateTool

    debate_tool = DebateTool(
        llm=llm,
        sink=sink,
        system_prompt=base_system_prompt,
        user_message=user_message,
        tools=worker_tools,
        base_tool_context=base_tool_context,
        profile_set=profiles,
        captain_run_id=captain_run_id,
        approval_gate=approval_gate,
        # ambient 掌舵：有活跃用户即武装（checkpoint_enabled）；辩论永不硬停，轮次边界非阻塞
        # drain steer 队列。自治 / handoff 不武装 → 纯裁判自判。
        conversation_id=conversation_id,
        ambient_armed=checkpoint_enabled,
        message_id=message_id,
        suspension_saver=suspension_saver,
        suspension_deleter=suspension_deleter,
        folder_id=folder_id,
        memory_enabled=memory_enabled,
        conversation_history_access=conversation_history_access,
        permission_axes=permission_axes,
        registry=default_interaction_registry(),
        # 批 D1：共享会话 roster，开赛探测幕1 透镜 session 作证人。
        session_store=session_store,
        session_loader=session_loader,
    )
    chat_tools.register(debate_tool)
    from agentcore.runtime.resolve.ceo_surface import (
        coordination_surface_active,
        register_coordination_surface,
    )

    # Injection == execution gate for the coord tools (active_coordination):
    # idle chat drops replan + the coordination suite. When a session is already
    # live at assemble time, register here so the first LLM round offers wait.
    # Mid-turn / pre-LLM: promote_coordination_surface_if_needed (tool_round +
    # ensure_coordination_surface_before_llm) when a session starts later.
    register_coordination_surface(
        chat_tools,
        delegate_tool=delegate_tool,
        sink=sink,
        include=coordination_surface_active(
            execution_id=base_tool_context.execution_id
        ),
    )
    # consult_skill (提示词瘦身 P2): always wired (not live-user gated) so the CEO can
    # pull any advanced-mechanism guidance on demand; the always-on 能力目录 in the
    # prompt lists the skills whose required tools are actually wired this turn.
    chat_tools.register(ConsultSkillTool(registry=skill_registry))
    # Memory gate (caller-supplied ``memory_enabled``; product resolve always on /
    # 定案 A): False ⇒ no remember / consult_memory / update_project_profile
    # (always-injected 画像 already gated in pipeline/run.py).
    # consult_memory is further gated by ``has_memory_topics`` — empty catalog ⇒ no tool
    # (aligns with「目录为空不渲染」; compose_ceo_chat_prompt keys the directory on this
    # tool being present). ``remember`` / explore profile stay on whenever memory is on.
    if memory_enabled:
        mem_store = default_memory_store()
        if has_memory_topics:
            # ``folder_id`` ⇒ project-then-global topic resolution (Agent记忆与知识系统 §二).
            chat_tools.register(ConsultMemoryTool(store=mem_store, folder_id=folder_id))
        # Explicit remember: a user directive is recorded as a USER RULE immediately (§5.7 分流
        # — inferred preferences still go through offline consolidation).
        chat_tools.register(RememberTool(folder_id=folder_id))
        # Explore-act close-out: project ``画像.md`` mid-turn write (§1.5 product exception).
        # Only when the conversation is bound to a project — bare chat has no project layer.
        if folder_id:
            chat_tools.register(
                UpdateProjectProfileTool(
                    folder_id=folder_id,
                    store=mem_store,
                    prompt_holders=[delegate_tool, debate_tool],
                )
            )
    if checkpoint_enabled:
        # 结构化挂起 2b: arm the ask_user pause with the SAME durable closures as the
        # delegate plan_review — message_id keys the frame, the turn-level constants
        # (captain_run_id / clean base prompt / user_message) let resume re-wire the
        # CEO toolset, and the saver/deleter persist before the wait + drop after a
        # live resolve. A disconnect mid-ask leaves a frame ``POST .../resume`` maps
        # the answer back onto.
        chat_tools.register(
            AskUserTool(
                sink=sink,
                conversation_id=conversation_id,
                timeout_seconds=settings.checkpoint_timeout_seconds,
                captain_run_id=captain_run_id,
                base_system_prompt=base_system_prompt,
                user_message=user_message,
                history=history,
                message_id=message_id,
                suspension_saver=suspension_saver,
                suspension_deleter=suspension_deleter,
                folder_id=folder_id,
                memory_enabled=memory_enabled,
                conversation_history_access=conversation_history_access,
                advertise_bind_local_folder=advertise_bind_local_folder,
            )
        )
    return delegate_tool, debate_tool, chat_tools


async def _deep_read_conversation_attachment(
    att: dict,
    *,
    name: str,
    user_id: str | None,
    host_conversation_id: str | None,
    conversation_history_access: bool,
) -> str:
    """Server-side deep transcript for ``kind=conversation`` — never client shallow text.

    Privacy gate off / missing id / owner soft-miss / handoff / host → explicit note.
    Over-long → first prompt-capped chunk via ``log_export.chunk_transcript`` +
    Worker ``read_conversation`` continuation hint.
    """
    from agentcore.conversation.log_export import (
        chunk_transcript,
        render_conversation_log,
    )
    from agentcore.db.base import async_session_factory
    from agentcore.db.repositories import (
        ConversationRepository,
        MessageRepository,
        TurnJournalRepository,
    )

    cid = str(att.get("conversation_id") or "").strip()
    if not conversation_history_access:
        return f"--- Conversation: {name} [deep-read denied] ---\n{_CONV_ATTACH_GATE_OFF}"
    if not cid:
        return f"--- Conversation: {name} ---\n{_CONV_ATTACH_NO_ID}"
    if host_conversation_id and cid == host_conversation_id:
        return f"--- Conversation: {name} ---\n{_CONV_ATTACH_HOST}"
    if not user_id:
        return f"--- Conversation: {name} ---\n{_CONV_ATTACH_SOFT_MISS}"

    async with async_session_factory() as session:
        conv = await ConversationRepository(session).get_by_id(cid, user_id=user_id)
        if conv is None or conv.mode == "handoff":
            return f"--- Conversation: {name} ---\n{_CONV_ATTACH_SOFT_MISS}"
        messages = list(await MessageRepository(session).list_all_for_conversation(cid))
        assistant_ids = [m.id for m in messages if m.role == "assistant"]
        journal_map = await TurnJournalRepository(session).load_map(assistant_ids)
        full = render_conversation_log(conv, messages, journal_map)
        chunk = chunk_transcript(
            full,
            conversation=conv,
            messages=messages,
            cursor=None,
            max_chars=ATTACHMENT_INLINE_MAX_CHARS,
        )

    title = chunk.title or name
    note = " (truncated; continue via read_conversation)" if chunk.truncated else ""
    body = chunk.transcript
    if chunk.truncated:
        cursor_part = f", next_cursor={chunk.next_cursor}" if chunk.next_cursor else ""
        body += _CONV_ATTACH_TRUNC_NOTE.format(cid=cid, cursor_part=cursor_part)
    return f"--- Conversation: {title}{note} ---\n{body}"


async def _build_attachment_context(
    attachments: list[dict] | None,
    *,
    user_id: str | None = None,
    host_conversation_id: str | None = None,
    conversation_history_access: bool = True,
) -> str | None:
    """Render user-referenced files / dirs / conversations into a prompt block.

    Text files carry pre-extracted text; pre-parsed binaries (docx/pdf/…) carry
    inline text (context-capped) plus a pointer to the ``*.md`` workspace copy;
    unscanned spreadsheet binaries carry only a workspace path (引用即驻留 —
    model must parse via ``code_execute``). Directories carry a recursive file
    listing (paths only); ``kind=conversation`` is **server deep-read** via
    ``log_export`` (client shallow ``text`` is ignored). A file with a
    ``workspace_path`` was persisted into the workspace, so the header points
    the agent at that durable path. Returns None when there is nothing to inject
    so the base prompt stays unchanged.
    """
    if not attachments:
        return None

    blocks: list[str] = []
    resident = False
    has_binary = False
    has_preparsed = False
    has_conversation = False
    for att in attachments:
        name = att.get("name") or "untitled"
        kind = att.get("kind") or "file"
        text = (att.get("text") or "").strip()
        binary = bool(att.get("binary"))
        ws_path = att.get("workspace_path")
        parse_status = att.get("parse_status")
        parsed_path = att.get("parsed_workspace_path")

        if kind == "dir":
            if not text:
                continue
            path = att.get("path") or name
            note = " (partial listing)" if att.get("truncated") else ""
            blocks.append(
                f"--- Directory: {name} ({path}){note} ---\n"
                f"File paths (contents not included):\n{text}"
            )
        elif kind == "conversation":
            has_conversation = True
            blocks.append(
                await _deep_read_conversation_attachment(
                    att,
                    name=name,
                    user_id=user_id,
                    host_conversation_id=host_conversation_id,
                    conversation_history_access=conversation_history_access,
                )
            )
        elif parse_status == "scanned" and text:
            path = ws_path or att.get("path") or name
            if ws_path:
                resident = True
            has_preparsed = True
            copy_note = f" [scan note → {parsed_path}]" if parsed_path else ""
            blocks.append(
                f"--- File: {name} ({path}) [scanned / no text layer]{copy_note} ---\n{text}"
            )
        elif parse_status == "ok" and text:
            path = ws_path or att.get("path") or name
            if ws_path:
                resident = True
            has_preparsed = True
            body, clipped = truncate_for_prompt(text)
            client_trunc = bool(att.get("truncated"))
            flags: list[str] = []
            if parsed_path and parsed_path != path:
                flags.append(f"pre-parsed → {parsed_path}")
            if clipped or client_trunc:
                flags.append("truncated")
            flag_s = f" [{'; '.join(flags)}]" if flags else ""
            block = f"--- File: {name} ({path}){flag_s} ---\n{body}"
            if clipped and parsed_path:
                block += (
                    f"\n\n… [truncated at {len(body)} chars for context; "
                    f"full extracted text is at {parsed_path}]"
                )
            elif clipped:
                block += f"\n\n… [truncated at {len(body)} chars for context]"
            blocks.append(block)
        elif binary or (ws_path and not text):
            # Binary (or empty-body resident / preparse failed): path only.
            path = ws_path or att.get("path") or name
            if ws_path:
                resident = True
            has_binary = True
            blocks.append(
                f"--- File: {name} ({path}) [binary] ---\n"
                "This is a binary file saved in the workspace (no text inline). "
                "Open and parse it with code_execute using the workspace-relative "
                "path above (e.g. openpyxl for .xlsx). Do NOT use an OS absolute path."
            )
        elif text:
            path = ws_path or att.get("path") or name
            if ws_path:
                resident = True
            note = " (truncated)" if att.get("truncated") else ""
            blocks.append(f"--- File: {name} ({path}){note} ---\n{text}")

    if not blocks:
        return None

    body = "\n\n".join(blocks)
    resident_note = (
        " Files shown with an in-workspace path have been saved into your "
        "workspace — read or edit them with the file tools by that path rather "
        "than trusting only the (possibly truncated) text below."
        if resident
        else ""
    )
    binary_note = (
        " Binary attachments have no inline body: use code_execute on the "
        "workspace-relative path. Never hard-read an OS absolute path outside "
        "the workspace (it will fail or hang)."
        if has_binary
        else ""
    )
    preparsed_note = (
        " Some office/PDF attachments were pre-parsed at upload: inline text may "
        "be truncated — use the ``*.md`` workspace copy (or the original path) "
        "with file tools for the full extract."
        if has_preparsed
        else ""
    )
    conversation_note = (
        " A Conversation block is a server-rendered deep transcript (messages +"
        " process layer); when truncated, delegate a Worker with"
        " ``read_conversation`` to continue — do not treat a truncated block as"
        " the full log."
        if has_conversation
        else ""
    )
    return (
        "<attached_files>\n"
        "The user attached the following files, directories and past "
        "conversations as actionable inputs for this turn—not mere optional "
        "reference. When the user narrows scope to these materials and/or "
        "existing workspace products, start from them (gap analysis or a "
        "revision); do not idle solely because a full repo is missing. Cite "
        "them by name when relevant. Directory entries list file paths only "
        "(file contents are not included)."
        f"{conversation_note}"
        f"{resident_note}{binary_note}{preparsed_note}\n\n"
        f"{body}\n"
        "</attached_files>"
    )

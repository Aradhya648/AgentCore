"""Fresh-turn Phase 2: approval gate, CEO toolset, chat system prompt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.config import settings
from agentcore.core.types import DEFAULT_PERMISSION_AXES, PermissionAxes
from agentcore.llm.profiles import TurnProfiles
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.context import (
    ContextAssembler,
    SectionOrder,
    build_workspace_overview,
    desktop_client_can_bind,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.runtime.resolve.prompt import compose_ceo_chat_prompt
from agentcore.runtime.sessions import SessionLoader, SessionSaver, default_session_registry
from agentcore.runtime.suspension import SuspensionDeleter, SuspensionSaver
from agentcore.tools.builtin import (
    approval_class_tool_names,
    delegation_grantable_tool_names,
    per_call_tool_names,
)
from agentcore.tools.registration import host_class_tool_names, register_board_ceo_tools
from agentcore.tools.registry import ToolRegistry
from agentcore.workspace.protocol import WorkspaceBackend

from .prepare import PreparedTurn


@dataclass
class AssembledTurn:
    """Phase-2 outputs: wired CEO tools + assembled chat prompt."""

    approval_gate: ApprovalGate | None
    permission_axes: PermissionAxes
    delegate_tool: Any
    debate_tool: Any
    chat_tools: ToolRegistry
    chat_system_prompt: str


async def assemble_ceo_turn(
    *,
    prepared: PreparedTurn,
    conversation_id: str,
    user_message: str,
    history: list[dict],
    sink: EventSink,
    backend: WorkspaceBackend,
    folder_id: str | None,
    memory_enabled: bool,
    conversation_history_access: bool = True,
    approvals_enabled: bool,
    permission_axes: PermissionAxes | None,
    profiles: TurnProfiles,
    captain_run_id: str,
    message_id: str,
    session_saver: SessionSaver | None,
    session_loader: SessionLoader | None,
    suspension_saver: SuspensionSaver | None,
    suspension_deleter: SuspensionDeleter | None,
    x_client_platform: str | None,
) -> AssembledTurn:
    """Assemble the CEO coordinator toolset and the turn's chat system prompt."""
    # The CEO owns the conversation and replies directly, but it is a
    # COORDINATOR: it carries only the read / retrieval built-ins
    # (``build_ceo_tool_registry`` — web_search/read_url/file_read/file_list/
    # grep) plus the on-demand orchestration primitive ``delegate``. It holds
    # NONE of the production / mutation tools (file_write/str_replace/
    # file_delete/file_move/code_execute); any work that produces or changes an
    # artifact is handed to a worker. There is no mandatory pre-turn
    # orchestrator pass — the CEO itself decides when/at what granularity to
    # delegate. ``delegate`` is NON-terminal: workers' products return to the
    # CEO's own ReAct loop, which writes a short user-facing overview in its own
    # voice (D3 / 决策①: per-worker detail is shown separately in the UI).
    # Workers get the full production ``worker_tools`` plus, for any worker with
    # ``depth < MAX_DELEGATION_DEPTH``, ``delegate``+``replan`` (delegation is on by
    # default within the depth cap — worker captains may nest one sub-team; depth-2
    # sub-workers are leaves; per-captain fan-out capped at ``MAX_WORKER_SUBDELEGATIONS``).
    # Approval gate (one per turn so an "allow for the rest of this turn" grant
    # is scoped to this message and does not leak across turns). It is wired into
    # the CEO's loop, but with the coordinator boundary the CEO holds no
    # GRANTABLE tools — so approvals now bite at the WORKER layer: the SAME
    # instance is handed to the delegate tool, which forwards it to workers ONLY
    # in local mode (双模式工作区 P2d 执行门) — so a delegated worker can't run
    # code / mutate files on the user's real machine without consent, while a
    # cloud team stays un-gated (isolated sandbox).
    if permission_axes is None:
        permission_axes = DEFAULT_PERMISSION_AXES
    approval_gate = (
        ApprovalGate(
            sink=sink,
            conversation_id=conversation_id,
            registry=default_interaction_registry(),
            timeout_seconds=settings.approval_timeout_seconds,
            timeout_overrides=settings.approval_timeout_overrides,
            file_op_tools=approval_class_tool_names(),
            per_call_tools=per_call_tool_names(),
            delegation_grantable_tools=delegation_grantable_tool_names(),
            host_class_tools=host_class_tool_names(),
            permission_axes=permission_axes,
        )
        if (settings.approval_gate_enabled and approvals_enabled)
        else None
    )
    # The conversation's live roster (留人, 乙 热修): delegate registers each
    # COMPLETED worker here as a recoverable RunSession, and revise recalls one to
    # continue on its own draft. Conversation-scoped (P2) — fetched from the
    # process-wide registry so it SURVIVES across turns ("改下刚才那个" works next
    # turn); bounded by TTL + count + byte caps, idle conversations reaped. An
    # expiry / miss falls back to 甲 (re-delegate). Cross-process persistence: P3.
    session_store = default_session_registry().get_or_create(conversation_id)
    # Structured DAG checkpoints (结构化挂起 2a) share the SAME gate as ask_user
    # (a live interactive user): an autonomous handoff job has no client to
    # answer, so a checkpoint there would only ever time out. Computed here —
    # before the delegate tool — because delegate consumes it too (it suspends
    # the WaveScheduler at a wave boundary when a step is marked checkpoint_after).
    checkpoint_enabled = settings.checkpoint_gate_enabled and approvals_enabled
    # The delegate tool gets the worker base prompt — the CLEAN base (no CEO chat
    # hints, reused verbatim by workers in runs/executor.py — they must not be told
    # about a delegate tool they do not hold) plus this turn's attachment block.
    # message_id + the suspension closures arm durable plan_review pauses (结构化
    # 挂起 2b) on the top-level delegate.
    # Look up via ``pipeline.run`` so governance tests can monkeypatch the seam.
    from agentcore.runtime.pipeline import run as run_mod

    delegate_tool, debate_tool, chat_tools = run_mod._assemble_ceo_toolset(
        llm=prepared.llm,
        sink=sink,
        base_system_prompt=prepared.worker_base_prompt,
        user_message=user_message,
        history=history,
        worker_tools=prepared.worker_tools,
        base_tool_context=prepared.base_tool_context,
        profiles=profiles,
        approval_gate=approval_gate,
        session_store=session_store,
        session_saver=session_saver,
        session_loader=session_loader,
        conversation_id=conversation_id,
        captain_run_id=captain_run_id,
        checkpoint_enabled=checkpoint_enabled,
        message_id=message_id,
        suspension_saver=suspension_saver,
        suspension_deleter=suspension_deleter,
        backend_location=backend.location,
        skill_registry=prepared.skill_registry,
        memory_enabled=memory_enabled,
        conversation_history_access=conversation_history_access,
        folder_id=folder_id,
        has_memory_topics=bool(prepared.memory_topics),
        permission_axes=permission_axes,
        # Same live-user gate as ask_user itself, plus desktop-only: web/mobile omit.
        advertise_bind_local_folder=checkpoint_enabled
        and desktop_client_can_bind(x_client_platform),
        desktop_online=desktop_client_can_bind(x_client_platform)
        or backend.location == "local",
    )

    # AI 协作白板: in a 白板会话, hand the CEO the board tools so it can draw on
    # (``board_ops``, §六 M2) and read (``board_read``, §九) the user's open canvas.
    # Registered AFTER the coordinator toolset is assembled and BEFORE ``ceo_tool_names``
    # is read, so they join the LLM's function catalog this turn. Only here (board-bound
    # runs) — every other chat never sees them.
    if prepared.board_channel is not None:
        register_board_ceo_tools(chat_tools)

    # The entry chat agent gets the SLIM CEO core + the always-on 能力目录 (提示词
    # 瘦身 P2) + inline citation guidance. The directory lists only the skills whose
    # required tools are actually wired this turn (derived from the assembled CEO
    # toolset), so it never advertises a capability the CEO does not hold (e.g.
    # the ask_user_* skills appear only on the live-user path, when ask_user is wired)
    # — the same invariant the old per-hint gating enforced. The advanced「怎么做」
    # detail no longer rides every turn; the CEO pulls it via consult_skill.
    ceo_tool_names = {schema.name for schema in chat_tools.list_all()}
    explore_reason: str | None = None
    project_nav_stale = False
    project_profile_empty_soft = False
    if memory_enabled and folder_id:
        from agentcore.memory.explore_profile import (
            compute_workspace_explore_fingerprint,
            evaluate_explore_fingerprint_drift,
            project_profile_explore_reason,
            resolve_folder_workspace_key,
            resolve_hard_explore_reason,
        )

        mem_store = run_mod.default_memory_store()
        current_key = await resolve_folder_workspace_key(folder_id)
        explore_reason = await project_profile_explore_reason(
            mem_store,
            prepared.base_tool_context.user_id,
            folder_id,
            current_workspace_key=current_key,
        )
        explore_reason, project_profile_empty_soft = resolve_hard_explore_reason(
            explore_reason,
            user_message,
        )
        # R2 soft hint + R1 background refresh: fingerprint drift never blocks.
        if not explore_reason:
            live_fp = await compute_workspace_explore_fingerprint(backend)
            project_nav_stale = await evaluate_explore_fingerprint_drift(
                mem_store,
                prepared.base_tool_context.user_id,
                folder_id,
                live_fingerprint=live_fp,
                current_workspace_key=current_key,
            )
            if project_nav_stale:
                from agentcore.memory.explore_refresh import (
                    build_workspace_explore_snapshot,
                    schedule_explore_refresh,
                )

                snapshot = await build_workspace_explore_snapshot(backend)
                schedule_explore_refresh(
                    user_id=prepared.base_tool_context.user_id,
                    folder_id=folder_id,
                    workspace_key=current_key,
                    snapshot=snapshot,
                    live_fingerprint=live_fp,
                )
    # Sink explore-pending into ToolContext so delegate can suppress structured
    # files_written inference / require ≥2 explore workers（prompt 块 delegate 读不到）。
    # Worker write_scope=explore_memory：写工具层拦出 AgentCore/ 与 文档/项目/。
    # Cleared in-place by update_project_profile on successful write.
    if explore_reason:
        prepared.base_tool_context.cold_start_explore_pending = True
        prepared.base_tool_context.write_scope = "explore_memory"
    chat_system_prompt = compose_ceo_chat_prompt(
        prepared.system_prompt,
        skill_registry=prepared.skill_registry,
        ceo_tool_names=ceo_tool_names,
        memory_topics=prepared.memory_topics,
        cold_start_explore=explore_reason or False,
        project_nav_stale=project_nav_stale,
        project_profile_empty_soft=project_profile_empty_soft,
    )
    # Real-time workspace overview (工作区上下文): a compact, newest-first listing of
    # the files already on disk in this conversation's workspace, so the CEO can
    # triage / delegate without spending a blind file_list round. Generated fresh
    # each turn from the live backend (never indexed → never stale); "" when empty /
    # unavailable. Workers don't get this — they already receive the richer per-run
    # manifest (runs/executor_context._workspace_manifest).
    workspace_overview = await build_workspace_overview(
        backend, shared_workspace=folder_id is not None
    )
    # 跨回合同图追加的回显通道 (CEO-only): history replays no tool I/O, so the newest
    # appendable graph's execution_id must ride the prompt to stay visible next turn.
    # "" when the conversation has no team graph yet (section drops out).
    from agentcore.runtime.delegate.graph_append import build_recent_graph_context

    recent_graph_context = await build_recent_graph_context(
        conversation_id=conversation_id,
        exclude_message_id=message_id,
    )
    # 可用性诚实性 · 甲：偏窄短问 → 复用最近 delivery_status 发卡到本回合答复面。
    from agentcore.runtime.delegate.delivery_status import (
        maybe_reinject_recent_delivery_for_availability_ask,
    )

    await maybe_reinject_recent_delivery_for_availability_ask(
        sink,
        conversation_id=conversation_id,
        user_message=user_message,
        exclude_turn_id=message_id,
    )
    # Variable tail AFTER the stable hint stack (workspace overview + recent graph +
    # attachments) so the CEO prefix (base + hints) stays byte-identical across turns
    # and rides the prefix cache even when the workspace / attachments change. Empty
    # sections are dropped, so a turn with none is byte-identical to the bare CEO prompt.
    chat_system_prompt = (
        ContextAssembler()
        .add("ceo_prompt", chat_system_prompt, SectionOrder.BASE)
        .add("workspace_context", workspace_overview, SectionOrder.WORKSPACE_OVERVIEW)
        .add(
            "recent_team_graph",
            recent_graph_context,
            SectionOrder.RECENT_TEAM_GRAPH,
        )
        .add(
            "attachment_context",
            prepared.attachment_context,
            SectionOrder.ATTACHMENT,
        )
        # COST-004 (仅观测起步): 埋本回合 CEO 系统提示的逐段 chars + 是否越软闸, 攒据用、零行为
        # 改动。此处是「易变尾 (workspace/attachment)」与稳定前缀 (ceo_prompt) 同框的 choke
        # point, 正是未来「仅裁易变尾」软闸的作用点 (项目审计-成本性能专项 §九)。
        .observe(scope="ceo_turn", soft_cap=settings.prompt_budget_char_soft_cap)
        .render()
    )

    # COST-004 tools 面: 补工具 schema JSON chars / 约算 token（原先只观测系统提示，编排工具
    # ~10k 字符盲区）。纯 structlog，不改 SSE / API 契约。
    from agentcore.runtime.resolve.ceo_surface import observe_tools_offered

    observe_tools_offered(chat_tools, scope="ceo_turn")

    return AssembledTurn(
        approval_gate=approval_gate,
        permission_axes=permission_axes,
        delegate_tool=delegate_tool,
        debate_tool=debate_tool,
        chat_tools=chat_tools,
        chat_system_prompt=chat_system_prompt,
    )

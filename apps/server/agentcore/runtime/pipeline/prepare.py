"""Fresh-turn Phase 1: memory, prompts, channels, LLM, base tool context."""

from __future__ import annotations

import json
from dataclasses import dataclass

import agentcore.runtime.pipeline as pipeline_pkg
from agentcore.board.channel import BoardChannel
from agentcore.config import settings
from agentcore.core.types import new_id
from agentcore.desktop.channel import DesktopClientChannel
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import TurnProfiles
from agentcore.memory import (
    assemble_turn_rules,
    load_memory_topics,
)
from agentcore.runtime.context import build_workspace_context, desktop_client_can_bind
from agentcore.runtime.costing import RunCost
from agentcore.runtime.events import EventSink
from agentcore.runtime.interaction import default_interaction_registry
from agentcore.runtime.resolve.prepare import (
    _build_attachment_context,
    _wire_worker_conversation_log_tools,
    _wire_worker_memory_tools,
)
from agentcore.runtime.resolve.prompt import (
    assemble_system_prompt,
    compose_worker_base_prompt,
)
from agentcore.runtime.skills import build_system_skill_registry
from agentcore.tools.builtin import build_worker_registry
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.vision import build_vision_reader
from agentcore.workspace.locate import workspace_channel_for_tools
from agentcore.workspace.protocol import WorkspaceBackend


@dataclass
class PreparedTurn:
    """Phase-1 outputs shared by assemble + execute."""

    llm: object
    system_prompt: str
    worker_base_prompt: str
    worker_tools: ToolRegistry
    skill_registry: object
    board_channel: BoardChannel | None
    base_tool_context: ToolContext
    vision_cost_sink: list[RunCost]
    attachment_context: str
    memory_topics: list[str]
    bound_execution_id: str
    execution_id_token: object


async def prepare_fresh_turn(
    *,
    conversation_id: str,
    user_id: str,
    backend: WorkspaceBackend,
    sink: EventSink,
    folder_id: str | None,
    board_id: str | None,
    attachments: list[dict] | None,
    memory_enabled: bool,
    conversation_history_access: bool = True,
    permission_axes,
    llm_credentials: LLMCredentials | None,
    x_client_platform: str | None,
    profiles: TurnProfiles | None = None,
) -> PreparedTurn:
    """Build the stable base prompt, worker tools, channels, and tool context."""
    # Long-term memory injection is gated by the caller-supplied ``memory_enabled``
    # flag (product resolve is always True / 定案 A): when False we inject nothing
    # (an empty body drops the <rules> memory section) — retained for internal
    # False-path tests and durable suspension frames.
    # 记忆作用域 (§5.2): the always-injected core spans global 偏好.md + 画像.md and — when
    # the conversation is in a project — that project's 画像.md, concatenated global-first
    # (stable prefix) into one <rules> body. ``memory_enabled=False`` ⇒ "".
    # Look up via ``pipeline.run`` so governance tests can monkeypatch the seam
    # (``test_pipeline_governance._patch_pipeline``).
    from agentcore.runtime.pipeline import run as run_mod

    memory_store = run_mod.default_memory_store()
    # 两档措辞 + 跨文件预算 (Agent记忆与知识系统 §二 / §5.7): the <rules> block now carries the
    # user's OWN rules (authoritative) ahead of AI memory (soft), under one MAX_INSTRUCTION_*
    # budget with global-priority survival — replacing the per-file memory cap. AI memory rides
    # the (patchable) store seam; user rules load through their own session and degrade to none
    # on failure, so this can never break a turn. With no user rules the memory body is
    # byte-identical to the prior assembly (prefix-cache safe).
    user_rules_markdown, memory_markdown = await assemble_turn_rules(
        memory_store,
        user_id,
        folder_id=folder_id,
        enabled=memory_enabled,
        max_docs=settings.max_instruction_docs,
        max_chars=settings.max_instruction_chars,
    )
    # 记忆主题目录 (记忆文件夹化 §六 / 作用域 §5.2): the on-demand TOPIC notes (主题/<slug>.md)
    # are never injected wholesale — only their NAMES (merged across global + project)
    # ride the CEO prompt, and the CEO pulls a note's full body via consult_memory when
    # relevant. Same master-switch gate: off ⇒ [] ⇒ no directory rendered, no tool wired.
    # Empty topics (memory on but no 主题 notes) likewise omit consult_memory — reuse this
    # list for the wire gate below so we do not re-list the store.
    memory_topics = await load_memory_topics(
        memory_store, user_id, folder_id=folder_id, enabled=memory_enabled
    )
    has_memory_topics = bool(memory_topics)
    # Clean, stable base (base + date + workspace facts + memory): NO attachments,
    # NO CEO hints. This is the cacheable prefix shared by the CEO and reused
    # verbatim by workers. Environment facts ride the shared base so workers also
    # know execution location (防止空云 scratch 里幻觉装软件). The (per-turn, variable)
    # attachment block is appended LAST below — after the stable CEO hint stack —
    # so a turn carrying attached files does not bust DeepSeek's prefix cache for
    # the hints (缓存友好: 易变内容置于稳定前缀之后).
    desktop_online = desktop_client_can_bind(x_client_platform) or backend.location == "local"
    from agentcore.tools.sandbox.exec_languages import resolve_exec_languages

    exec_languages = await resolve_exec_languages(backend)
    # Desktop channel early: MCP discovery (stdio on desktop) must complete before
    # workspace_context stamps mcp= — same ClientTool sink the turn will stream.
    desktop_channel = (
        DesktopClientChannel(
            sink=sink,
            conversation_id=conversation_id,
            registry=default_interaction_registry(),
            timeout_seconds=settings.board_op_timeout_seconds,
        )
        if desktop_online
        else None
    )
    from agentcore.tools.mcp import discover_mcp_tools, mcp_capability_label, register_mcp_tools

    mcp_discover = await discover_mcp_tools(desktop_channel)
    mcp_label = mcp_capability_label(mcp_discover, desktop_online=desktop_online)
    workspace_facts = build_workspace_context(
        backend,
        desktop_online=desktop_online,
        exec_languages=exec_languages,
        host_axis=permission_axes.host if permission_axes is not None else None,
        mcp_enabled=mcp_discover.tool_count > 0,
        mcp_label=mcp_label,
    )
    system_prompt = assemble_system_prompt(
        memory_markdown=memory_markdown,
        user_rules_markdown=user_rules_markdown,
        workspace_context=workspace_facts,
    )
    attachment_context = await _build_attachment_context(
        attachments,
        user_id=user_id,
        host_conversation_id=conversation_id,
        conversation_history_access=conversation_history_access,
    )
    # Workers hold no CEO hints; their base is the shared base + optional simplified
    # 记忆主题目录 + the same attachment block at the end — byte-identical to the old
    # single-call assembly when memory is off and no topics exist.
    worker_base_prompt = compose_worker_base_prompt(
        system_prompt,
        memory_topics=memory_topics,
        memory_enabled=memory_enabled,
        attachment_context=attachment_context,
    )
    worker_tools = build_worker_registry(
        backend=backend,
        permission_axes=permission_axes,
        languages=exec_languages if backend.location == "local" else None,
        desktop_online=desktop_online,
    )
    register_mcp_tools(worker_tools, mcp_discover)
    _wire_worker_memory_tools(
        worker_tools,
        memory_enabled=memory_enabled,
        folder_id=folder_id,
        has_memory_topics=has_memory_topics,
    )
    _wire_worker_conversation_log_tools(
        worker_tools,
        conversation_history_access=conversation_history_access,
        folder_id=folder_id,
    )
    # System skills (提示词瘦身 P2): the advanced-mechanism guidance the CEO pulls
    # on demand via consult_skill. Built once per turn; backs the tool AND the
    # always-on 能力目录 rendered into the CEO prompt below. Capability packs
    # (e.g. legal) layer in for every user when the deployment gate is on.
    from agentcore.runtime.capability_packs import enabled_packs

    skill_registry = build_system_skill_registry(enabled_packs=enabled_packs())
    # 真·多模型辩手：回合 llm = DeepSeek 默认（``build_provider``，保留可测试打桩的 seam）
    # 外包一层 ProviderRouter。无前缀模型（CEO / 委派 / 主持人）照走默认，仅辩论辩手 side
    # 带 ``provider/model`` 前缀的调用路由到对应厂商。无厂商 key 时只是空包一层，零行为变化。
    # Cross-provider Worker 默认经 ``build_turn_router`` 注入 BYOK extras。
    # 路由器接管默认 + 厂商 client 的生命周期，由下方 finally 的 ``await llm.close()`` 释放。
    from agentcore.llm.credentials import bind_credential_pricing_context

    # Call-level pricing + optional user unit card (同路贯穿 calculate_cost).
    bind_credential_pricing_context(llm_credentials)
    llm = await pipeline_pkg.build_turn_router(
        llm_credentials, user_id=user_id, profiles=profiles
    )
    # AI 协作白板 (§六 M2): a board-bound turn gets a BoardChannel so ``board_ops`` can
    # reach the user's open canvas via the desktop. Bound to this board + conversation
    # on the shared interaction bridge (same registry the resolve endpoint settles).
    # ``None`` for an ordinary chat — then the tool below is never wired either.
    board_channel = (
        BoardChannel(
            sink=sink,
            conversation_id=conversation_id,
            board_id=board_id,
            registry=default_interaction_registry(),
            timeout_seconds=settings.board_op_timeout_seconds,
        )
        if board_id
        else None
    )
    # desktop_channel created earlier (MCP discovery); reuse the same instance.
    workspace_channel = workspace_channel_for_tools(
        backend,
        sink=sink,
        conversation_id=conversation_id,
    )

    # AI 协作白板 §九.4 Gap ②: the turn-level vision cost sink. ``board_read`` appends a
    # priced ``role=vision`` ledger row here per 读图 sub-call. Shared by REFERENCE across
    # every derived run context (executor uses ``replace``, which copies the list ref), so
    # a vision call from any run — captain or a delegated worker — lands in this one list,
    # collected into ``cost_runs`` after the turn. Empty unless a board_read actually billed.
    vision_cost_sink: list[RunCost] = []

    # 深度研究自治：会话旗标 + 自动开辩计数（kickoff / ceo_format 经 ToolContext 读取）。
    from agentcore.runtime.deep_research_auto import load_deep_research_auto_state

    deep_research_auto, deep_research_auto_debate_count = (
        await load_deep_research_auto_state(conversation_id)
    )

    # The workspace backend is resolved per conversation by the caller
    # (folder space vs. its own conversation space) and injected here. The
    # engine and tools never see a Path — they only touch ``context.backend``.
    base_tool_context = ToolContext(
        execution_id=new_id(),
        run_id=new_id(),
        agent_id="default",
        backend=backend,
        user_id=user_id,
        conversation_id=conversation_id,
        permission_preset=(
            json.dumps(permission_axes.to_dict()) if permission_axes is not None else None
        ),
        deep_research_auto=deep_research_auto,
        deep_research_auto_debate_count=deep_research_auto_debate_count,
        board_channel=board_channel,
        desktop_channel=desktop_channel,
        workspace_channel=workspace_channel,
        # §九.4: vision provider (QwenVL) — set VISION_API_KEY to enable; None ⇒
        # board_read returns a clean「读图能力未配置」error (「插上即用」).
        vision_reader=build_vision_reader(),
        cost_sink=vision_cost_sink,
        shared_workspace=folder_id is not None,
    )
    from agentcore.runtime.coordination.session import current_execution_id
    from agentcore.runtime.delegate.delivery_status import current_delivery_verdict

    bound_execution_id = base_tool_context.execution_id
    execution_id_token = current_execution_id.set(bound_execution_id)
    # Fresh turn: prior batch delivery verdict must not leak into finish_guard.
    current_delivery_verdict.set(None)

    # Pillar B: if a background execution is already live for this conversation,
    # adopt it so the CEO wait path / interjection routing share one registry key.
    from agentcore.runtime.coordination.session import adopt_active_execution

    adopted = adopt_active_execution(conversation_id, event_sink=sink)
    if adopted is not None:
        bound_execution_id = adopted.execution_id
        base_tool_context.execution_id = adopted.execution_id
        current_execution_id.set(adopted.execution_id)

    return PreparedTurn(
        llm=llm,
        system_prompt=system_prompt,
        worker_base_prompt=worker_base_prompt,
        worker_tools=worker_tools,
        skill_registry=skill_registry,
        board_channel=board_channel,
        base_tool_context=base_tool_context,
        vision_cost_sink=vision_cost_sink,
        attachment_context=attachment_context,
        memory_topics=memory_topics,
        bound_execution_id=bound_execution_id,
        execution_id_token=execution_id_token,
    )

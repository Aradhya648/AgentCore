"""DelegateTool — CEO main-agent orchestration primitive."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.text import clip_preview
from agentcore.core.types import (
    DEFAULT_PERMISSION_AXES,
    PermissionAxes,
    ToolApproval,
    ToolCategory,
    ToolEffect,
    new_id,
)
from agentcore.llm.profiles import TurnProfiles as ProfileSet
from agentcore.llm.profiles import default_turn_profiles as default_profile_set
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.delegate.drive import drive
from agentcore.runtime.delegate.plan_events import plan_event
from agentcore.runtime.delegate.steer import apply_steer, record_plan_snapshot
from agentcore.runtime.delegate.supervised import (
    SupervisedRun,
    apply_replan,
    finalize_stopped,
)
from agentcore.runtime.events import EventSink, plan_revised
from agentcore.tools.builtin.delegate.schema import (
    DELEGATE_DESCRIPTION,
    DELEGATE_PARAMETERS,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_CEO_ONLY,
    CeoWire,
    ToolRegistration,
    ToolSurface,
)
from agentcore.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agentcore.runtime.approvals import ApprovalGate
    from agentcore.runtime.costing import RunCost
    from agentcore.runtime.ports import ClientRequestBridge
    from agentcore.runtime.runs.notewall import NoteWall
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.scheduler import BoundaryReason
    from agentcore.runtime.runs.types import RunSpec, RunState
    from agentcore.runtime.sessions import SessionLoader, SessionSaver, SessionStore
    from agentcore.runtime.suspension import SuspensionDeleter, SuspensionSaver

logger = get_logger(__name__)


def _has_wave_boundary_features(tasks_raw: list[Any]) -> bool:
    """True when any task needs BIND / CHECKPOINT / DAG wave-boundary machinery."""
    for task in tasks_raw:
        if not isinstance(task, dict):
            continue
        if task.get("depends_on") or task.get("checkpoint_after") or task.get("bind_after_deps"):
            return True
    return False


def _has_deep_deliverable_signal(tasks_raw: list[Any]) -> bool:
    """True when any task's deliverable signals deep / long-form file work.

    Orchestration shape (single worker, no DAG) is orthogonal to output weight —
    deep deliverable must not be collapsed into auto-light.
    """
    from agentcore.runtime.runs.builder import _parse_deliverable
    from agentcore.runtime.runs.worker_budget import is_deep_deliverable

    for task in tasks_raw:
        if not isinstance(task, dict):
            continue
        if is_deep_deliverable(_parse_deliverable(task)):
            return True
    return False


def _blocks_explicit_light(tasks_raw: list[Any]) -> bool:
    """True when explicit light must be ignored (long-form only, not file landing)."""
    from agentcore.runtime.runs.builder import _parse_deliverable
    from agentcore.runtime.runs.worker_budget import blocks_light_complexity

    for task in tasks_raw:
        if not isinstance(task, dict):
            continue
        if blocks_light_complexity(_parse_deliverable(task)):
            return True
    return False


def _should_auto_light_delegate(tasks_raw: list[Any]) -> bool:
    """True when a single dependency-free worker needs no multi-agent coordination.

    Skips auto-light when deliverable signals deep work (files / artifacts / long-form)
    so budget mapping can still promote standard → deep.
    """
    if len(tasks_raw) != 1:
        return False
    task = tasks_raw[0]
    if not isinstance(task, dict):
        return False
    if _has_wave_boundary_features([task]):
        return False
    return not _has_deep_deliverable_signal([task])


# Cap on how many nodes `delegate.started` lists by name/task — a big fan-out shouldn't
# balloon one log line; `nodes` still carries the true total.
_DELEGATE_LOG_AGENTS_CAP = 12


class DelegateTool:
    """CEO-agent tool that delegates sub-tasks to a Run plan and returns their
    products for the CEO to synthesize (non-terminal, Option 1).
    """

    registration = ToolRegistration(
        surface=ToolSurface.CEO_ORCHESTRATION,
        audience=AUDIENCE_CEO_ONLY,
        ceo_wire=CeoWire.ALWAYS,
    )

    def __init__(
        self,
        *,
        llm: OpenAICompatibleProvider,
        sink: EventSink,
        system_prompt: str,
        user_message: str,
        history: list[dict],
        tools: ToolRegistry,
        base_tool_context: ToolContext,
        profile_set: ProfileSet | None = None,
        max_parallel: int | None = None,
        captain_run_id: str | None = None,
        approval_gate: ApprovalGate | None = None,
        session_store: SessionStore | None = None,
        session_saver: SessionSaver | None = None,
        session_loader: SessionLoader | None = None,
        conversation_id: str | None = None,
        registry: ClientRequestBridge | None = None,
        checkpoint_timeout_seconds: float | None = None,
        checkpoint_enabled: bool = False,
        message_id: str | None = None,
        suspension_saver: SuspensionSaver | None = None,
        suspension_deleter: SuspensionDeleter | None = None,
        folder_id: str | None = None,
        memory_enabled: bool = True,
        conversation_history_access: bool = True,
        permission_axes: PermissionAxes | None = None,
        depth: int = 0,
    ) -> None:
        self._llm = llm
        self._sink = sink
        self._system_prompt = system_prompt
        self._user_message = user_message
        self._history = history
        self._tools = tools
        self._base_tool_context = base_tool_context
        self._profile_set = profile_set or default_profile_set()
        self._max_parallel = max_parallel
        self._approval_gate = approval_gate
        self._permission_axes = permission_axes or DEFAULT_PERMISSION_AXES
        self._auto_grant_pending = False
        self._captain_run_id = captain_run_id
        self._session_store = session_store
        self._session_saver = session_saver
        self._session_loader = session_loader
        self._depth = depth
        self._conversation_id = conversation_id
        self._registry = registry
        self._checkpoint_timeout_seconds = checkpoint_timeout_seconds
        self._checkpoint_enabled = checkpoint_enabled
        self._message_id = message_id
        self._suspension_saver = suspension_saver
        self._suspension_deleter = suspension_deleter
        # Turn-level project scope, carried purely so a durable plan_review pause captures it
        # into the frame — the resumed toolset re-wires consult_memory to the same project
        # (Agent记忆与知识系统 §二). Not used by the delegate drive itself.
        self._folder_id = folder_id
        # Same capture-only role: the memory gate rides the frame so resume re-wires
        # consult_memory exactly as this turn did (False ⇒ stays off).
        self._memory_enabled = memory_enabled
        self._conversation_history_access = conversation_history_access
        self._children: list[DelegateTool] = []
        self._calls = 0
        # Cumulative sub-workers spawned by this captain (worker leads only).
        self._sub_workers_spawned = 0
        from agentcore.runtime.costing import WorkerResultAccumulator

        self._acc = WorkerResultAccumulator()
        # 续派次数（CEO continue_from + redirect 热修；不计辩论）— turn_metrics.revises。
        self._continuation_ids: list[str] = []
        self._supervised: SupervisedRun | None = None
        self._pending_boundary: tuple[BoundaryReason, list[RunSpec]] | None = None
        # 挂起即收口 (②): set by the CHECKPOINT boundary hook when it finalizes the turn at a
        # plan_review pause (frame saved) — ``drive`` reads it after the scheduler soft-pauses
        # and returns a SUSPEND ToolResult. False on every ordinary drive.
        self._pending_pause: bool = False
        # 团队便签墙 (§2.2 通 / §2.3 合·对账): the most recent batch's wall,
        # set by ``drive`` when it
        # builds the executor so the CEO finalize (``format_for_ceo``, both the normal-终态 and the
        # ``replan(stop)`` finalize_stopped paths) can fold the team's outstanding 决定 / 认领 into
        # 语义边界对账. None until a batch runs (a CEO that never delegated has no wall).
        self._note_wall: NoteWall | None = None
        # Turn-level team consensus (team_brief): survives across delegate calls in one CEO turn.
        self._team_brief: str | None = None
        # Last resolved note-wall coordination mode (wall|none); resume/replan reuse it.
        self._coordination: str = "none"
        # 本批 CEO 预贴便签（execute 解析后暂存）：开工卡挂在 setup_note_wall 之前，
        # 耐久帧从这里捕获（persist_kickoff），否则恢复后 seed 便签永久丢失。
        self._seed_notes: list[dict[str, str]] = []
        # Same-gap streak for completion_criteria_unmet (同缺口收敛护栏).
        self._completion_gap_streak: tuple[tuple[str, ...], int] | None = None
        # 当前 execute 展开的 playbook 名（team_preview pre-auth 判定用）。
        self._active_playbook: str | None = None
        # Per-call force flag for isomorphic re-delegation (set in execute).
        self._delegate_force: bool = False

    def spawn_lead_subteam(self, captain_run_id: str, captain_depth: int):
        """Mint a nested lead handle (阶段2); construction stays in the tools package."""
        from agentcore.tools.builtin.delegate.nesting import make_lead_subteam

        return make_lead_subteam(self, captain_run_id, captain_depth)

    def _kickoff_system_prompt(self) -> str:
        return self._system_prompt

    def _kickoff_tool_name(self) -> str:
        return "delegate"

    @property
    def usage(self) -> dict[str, int]:
        return self._acc.usage

    @property
    def run_ledger(self) -> list[RunCost]:
        return self._acc.run_ledger

    @property
    def citations(self) -> list[dict[str, Any]]:
        return self._acc.citations

    @property
    def continuation_count(self) -> int:
        """CEO 侧续派次数（continue_from + redirect 热修；不计辩论编排续写）。"""
        n = len(self._continuation_ids)
        for child in self._children:
            n += child.continuation_count
        return n

    def note_continuation(self, run_id: str) -> None:
        """Record a successful CEO-side continuation for turn_metrics.revises."""
        self._continuation_ids.append(run_id)

    def note_completion_gap(self, fingerprint: tuple[str, ...]) -> int:
        """Record an unmet completion gap; return consecutive count for this fingerprint."""
        prev = self._completion_gap_streak
        count = prev[1] + 1 if prev is not None and prev[0] == fingerprint else 1
        self._completion_gap_streak = (fingerprint, count)
        return count

    def clear_completion_gap_streak(self) -> None:
        """Reset same-gap streak after criteria are met (or unrelated success)."""
        self._completion_gap_streak = None

    @property
    def collab(self) -> dict[str, int]:
        """Turn-level 协作质量 tally (学·度量 §2.5): boundary_yields / scope_signals /
        escalations, rolled up across this turn's batches (and nested sub-teams)."""
        return self._acc.collab

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="delegate",
            description=DELEGATE_DESCRIPTION,
            parameters=DELEGATE_PARAMETERS,
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        from agentcore.runtime.delegate.playbook_declaration import (
            declaration_reject_gate,
            resolve_playbook_declaration,
        )
        from agentcore.runtime.runs import build_run_plan
        from agentcore.runtime.turn_token_budget import (
            current_turn_tokens,
            is_turn_token_ceiling_hit,
            resolve_turn_token_ceiling,
            turn_token_ceiling_reject_message,
        )

        # Turn 级硬顶：禁新派（在飞不 cancel）；与 per-worker ceiling 正交。
        if is_turn_token_ceiling_hit():
            msg = turn_token_ceiling_reject_message()
            logger.info(
                "delegate.turn_token_ceiling_rejected",
                spent=current_turn_tokens(),
                ceiling=resolve_turn_token_ceiling(),
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=msg,
                contract_failure=True,
            )

        # Agent/自动化：只认结构化 ledger 后果（已记账「可运行/仅方案」禁 toolshed 等）。
        # 不扫用户原文猜意图、不因无账拒整个 delegate。须先于 playbook 声明闸传入记账。
        automation_delivery_warning: str | None = None
        automation_conf = None
        from agentcore.runtime.runs.automation_delivery import (
            automation_runnable_no_exec_soft_tip,
            is_runnable_delivery,
            resolve_delivery_confirmation,
        )
        from agentcore.tools.builtin import code_execution_enabled_for

        cid_auto = (self._conversation_id or "").strip()
        automation_conf = (
            await resolve_delivery_confirmation(cid_auto) if cid_auto else None
        )
        if automation_conf is not None and is_runnable_delivery(automation_conf):
            exec_on = code_execution_enabled_for(self._base_tool_context.backend)
            if not exec_on:
                automation_delivery_warning = automation_runnable_no_exec_soft_tip()
                logger.info(
                    "delegate.automation_delivery_soft_tip",
                    conversation_id=cid_auto or None,
                    reason="runnable_no_exec",
                    format_id=automation_conf.format_id,
                )

        # Playbook 声明闸：结构校验 + 自动化开工卡记账；建站/绿场 none 不再硬拒。
        declared_playbook, none_reason, decl_error = resolve_playbook_declaration(
            arguments,
            user_message=self._user_message or "",
            automation_delivery=automation_conf,
        )
        if decl_error:
            gate = declaration_reject_gate(decl_error)
            logger.info(
                "delegate.playbook_declaration_rejected",
                playbook_id=arguments.get("playbook_id") or arguments.get("playbook"),
                has_tasks=bool(arguments.get("tasks")),
                gate=gate,
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=decl_error,
                contract_failure=True,
            )
        logger.info(
            "delegate.playbook_declaration",
            playbook_id=declared_playbook or "none",
            none_reason=(none_reason[:120] if none_reason else ""),
        )

        # 拆·playbook 固化 (§2.1): a固化形状 instantiates the whole tasks array, then flows through
        # the SAME pipeline below as a hand-written one (纯加法). playbook XOR tasks is enforced
        # in resolve_playbook_declaration (and re-checked here as defense in depth).
        playbook = declared_playbook
        if playbook is not None:
            from agentcore.runtime.delegate.playbook_declaration import (
                PLAYBOOK_TASKS_XOR_MSG,
            )
            from agentcore.runtime.runs.playbooks import (
                collect_playbook_notes,
                expand_playbook,
            )

            if arguments.get("tasks"):
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=PLAYBOOK_TASKS_XOR_MSG,
                    # 契约自纠拒绝——勿进熔断（CEO 连试换 none/去掉 tasks 会误禁用）。
                    contract_failure=True,
                )
            # P1a 风格双闸（keyed on build_website / build_toolshed）：须有 ask_user
            # 记账的 style_id；full_auto 窄豁免 → 落默认风格进记账（DESIGN 由 design 节点写入）。
            if playbook in ("build_website", "build_toolshed"):
                from agentcore.runtime.runs.website_style import (
                    build_website_missing_style_error,
                    ensure_full_auto_default_style,
                    resolve_style_confirmation,
                )

                cid = (self._conversation_id or "").strip()
                conf = await resolve_style_confirmation(cid) if cid else None
                if conf is None:
                    if self._permission_axes.auto_executes and cid:
                        ensure_full_auto_default_style(cid)
                        logger.info(
                            "delegate.website_style_full_auto_default",
                            conversation_id=cid,
                            playbook=playbook,
                        )
                    else:
                        logger.info(
                            "delegate.website_style_rejected",
                            conversation_id=cid or None,
                            permission_axes=self._permission_axes.to_dict(),
                            playbook=playbook,
                        )
                        return ToolResult(
                            tool_call_id="",
                            success=False,
                            output="",
                            error=build_website_missing_style_error(),
                            contract_failure=True,
                        )
            # Mechanism: pass turn user line so playbooks (e.g. multi_lens synthesizer)
            # can inject proposition-fidelity anchors without relying on CEO-filled topic.
            tasks_raw, pb_errors = expand_playbook(
                playbook,
                arguments.get("playbook_args"),
                user_message=self._user_message,
                conversation_id=self._conversation_id or "",
            )
            if pb_errors:
                msg = "playbook 实例化失败：" + "；".join(pb_errors)
                logger.info("delegate.playbook_rejected", playbook=playbook, errors=pb_errors)
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )
            self._active_playbook = playbook
            playbook_notes = collect_playbook_notes(tasks_raw)
            logger.info(
                "delegate.playbook",
                playbook=playbook,
                nodes=len(tasks_raw),
                notes=len(playbook_notes),
            )
            # MLR keep 标记延后到真正开跑（team_preview CONTINUE / pre-auth 跳过），
            # 避免 STOP / 调度失败仍挡住回合收尾 orphan。
        else:
            self._active_playbook = None
            playbook_notes = []
            tasks_raw = arguments.get("tasks")
            if not isinstance(tasks_raw, list) or not tasks_raw:
                msg = "'tasks' 必须是非空数组：每个元素至少包含 role 和 task。"
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )

        # 演讲/PPT：只认结构化 format ledger 后果（已确认 pptx + 有执行 → 禁静默只交 .md/Marp）。
        # 不扫用户原文猜意图、不因无账拒整个 delegate。
        presentation_format_warning: str | None = None
        from agentcore.runtime.runs.presentation_format import (
            is_pptx_format_confirmation,
            presentation_pptx_no_exec_soft_tip,
            presentation_pptx_silent_md_error,
            resolve_format_confirmation,
            tasks_silently_downgrade_pptx_to_md,
        )
        from agentcore.tools.builtin import code_execution_enabled_for

        cid_pres = (self._conversation_id or "").strip()
        conf = await resolve_format_confirmation(cid_pres) if cid_pres else None
        if conf is not None and is_pptx_format_confirmation(conf):
            exec_on = code_execution_enabled_for(self._base_tool_context.backend)
            if exec_on and tasks_silently_downgrade_pptx_to_md(tasks_raw):
                logger.info(
                    "delegate.presentation_format_rejected",
                    conversation_id=cid_pres or None,
                    reason="pptx_silent_md",
                    format_id=conf.format_id,
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=presentation_pptx_silent_md_error(),
                    contract_failure=True,
                )
            if not exec_on:
                presentation_format_warning = presentation_pptx_no_exec_soft_tip()
                logger.info(
                    "delegate.presentation_format_soft_tip",
                    conversation_id=cid_pres or None,
                    reason="pptx_no_exec",
                    format_id=conf.format_id,
                )

        valid_tools = {s.name for s in self._tools.list_all()}
        complexity_hint = arguments.get("complexity_hint", "standard")
        self._delegate_force = bool(arguments.get("force"))
        if "complexity_hint" not in arguments and _should_auto_light_delegate(tasks_raw):
            complexity_hint = "light"
            # info 级：档位归责的关键决策事件，debug 级曾导致线上排查只能靠 demo_tape 反推。
            logger.info("delegate.complexity_hint_inferred", hint="light")
        elif complexity_hint == "light" and (
            _has_wave_boundary_features(tasks_raw) or _blocks_explicit_light(tasks_raw)
        ):
            # 显式 light 与 DAG/波边界或成篇长文并存时忽略 light：
            # 前者避免关掉 on_boundary；后者保留成篇调研的 standard 编排。
            # requires_files / form=files / artifacts  alone 不再挡 light（修码快修）。
            reason = (
                "wave_boundary_features"
                if _has_wave_boundary_features(tasks_raw)
                else "long_form_deliverable"
            )
            complexity_hint = "standard"
            logger.info(
                "delegate.complexity_hint_ignored",
                reason=reason,
            )

        if self._depth >= 1:
            from agentcore.runtime.runs.constants import MAX_WORKER_SUBDELEGATIONS

            new_nodes = len(tasks_raw)
            if self._sub_workers_spawned + new_nodes > MAX_WORKER_SUBDELEGATIONS:
                msg = (
                    f"子团队扇出已达上限（已派出 {self._sub_workers_spawned} 个 sub-worker，"
                    f"本次 {new_nodes} 个，上限 {MAX_WORKER_SUBDELEGATIONS}）——请合并任务或分批。"
                )
                logger.info(
                    "delegate.sub_fanout_rejected",
                    spawned=self._sub_workers_spawned,
                    requested=new_nodes,
                    cap=MAX_WORKER_SUBDELEGATIONS,
                )
                return ToolResult(tool_call_id="", success=False, output="", error=msg)
        # 消费者漏边：task 写明吃同批队友产出但 depends_on 为空 → 软告警一次，不拒收入图。
        # playbook 展开后的 tasks 也过闸；有边则无告警。引擎不猜边改图。
        from agentcore.runtime.delegate.consumer_deps import (
            check_consumer_missing_depends,
        )

        consumer_deps_warn = check_consumer_missing_depends(tasks_raw)
        if consumer_deps_warn:
            logger.info(
                "delegate.consumer_deps_soft_warn",
                task_count=len(tasks_raw),
                hint=consumer_deps_warn[:200],
            )

        # 跨回合同图追加：须在 build_run_plan 之前加载宿主计划，以便 depends_on 解析
        # 同 execution 已有图节点（对齐 build_added_nodes / replan add）。
        append_raw = arguments.get("append_to_execution_id")
        append_to = (
            append_raw.strip()
            if isinstance(append_raw, str) and append_raw.strip()
            else None
        )
        host_message_id: str | None = None
        append_seed: dict | None = None
        host_plan_for_append = None
        if append_to and self._depth > 0:
            msg = (
                "append_to_execution_id 仅根协调者可用：嵌套 lead 不能跨回合追加协作图。"
                "请去掉该参数，直接在本子团队内委派。"
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=msg,
                contract_failure=True,
            )
        if append_to and append_to.lower() == "latest":
            from agentcore.runtime.delegate.graph_append import (
                resolve_latest_appendable_execution,
            )

            resolved = await resolve_latest_appendable_execution(
                conversation_id=self._conversation_id or "",
                exclude_message_id=self._message_id,
            )
            if not resolved:
                from agentcore.runtime.coordination.session import active_coordination

                active = active_coordination(self._base_tool_context.execution_id)
                if active is not None and active.active:
                    msg = (
                        "追加解析失败：本回合已有活跃协作图。同回合追加无需 "
                        'append_to_execution_id="latest"——直接再调 delegate（不传该参数）'
                        "即会自动并入当前协作图（同一 execution_id / 同一协调会话）。"
                        "向用户汇报时说「已往当前团队追加」，不要说成新组建团队。"
                    )
                else:
                    msg = (
                        '追加解析失败：本对话没有可追加的既有协作图（append_to_execution_id="latest" '
                        "未命中）。请改为不传 append_to_execution_id 新建团队执行，"
                        "并如实告知用户本次是新组建团队、未在旧图上追加。"
                    )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )
            append_to = resolved
        if append_to:
            from agentcore.runtime.delegate.graph_append import (
                load_host_plan_and_completed,
                resolve_host_message_id,
            )

            host_message_id = await resolve_host_message_id(
                conversation_id=self._conversation_id or "",
                execution_id=append_to,
            )
            if not host_message_id:
                msg = (
                    f"找不到 execution_id=`{append_to}` 对应的既有协作图。"
                    "请确认 id 来自本对话上一张团队执行的 run_plan，或改为不传 "
                    "append_to_execution_id 以新建图。"
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )
            host_plan_for_append, append_seed = await load_host_plan_and_completed(
                host_message_id
            )
            if host_plan_for_append is None:
                msg = (
                    f"既有协作图 `{append_to}` 缺少可合并的计划快照（plan_snapshot），"
                    "无法跨回合追加。请新建团队执行。"
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )

        self._calls += 1
        # 冻结本次委派调用的序号：同回合并发的多个 delegate 调用共享 self._calls，若在完成侧
        # 惰性读取会把每个批次的 completed / synthesis 日志都错记到「最后自增到的序号」。这里
        # 立刻定格，透传给 drive → format_for_ceo 用于完成侧日志。
        call_idx = self._calls
        prefix = f"del_{new_id()}"
        plan, errors = build_run_plan(
            tasks_raw,
            valid_tools=valid_tools,
            id_prefix=prefix,
            parent_run_id=self._captain_run_id,
            depth=self._depth + 1,
            complexity_hint=complexity_hint,
            existing_plan=host_plan_for_append,
        )
        if errors:
            msg = "委派任务无效：" + "；".join(errors)
            logger.info("delegate.rejected", errors=errors)
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=msg,
                # 参数/依赖校验打回是零成本可自纠——勿进熔断。
                contract_failure=True,
            )
        # 部分并行：检查点波后线性链可按 parallelism 放宽（默认 conservative 不改图）。
        from agentcore.runtime.delegate.parallelism import (
            resolve_parallelism,
            widen_post_checkpoint_deps,
        )

        parallelism = resolve_parallelism(
            arguments.get("parallelism"),
            complexity_hint=complexity_hint if isinstance(complexity_hint, str) else "standard",
            node_count=len(plan.nodes),
            has_checkpoint=any(n.checkpoint_after for n in plan.nodes),
        )
        widen_post_checkpoint_deps(plan, parallelism)
        from agentcore.runtime.delegate.continuation import apply_continuation_tool_merges
        from agentcore.runtime.runs.research_quality import (
            batch_includes_review_role,
            plan_signals_long_form_audit,
        )

        # 乙续派：新 task.tools 只增不减 merge 进现场，供后续能力闸与 continue_run 共用。
        await apply_continuation_tool_merges(plan, self)

        batch_includes_review = (
            playbook == "research_report" or batch_includes_review_role(tasks_raw)
        )
        batch_audit_hard = (
            playbook == "research_report"
            or plan_signals_long_form_audit(plan.nodes)
        )
        from agentcore.runtime.delegate.completion import (
            default_repair_code_criteria,
            execution_capability_warning,
            format_resolved_acceptance_echo,
            hoist_task_completion_criteria,
            resolve_completion_with_source,
            validate_cold_start_explore_deliverables,
            validate_code_verified_worker_tools,
            validate_completion_against_forms,
            validate_criteria_kind_fit,
            validate_execution_capability,
            validate_repair_how_fixed,
        )

        # 顶层缺失时，容错提升 task 内误放的 completion_criteria（不改 schema 契约）。
        completion_criteria, hoist_err = hoist_task_completion_criteria(
            arguments.get("completion_criteria"),
            tasks_raw,
        )
        if hoist_err:
            logger.info("delegate.rejected", errors=[hoist_err])
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=hoist_err,
                contract_failure=True,
            )

        # E1/E2：repair_code 强制 code_verified（不可降到 files_written），写入 how-fixed。
        playbook_name_early = (
            playbook.strip() if isinstance(playbook, str) and playbook.strip() else None
        )
        if playbook_name_early == "repair_code":
            completion_criteria = default_repair_code_criteria(
                arguments.get("playbook_args")
            )
            # Prefer richer how-fixed already on an explicit top-level object.
            from agentcore.runtime.delegate.completion import (
                how_fixed_text,
                parse_completion_criteria,
            )

            prior = parse_completion_criteria(arguments.get("completion_criteria"))
            prior_how = how_fixed_text(prior)
            if prior_how and not completion_criteria.get("verify_command"):
                completion_criteria = {
                    **completion_criteria,
                    "verify_command": prior_how,
                }
            logger.info(
                "delegate.repair_code_criteria_forced",
                criteria="code_verified",
            )

        how_fixed_err = validate_repair_how_fixed(
            completion_criteria,
            playbook=playbook_name_early,
            playbook_args=arguments.get("playbook_args"),
            complexity_hint=(
                complexity_hint if isinstance(complexity_hint, str) else None
            ),
        )
        if how_fixed_err:
            logger.info(
                "delegate.rejected",
                errors=[how_fixed_err],
                reason="repair_how_fixed",
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=how_fixed_err,
                contract_failure=True,
            )

        # 冷启动探索未完成：默认探路须 prose；禁止 form=files / artifacts（画像由 CEO
        # update_project_profile 写）。显式 files_written 为进阶覆盖。旗标在 assemble
        # 置位、画像写入成功后清除。
        explore_pending = bool(self._base_tool_context.cold_start_explore_pending)
        if explore_pending:
            explore_form_err = validate_cold_start_explore_deliverables(
                plan,
                explicit_criteria=completion_criteria,
            )
            if explore_form_err:
                logger.info(
                    "delegate.cold_start_explore_rejected",
                    reason="files_or_artifacts",
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=explore_form_err,
                    contract_failure=True,
                )

        form_conflict = validate_completion_against_forms(
            completion_criteria,
            plan,
        )
        if form_conflict:
            logger.info("delegate.rejected", errors=[form_conflict])
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=form_conflict,
                contract_failure=True,
            )
        kind_fit_err = validate_criteria_kind_fit(completion_criteria, plan)
        if kind_fit_err:
            logger.info(
                "delegate.rejected",
                errors=[kind_fit_err],
                reason="criteria_kind_fit",
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=kind_fit_err,
                contract_failure=True,
            )
        # 委派前能力闸（能力闸门与交付诚实性）：resolved code_verified / runtime_ready
        # （显式 / 结构化，与收尾验收同一解析；文案不再绑定）撞上「无执行环境 /
        # 无本机 terminal」硬拒；剩余启发命中（运行/二进制文案）只软警告、不拦截。
        # 冷启动探索未完成时抑制 form/artifacts→files_written 推断（仅显式生效）。
        resolved_acceptance = resolve_completion_with_source(
            completion_criteria,
            plan,
            suppress_structured_files_written=explore_pending,
        )
        acceptance_echo = format_resolved_acceptance_echo(resolved_acceptance)
        capability_error = validate_execution_capability(
            completion_criteria,
            plan,
            self._base_tool_context.backend,
        )
        if capability_error:
            kind = (
                resolved_acceptance.criteria.kind
                if resolved_acceptance.criteria is not None
                else "unknown"
            )
            logger.info(
                "delegate.capability_rejected",
                criteria=kind,
                explicit=completion_criteria is not None,
                backend_location=getattr(self._base_tool_context.backend, "location", None),
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=capability_error,
                contract_failure=True,
            )
        # 与环境能力闸正交：code_verified 须批内至少一人持执行类 tools。
        tools_surface_error = validate_code_verified_worker_tools(
            completion_criteria,
            plan,
        )
        if tools_surface_error:
            kind = (
                resolved_acceptance.criteria.kind
                if resolved_acceptance.criteria is not None
                else "unknown"
            )
            logger.info(
                "delegate.capability_rejected",
                criteria=kind,
                reason="no_execution_tools",
                explicit=completion_criteria is not None,
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=tools_surface_error,
                contract_failure=True,
            )
        capability_warning = execution_capability_warning(
            completion_criteria,
            plan,
            self._base_tool_context.backend,
        )
        if capability_warning:
            logger.info(
                "delegate.capability_warning",
                backend_location=getattr(self._base_tool_context.backend, "location", None),
            )
        # execution_id when already known at kickoff (append host / same-turn graph)
        # so analysts can join acceptance_resolved ↔ completion_criteria_unmet.
        kickoff_execution_id = append_to or self._base_tool_context.execution_id
        logger.info(
            "delegate.acceptance_resolved",
            criteria=(
                resolved_acceptance.criteria.kind if resolved_acceptance.criteria else None
            ),
            source=resolved_acceptance.source,
            **(
                {"execution_id": kickoff_execution_id}
                if kickoff_execution_id
                else {}
            ),
        )
        if self._depth >= 1:
            self._sub_workers_spawned += len(plan.nodes)

        from agentcore.runtime.delegate.seed_notes import (
            parse_seed_notes,
            parse_team_brief,
            resolve_coordination,
        )

        seed_notes, seed_err = parse_seed_notes(arguments.get("seed_notes"))
        if seed_err:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=seed_err,
                contract_failure=True,
            )
        brief_raw = arguments.get("team_brief")
        if brief_raw is not None:
            brief, brief_err = parse_team_brief(brief_raw)
            if brief_err:
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=brief_err,
                    contract_failure=True,
                )
            self._team_brief = brief

        playbook_name = playbook.strip() if isinstance(playbook, str) and playbook.strip() else None
        coordination = resolve_coordination(
            raw=arguments.get("coordination") if "coordination" in arguments else None,
            complexity_hint=complexity_hint,
            seed_notes=seed_notes,
            team_brief=self._team_brief,
            playbook=playbook_name,
        )
        self._coordination = coordination
        self._seed_notes = seed_notes

        # 跨回合同图追加：宿主计划已在 build 前加载；此处合并新节点并绑定生长 divert。
        added_nodes_for_anchor: list = list(plan.nodes)
        graph_redirect = None
        graph_redirect_token = None

        if append_to:
            from agentcore.runtime.runs.plan import RunPlanError

            old_plan = host_plan_for_append
            assert old_plan is not None  # loaded before build_run_plan
            added_nodes_for_anchor = []
            for node in plan.nodes:
                try:
                    old_plan.add(node)
                    added_nodes_for_anchor.append(node)
                except RunPlanError as exc:
                    logger.warning(
                        "delegate.graph_append_skip_node",
                        execution_id=append_to,
                        run_id=node.run_id,
                        error=str(exc),
                    )
            if not added_nodes_for_anchor:
                msg = "跨回合追加未并入任何新节点（可能与旧图 run_id 冲突）。请调整 tasks。"
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    contract_failure=True,
                )
            plan = old_plan
            # Workers / coordination registry must see the host execution_id before
            # admission / emit (reject must not leave graph_append / run_plan).
            self._base_tool_context.execution_id = append_to
            from agentcore.runtime.coordination.session import current_execution_id

            # Turn teardown clears via current_execution_id — keep it on the host
            # so the append coordination session is not orphaned under a fresh id.
            current_execution_id.set(append_to)

        execution_id = (
            append_to
            if append_to
            else (self._base_tool_context.execution_id or new_id())
        )
        finalize_flag = bool(arguments.get("finalize"))
        from agentcore.runtime.coordination.host import (
            admit_before_run_plan_emit,
            should_defer_run_plan_emit_to_merge,
        )

        # 准入→提交→执行：sibling / 追加重叠 / 同构闸在 durable run_plan 之前。
        admitted_reject = admit_before_run_plan_emit(
            self,
            plan,
            execution_id=execution_id,
            finalize=finalize_flag,
            call_idx=call_idx,
        )
        if admitted_reject is not None:
            return admitted_reject

        if append_to:
            from agentcore.core.log_context import get_log_value
            from agentcore.runtime.delegate.graph_append import (
                GraphAppendRedirect,
                bind_redirect,
                open_host_journal_writer,
            )
            from agentcore.runtime.events import graph_append as graph_append_event

            host_writer = await open_host_journal_writer(
                host_message_id=host_message_id,
                conversation_id=self._conversation_id or "",
                trace_id=get_log_value("trace_id"),
            )
            graph_redirect = GraphAppendRedirect(
                execution_id=append_to,
                host_message_id=host_message_id,
                append_message_id=self._message_id or "",
                host_writer=host_writer,
            )
            graph_redirect_token = bind_redirect(graph_redirect)
            roles_anchor = [
                n.role or n.agent_name or n.run_id for n in added_nodes_for_anchor
            ]
            self._sink.emit(
                graph_append_event(
                    execution_id=append_to,
                    host_message_id=host_message_id,
                    append_message_id=self._message_id or "",
                    added_count=len(added_nodes_for_anchor),
                    roles=roles_anchor,
                    added_run_ids=[n.run_id for n in added_nodes_for_anchor],
                    # 批 A1：跨回合追加暂归宿主既有幕（act-1）；开新幕是后续批次。
                    act_id="act-1",
                    act_kind="multi_agent",
                )
            )
            logger.info(
                "delegate.graph_append",
                execution_id=append_to,
                host_message_id=host_message_id,
                added=len(added_nodes_for_anchor),
                total=len(plan.nodes),
            )

        record_plan_snapshot(plan)

        from agentcore.runtime.audit.hooks import on_delegate_plan

        on_delegate_plan(
            execution_id=execution_id,
            plan=plan,
            captain_run_id=self._captain_run_id,
        )
        # 同回合合入活跃协调时由 merge 在准入后发出成长后的 run_plan（提交点）。
        if not should_defer_run_plan_emit_to_merge(
            self, execution_id=execution_id, finalize=finalize_flag
        ):
            self._sink.emit(
                plan_event(
                    self,
                    execution_id,
                    plan,
                    host_message_id=host_message_id,
                )
            )
        # 决策可观测: who + what got delegated (the「派了谁、干什么」input basis), not just a
        # node count. `parallel` = first-wave width (nodes with no deps → run concurrently), so
        # 扇出 vs 串行 is visible offline. `agents` is capped to keep the line bounded on a big fan-out.
        logger.info(
            "delegate.started",
            nodes=len(plan.nodes),
            call=call_idx,
            parallel=sum(1 for n in plan.nodes if not n.depends_on),
            complexity_hint=complexity_hint,
            coordination=coordination,
            append_to=append_to,
            plan=[
                {"id": n.run_id, "role": n.role, "depends_on": n.depends_on}
                for n in plan.nodes
            ],
            waves=[
                [n.run_id for n in wave]
                for wave in plan.waves()
            ],
            agents=[
                f"{n.role or n.agent_name or n.run_id}: {clip_preview(n.task, 80)}"
                for n in plan.nodes[:_DELEGATE_LOG_AGENTS_CAP]
            ],
        )
        # Plan-only eval: real plan path done (build + validate + run_plan). Skip drive
        # so workers / coordination never start; HANDOFF ends the CEO loop immediately.
        from agentcore.runtime.plan_only import is_plan_only

        if is_plan_only():
            summary = (
                f"[plan-only] 已记录计划（{len(plan.nodes)} 节点），跳过执行。"
                f"\n\n{acceptance_echo}"
            )
            if playbook_notes:
                summary = summary + "\n\n" + "\n\n".join(playbook_notes)
            logger.info("delegate.plan_only", nodes=len(plan.nodes), call=call_idx)
            from agentcore.runtime.delegate.batch_shape import annotate_batch_meta

            if graph_redirect_token is not None:
                from agentcore.runtime.delegate.graph_append import reset_redirect

                reset_redirect(graph_redirect_token)
            return annotate_batch_meta(
                ToolResult(
                    tool_call_id="",
                    success=True,
                    output=summary,
                    effect=ToolEffect.HANDOFF,
                    final_text=summary,
                ),
                node_count=len(added_nodes_for_anchor),
                has_deps=any(n.depends_on for n in added_nodes_for_anchor),
                playbook=playbook_name,
                audit_hard=batch_audit_hard,
                includes_review=batch_includes_review,
            )
        # retry-failed: if a retry seed is set (from retry_failed_chat), use it
        # so workers that already succeeded are skipped by the WaveScheduler.
        from agentcore.runtime.retry import retry_failed_targets as _retry_failed_targets_var
        from agentcore.runtime.retry import retry_seed as _retry_seed_var

        _retry = _retry_seed_var.get(None)
        _failed_targets = _retry_failed_targets_var.get(None)
        # Only use the seed once (for the first delegate call); clear it so a
        # second delegate in the same turn doesn't inherit stale seeds.
        if _retry is not None:
            _retry_seed_var.set(None)
        if _failed_targets is not None:
            _retry_failed_targets_var.set(None)
            from agentcore.runtime.audit.hooks import on_run_retry

            for target in _failed_targets:
                run_id = str(target.get("run_id") or "")
                if not run_id:
                    continue
                on_run_retry(
                    run_id=run_id,
                    attempt=1,
                    source="retry_failed",
                    error=target.get("error"),
                )

        # retry-failed seed 是上一回合铸的 run_id（del_<旧uuid>_<raw>），本回合新计划用新前缀，
        # 不重映射则 WaveScheduler 精确匹配永不命中、已成功 worker 全量重跑。这里按 raw 尾缀把
        # seed 重映射到新计划的同 raw 节点（数字位置号不映射），并如实补发命中节点的完成态——
        # 命中节点被调度器跳过不发 run_*，而旧回合 journal 已删，否则前端图会永远卡 pending。
        # 仅在真会用到 retry seed 时执行（append 走宿主 seed，二者互斥）。
        retry_seed_remapped: dict[str, RunState] | None = None
        if _retry and not append_to:
            from agentcore.runtime.delegate.retry_remap import (
                remap_retry_seed,
                replay_seeded_completed,
            )

            remap = remap_retry_seed(_retry, plan, prefix=prefix)
            retry_seed_remapped = remap.seed or None
            if retry_seed_remapped:
                replay_seeded_completed(self._sink, plan, retry_seed_remapped)

        from agentcore.runtime.delegate.batch_shape import annotate_batch_meta

        # Cross-turn append seeds from host journal; retry-failed only applies to fresh graphs.
        seed_completed = append_seed if append_to else retry_seed_remapped

        try:
            result = await drive(
                self,
                plan,
                execution_id=execution_id,
                seed_completed=seed_completed,
                finalize=bool(arguments.get("finalize")),
                seed_notes=seed_notes,
                complexity_hint=complexity_hint,
                coordination=coordination,
                call_idx=call_idx,
                completion_criteria=completion_criteria,
                # Omit → True（默认协调）；显式 false → 经典阻塞。勿用 bool(get())，
                # 否则缺省会落成 False，与 schema default 不一致。
                coordinate=(
                    bool(arguments["coordinate"])
                    if "coordinate" in arguments
                    else True
                ),
            )
        finally:
            if graph_redirect_token is not None:
                from agentcore.runtime.delegate.graph_append import reset_redirect

                reset_redirect(graph_redirect_token)
            if graph_redirect is not None:
                with contextlib.suppress(Exception):
                    await graph_redirect.host_writer.flush()

        # 验收回显（提案 B1 补偿②）+ 软警告：挂在委派结果尾部，CEO 当轮可见可改。
        # SUSPEND（开工卡挂起）无 output 可挂，跳过——不改挂起语义。
        if result.output and result.effect is ToolEffect.CONTINUE:
            tails: list[str] = [acceptance_echo]
            if capability_warning:
                tails.append(capability_warning)
            if presentation_format_warning:
                tails.append(presentation_format_warning)
            if automation_delivery_warning:
                tails.append(automation_delivery_warning)
            if playbook_notes:
                tails.extend(playbook_notes)
            if append_to:
                # 口径与产品呈现一致：UI 在追加回合只显示「已往上方协作图追加 N 名成员」
                # 锚点，生长发生在上方旧图。回显 execution_id 供后续追加显式指定。
                tails.append(
                    f"【跨回合同图追加】已往上方协作图追加 "
                    f"{len(added_nodes_for_anchor)} 名成员（execution_id=`{append_to}`）；"
                    "生长呈现在上方旧图，本回合只显示追加锚点；队员正在后台报到，"
                    "完成态靠图事件异步呈现，勿宣称已全员就位；图完成态由该 execution 自身收口，"
                    "不随本回合 message_end 结束。向用户汇报请用「已追加、正在报到」口径；"
                    "用户要立等结果时用 finalize 阻塞收口。不要说成新组建团队。"
                )
            elif self._depth == 0:
                # 回显本图 execution_id（跨回合追加的显式指定通道；latest 解析为主路径）。
                # 仅根协调者——嵌套 lead 不能跨回合追加，回显只会误导。
                tails.append(
                    f"【协作图】本次团队执行 execution_id=`{execution_id}`"
                    '（跨回合往这张图追加队员：delegate 传 append_to_execution_id="latest" '
                    "或此精确 id）。"
                )
            result.output = f"{result.output}\n\n" + "\n\n".join(tails)
        return annotate_batch_meta(
            result,
            node_count=len(added_nodes_for_anchor),
            has_deps=any(n.depends_on for n in added_nodes_for_anchor),
            playbook=playbook if isinstance(playbook, str) else None,
            audit_hard=batch_audit_hard,
            includes_review=batch_includes_review,
        )

    async def _drive(
        self,
        plan: RunPlan,
        *,
        execution_id: str,
        seed_completed: dict[str, RunState] | None,
        finalize: bool,
        seed_notes: list[dict[str, str]] | None = None,
        complexity_hint: str = "standard",
    ) -> ToolResult:
        return await drive(
            self,
            plan,
            execution_id=execution_id,
            seed_completed=seed_completed,
            finalize=finalize,
            seed_notes=seed_notes or [],
            complexity_hint=complexity_hint,
            coordination=self._coordination,
        )

    async def resume_plan(
        self,
        plan: RunPlan,
        seed_completed: dict[str, RunState],
        *,
        decision: CheckpointDecision,
        note: str,
        checkpoint_run_ids: set[str],
        execution_id: str,
        coordinate: bool = False,
        apply_kickoff_grant: bool = False,
        coordination: str | None = None,
        team_brief: str | None = None,
        seed_notes: list[dict[str, str]] | None = None,
        ceo_review: dict | None = None,
    ) -> ToolResult:
        # 耐久恢复的批次协作参数回灌：挂起帧带回 coordination / team_brief / seed_notes
        # （挂起点在 setup_note_wall 之前，这批参数只活在工具实例上；恢复走全新实例，
        # 不回灌则 wall 批降级 none → worker 被剥便签三件套）。缺省 None = 在进程内
        # 热续跑，沿用实例现值。
        if coordination in ("wall", "none"):
            self._coordination = coordination
        if team_brief:
            self._team_brief = team_brief
        if seed_notes:
            self._seed_notes = list(seed_notes)
        if decision is CheckpointDecision.STOP:
            return await finalize_stopped(self, plan, seed_completed)

        # Steer: ADJUST always; kickoff CONTINUE+note ≡ former adjust (嘱咐注入未跑队员).
        # plan_review CONTINUE+note does not steer (apply_kickoff_grant=False; UI still has 调整).
        if note.strip() and (
            decision is CheckpointDecision.ADJUST
            or (decision is CheckpointDecision.CONTINUE and apply_kickoff_grant)
        ):
            apply_steer(plan, seed_completed, checkpoint_run_ids, note.strip())
        # plan_review CONTINUE：读帧上 llm ceo_review → 压缩 REPLACE 注入 gate_notes。
        # 开工卡路径 (apply_kickoff_grant) 不走；deterministic / 无 review → 不下发。
        if (
            decision is CheckpointDecision.CONTINUE
            and not apply_kickoff_grant
            and ceo_review is not None
        ):
            from agentcore.runtime.delegate.steer import (
                apply_gate_notes,
                compress_ceo_review_for_gate,
            )

            gate_body = compress_ceo_review_for_gate(ceo_review)
            if gate_body:
                apply_gate_notes(plan, seed_completed, checkpoint_run_ids, gate_body)
        # Kickoff (开工卡): continue / adjust → grant; per_call → no grant.
        # PER_CALL kept for historical / API clients; UI no longer offers the entry.
        # apply_kickoff_grant is True only when resuming a team_preview suspension.
        if apply_kickoff_grant and self._approval_gate is not None:
            if decision is CheckpointDecision.PER_CALL:
                pass  # historical: start with per-call approval
            elif decision in (CheckpointDecision.CONTINUE, CheckpointDecision.ADJUST):
                self._approval_gate.grant_delegation(execution_id)
            elif decision is CheckpointDecision.TIMEOUT:
                # Historical timeout→auto-continue: grant (same as continue).
                self._approval_gate.grant_delegation(execution_id)
        # Resume never re-runs the original execute() path, so re-emit run_plan here:
        # the frontend drops the pause bubble on message_start and must re-bind the DAG
        # under the new streaming assistant before worker frames arrive.
        self._sink.emit(plan_event(self, execution_id, plan))
        logger.info(
            "delegate.resume_plan",
            execution_id=execution_id,
            decision=decision.value,
            nodes=len(plan.nodes),
        )
        # plan_review：仅经典路径 durable 挂起（协调态波边界只发 BOUNDARY_YIELD），续跑保持
        # coordinate=False。team_preview：挂在 coordinate fork **之前**，开做后续跑须默认
        # 臂后台（coordinate=True）；显式经典由调用方传 coordinate=False。
        from agentcore.runtime.delegate.batch_shape import annotate_batch_meta

        result = await drive(
            self,
            plan,
            execution_id=execution_id,
            seed_completed=seed_completed,
            finalize=False,
            # 开工卡恢复补种 CEO 预贴便签（挂起时尚未上墙）；plan_review 恢复不带（已上墙）。
            seed_notes=list(seed_notes or []),
            coordination=self._coordination,
            coordinate=coordinate,
        )
        return annotate_batch_meta(
            result,
            node_count=len(plan.nodes),
            has_deps=any(n.depends_on for n in plan.nodes),
        )

    async def replan(self, arguments: dict[str, Any]) -> ToolResult:
        from agentcore.runtime.runs import BoundaryReason

        sup = self._supervised
        if sup is None:
            msg = (
                "当前没有待续跑的受监督计划。replan 仅在 delegate 让出边界（输出『计划已"
                "让出』）或部分队员失败/跳过后可用；要发起新任务请用 delegate。"
            )
            return ToolResult(tool_call_id="", success=False, output="", error=msg)

        binds = arguments.get("binds") or []
        steers = arguments.get("steers") or []
        adds = arguments.get("add") or []
        stop = bool(arguments.get("stop"))
        if (
            not isinstance(binds, list)
            or not isinstance(steers, list)
            or not isinstance(adds, list)
        ):
            msg = "replan 的 binds / steers / add 必须是数组。"
            return ToolResult(tool_call_id="", success=False, output="", error=msg)
        if sup.reason is BoundaryReason.BIND and not stop and not binds:
            msg = (
                "replan 需要 binds 定稿至少一个『待定稿』步骤，或设 stop=true 收口"
                "（仅 steers / add 不能让待定稿步骤运行起来）。"
            )
            return ToolResult(tool_call_id="", success=False, output="", error=msg)

        # Snapshot the pre-add node ids so we can tell which nodes apply_replan appended
        # (it mutates the plan in place) — those drive the re-emitted run_plan below.
        ids_before = {n.run_id for n in sup.plan.nodes}
        errors = apply_replan(self, sup.plan, sup.completed, binds, steers, adds)
        if errors:
            msg = "replan 无效：" + "；".join(errors)
            logger.info("replan.rejected", errors=errors)
            return ToolResult(tool_call_id="", success=False, output="", error=msg)

        self._supervised = None
        record_plan_snapshot(sup.plan)
        added_nodes = [n for n in sup.plan.nodes if n.run_id not in ids_before]
        # 波边界追加节点 (设计 §7.1): re-emit run_plan so the grown DAG's new nodes merge onto
        # the live graph (same execution_id → the frontend folds merge, never reset, exactly
        # like a second delegate batch). Journaled, so the appended nodes replay on reload;
        # without this their run_started/run_completed would target unknown ids and be dropped.
        if added_nodes:
            self._sink.emit(plan_event(self, sup.execution_id, sup.plan))
        # 「计划已调整」轻痕迹 (设计 §7.2): surface the autonomous re-bind / re-steer onto the
        # affected graph nodes (bind=据上游证据定稿待绑定步骤; steer=偏离后操舵未跑步骤). A node
        # both bound AND steered reads as the bigger event (bind). Emitted only when something
        # changed — a no-op SCOPE resume (replan() 续跑) sends nothing. Appended nodes are NEW
        # (not revised), so they ride the run_plan merge above, not this trace.
        revised: dict[str, str] = {}
        for b in binds:
            rid = str(b.get("run_id") or "").strip() if isinstance(b, dict) else ""
            if rid:
                revised[rid] = "bind"
        for s in steers:
            rid = str(s.get("run_id") or "").strip() if isinstance(s, dict) else ""
            if rid and rid not in revised:
                revised[rid] = "steer"
        if revised:
            self._sink.emit(
                plan_revised(
                    execution_id=sup.execution_id,
                    revisions=[{"run_id": rid, "kind": kind} for rid, kind in revised.items()],
                )
            )
        logger.info(
            "replan.applied",
            binds=len(binds),
            steers=len(steers),
            adds=len(added_nodes),
            stop=stop,
        )
        from agentcore.runtime.audit.hooks import on_replan

        on_replan(
            execution_id=sup.execution_id,
            binds=binds,
            steers=steers,
            adds=len(added_nodes),
            stop=stop,
        )
        if stop:
            return await finalize_stopped(self, sup.plan, sup.completed)
        return await drive(
            self,
            sup.plan,
            execution_id=sup.execution_id,
            seed_completed=sup.completed,
            finalize=sup.finalize,
            coordination=self._coordination,
            coordinate=False,
        )

    async def dispose_open_supervised(self) -> ToolResult | None:
        """Turn-end disposition of a plan the CEO yielded at a boundary but never resumed
        (受监督的波循环 P5「Edge」: turn 末仍开着的 supervised run).

        The yield path returns the boundary brief WITHOUT folding the已完成 workers' usage /
        ledger / citations — those fold on the resume's terminal drive. If the captain loop
        ends first (the CEO answered without a ``replan``, hit MAX_ROUNDS, errored upstream…),
        that spend would be stranded (unbilled, sources unshown). Treat it as an implicit
        ``stop``: fold the completed work in and materialise the un-run tail SKIPPED — the
        exact ``replan(stop=true)`` path — then release the dangling state. No-op when nothing
        is paused. The host calls this once at turn end; the returned ToolResult is unused (the
        CEO already moved on), it exists only to reuse the stop path verbatim.
        """
        sup = self._supervised
        if sup is None:
            return None
        self._supervised = None
        logger.info(
            "delegate.supervised_disposed",
            reason=sup.reason.value,
            completed=len(sup.completed),
            pending=sum(1 for n in sup.plan.nodes if n.run_id not in sup.completed),
        )
        return await finalize_stopped(self, sup.plan, sup.completed)

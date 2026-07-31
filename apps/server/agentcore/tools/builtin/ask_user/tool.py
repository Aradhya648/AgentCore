"""AskUserTool: CEO asking primitive (blocking suspend + non-blocking surface)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolApproval, ToolCategory, ToolEffect, new_id
from agentcore.runtime.events import (
    EventSink,
    checkpoint_required,
    question_posted,
)
from agentcore.tools.builtin.ask_user.card import (
    CARD_KINDS,
    CARD_RETRY_HINT,
    card_max_options,
    card_overrides_intent,
    parse_card,
    validate_card_shape,
)
from agentcore.tools.builtin.ask_user.intent import resolve_ask_checkpoint_intent
from agentcore.tools.builtin.ask_user.schema import (
    ListArgError,
    normalize_assumptions,
    normalize_format_options,
    normalize_questions,
    normalize_style_options,
)
from agentcore.tools.builtin.ask_user.suspend import persist_suspension
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_CEO_ONLY,
    CeoWire,
    ToolRegistration,
    ToolSurface,
)

if TYPE_CHECKING:
    from agentcore.runtime.suspension import SuspensionDeleter, SuspensionSaver

logger = get_logger(__name__)


@dataclass
class AskUserTool:
    """The CEO's asking primitive: surface a card, suspend, resume on the answer.

    Constructed per turn where the sink is available (mirrors ``ApprovalGate`` /
    ``DelegateTool``): ``sink`` carries the prompt + resolution to the client,
    ``timeout_seconds`` is the ops-configured wait bound (default unlimited / D2 —
    ``None`` at settings maps to a large sentinel).

    结构化挂起 2b + 挂起即收口 (②) / D11: when ``message_id`` + the suspension closures
    are wired (live CEO path), the pause is persisted to ``paused_turns`` and the turn
    ends in place (``ToolEffect.SUSPEND``); resume is the single cold path
    ``POST .../resume``. The frame needs the turn-level constants (``captain_run_id`` /
    ``base_system_prompt`` / ``user_message``) to re-wire the CEO toolset on resume.
    If the durable frame cannot be saved ⇒ **explicit failure** (no in-memory timed
    wait, or auto-continue on timeout — the narrow兜底 was deleted).
    """

    registration = ToolRegistration(
        surface=ToolSurface.CEO_ORCHESTRATION,
        audience=AUDIENCE_CEO_ONLY,
        ceo_wire=CeoWire.CHECKPOINT,
    )

    sink: EventSink
    conversation_id: str
    timeout_seconds: float
    captain_run_id: str | None = None
    base_system_prompt: str = ""
    user_message: str = ""
    # Prior conversation turns (same shape as DelegateTool._history); captured on
    # suspend for resume parity. Kickoff skip is journal checkpoint_resolved only.
    history: list[dict[str, Any]] | None = None
    message_id: str | None = None
    suspension_saver: SuspensionSaver | None = None
    suspension_deleter: SuspensionDeleter | None = None
    # The cloud project (= workspace folder) scope, carried so a durable ask_user pause
    # captures it into the frame — the resumed toolset re-wires consult_memory to the same
    # project (Agent记忆与知识系统 §二). ``None`` for 裸聊 / local. Capture-only (unused live).
    folder_id: str | None = None
    # Caller-supplied memory gate, captured so resume re-wires consult_memory as this
    # turn did (False ⇒ stays off). Capture-only; defaults True (product always-on).
    memory_enabled: bool = True
    # Caller-supplied conversation-log access gate, captured for resume wire parity.
    conversation_history_access: bool = True
    # Advertise desktop-only ask_user option actions (open_local_project /
    # bind_local_folder / grant_readonly_folder / grant_organize_folder) when the
    # desktop client can fulfil them.
    advertise_bind_local_folder: bool = False

    @property
    def schema(self) -> ToolSchema:
        option_properties: dict[str, Any] = {
            "label": {
                "type": "string",
                "description": "选项文字（即用户选它时回传的答案）。",
            },
            "detail": {
                "type": "string",
                "description": (
                    "可选：这个选项的一行权衡 / 代价，展示在选项下方，帮用户看懂「为什么选它」。"
                ),
            },
            "recommended": {
                "type": "boolean",
                "description": (
                    "可选：标记你建议的那一项（至多一个）。仅「推荐」高亮、不会替用户预选；"
                    "要预选请用 default。"
                ),
            },
        }
        # Schema: short trigger. HOW → ask_user_kickoff / ask_user_midtask skills.
        questions_desc = (
            "可选：要用户拍板的问题（最多 5）。关键岔路通常预填或省略 default。"
            "choice 可配 detail / recommended。用法见 consult_skill。"
        )
        tool_desc = (
            "向用户发问（唯一问用户原语）。默认 blocking 暂停回合；"
            "blocking=false 非阻塞按默认继续。"
            "通用短澄清：信息不够时短问，可与检索/读文件等穿插、可连续多次；"
            "Agent 自主决定何时问。详见 consult_skill"
            "（ask_user_kickoff / ask_user_midtask）。"
        )
        if self.advertise_bind_local_folder:
            option_properties["action"] = {
                "type": "string",
                "enum": [
                    "open_local_project",
                    "bind_local_folder",
                    "grant_readonly_folder",
                    "grant_organize_folder",
                ],
                "description": (
                    "可选。按意图分流："
                    "open_local_project=打开本机文件夹为本地项目（新建会话挂 Folder，"
                    "空 subpath；不改本会话 folder_id）；"
                    "bind_local_folder=本会话绑本机执行环境（裸聊 scratch，≠打开项目）；"
                    "grant_readonly_folder=开只读授权（区外目录、仅本对话；与绑定正交，"
                    "云端草稿+桌面在线亦可）；"
                    "grant_organize_folder=开整理授权（可移动/重命名/复制/删进回收站、仅本对话）。"
                ),
            }
            questions_desc += (
                " 打开本机目录当项目→open_local_project；本会话只要本机执行→"
                "bind_local_folder；区外只读/整理→grant_*"
                "（action=open_local_project / bind_local_folder / "
                "grant_readonly_folder / grant_organize_folder）。"
            )
            tool_desc += (
                " 桌面在线时可标 open_local_project / bind_local_folder / "
                "grant_readonly_folder / grant_organize_folder（按意图分流）。"
            )

        return ToolSchema(
            name="ask_user",
            description=tool_desc,
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "必填。卡片顶部说明（问什么、为何需拍板）。",
                    },
                    "context": {
                        "type": "string",
                        "description": "可选：背景补充。",
                    },
                    "assumptions": {
                        "type": "array",
                        "description": (
                            "可选：低影响默认可逆决策（只读陈列）。高杠杆放 questions。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "决策项。",
                                },
                                "value": {
                                    "type": "string",
                                    "description": "默认值。",
                                },
                            },
                            "required": ["label", "value"],
                        },
                    },
                    "questions": {
                        "type": "array",
                        "description": questions_desc,
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "问题正文。",
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["choice", "text"],
                                    "description": "choice 或 text，默认 choice。",
                                },
                                "options": {
                                    "type": "array",
                                    "description": "kind=choice 候选项（最多 6）。",
                                    "items": {
                                        "type": "object",
                                        "properties": option_properties,
                                        "required": ["label"],
                                    },
                                },
                                "multiple": {
                                    "type": "boolean",
                                    "description": "可选：允许多选，默认 false。",
                                },
                                "default": {
                                    "type": "string",
                                    "description": "可选默认答案（choice=某 label）。",
                                },
                            },
                            "required": ["prompt"],
                        },
                    },
                    "style_options": {
                        "type": "array",
                        "description": (
                            "可选兼容字段：视觉风格候选（不记账、不硬闸；优先短问）。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "风格名。",
                                },
                            },
                            "required": ["label"],
                        },
                    },
                    "format_options": {
                        "type": "array",
                        "description": (
                            "可选兼容字段：交付形态候选（不记账、不硬闸；优先短问）。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "交付形态名。",
                                },
                            },
                            "required": ["label"],
                        },
                    },
                    "blocking": {
                        "type": "boolean",
                        "description": (
                            "可选，默认 true。false=非阻塞（须在 assumptions/default 写明默认）。"
                        ),
                    },
                    "card": {
                        "type": "string",
                        "enum": ["proposal_pick", "risk_ack", "organize_plan", "daily_review"],
                        "description": (
                            "可选卡型（都须 blocking、且恰好 1 个 question）："
                            "proposal_pick=从 2–6 个候选方案里单选一个"
                            "（kind=choice、multiple=false）；"
                            "risk_ack=从 1–10 条风险项里多选要处理哪些（multiple=true）；"
                            "organize_plan=从 1–50 条整理项里多选（multiple=true）；"
                            "daily_review=每日复盘提案多选（multiple=true，options 须带 "
                            "review_kind+body；确认后由服务端落盘）。"
                            "要问多个【不同】问题就别用 card（用普通 ask_user，questions 最多 5）。"
                            "详见 ask_user_* skill。"
                        ),
                    },
                },
                "required": ["message"],
            },
            category=ToolCategory.INTERACTION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        message = str(arguments.get("message") or "").strip()
        if not message:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="ask_user 需要非空的 message 参数（向用户说明你在问什么）。",
            )
        card_parsed = parse_card(arguments.get("card"))
        # Success returns a known card literal (also a str); errors return a Chinese
        # guidance string not in CARD_KINDS.
        if card_parsed is None:
            card = None
        elif card_parsed in CARD_KINDS:
            card = card_parsed  # type: ignore[assignment]
        else:
            logger.info(
                "ask_user.card_rejected",
                conversation_id=self.conversation_id,
                card=str(arguments.get("card")),
                reason="unknown",
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=str(card_parsed) + CARD_RETRY_HINT,
            )

        ctx_text = str(arguments.get("context") or "")
        try:
            assumptions = normalize_assumptions(arguments.get("assumptions"))
            questions = normalize_questions(
                arguments.get("questions"),
                max_options=card_max_options(card),
            )
            style_options = normalize_style_options(arguments.get("style_options"))
            format_options = normalize_format_options(arguments.get("format_options"))
        except ListArgError as exc:
            logger.info(
                "ask_user.list_arg_rejected",
                conversation_id=self.conversation_id,
                error=str(exc),
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    f"{exc} 请直接传 JSON 数组，不要把数组再序列化成字符串。"
                    f"{CARD_RETRY_HINT}"
                ),
            )
        if not self.advertise_bind_local_folder:
            for q in questions:
                for opt in q.get("options") or []:
                    if isinstance(opt, dict):
                        opt.pop("action", None)

        # 非阻塞发问 (Cursor 式): surface + proceed, never freeze the turn. Branch BEFORE
        # any suspend / durable-frame machinery — it shares none of it.
        blocking_arg = arguments.get("blocking")
        blocking = True if blocking_arg is None else bool(blocking_arg)

        if card is not None:
            card_err = validate_card_shape(card, blocking=blocking, questions=questions)
            if card_err:
                # Observability for the recurring model fumble (e.g. kickoff-style
                # multi-question asks tagged card=proposal_pick): count + shape details.
                logger.info(
                    "ask_user.card_rejected",
                    conversation_id=self.conversation_id,
                    card=card,
                    reason="shape",
                    questions=len(questions),
                    blocking=blocking,
                )
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=card_err + CARD_RETRY_HINT,
                )

        if not blocking:
            return self._post_nonblocking(
                message, ctx_text, assumptions, questions, style_options, format_options
            )

        checkpoint_id = new_id()
        from agentcore.runtime.suspension import captain_transcript

        intent = (
            card_overrides_intent(card)
            if card is not None
            else resolve_ask_checkpoint_intent(captain_transcript.get())
        )
        # style_options / format_options：wire 兼容可传，不记账、不硬闸。
        required = checkpoint_required(
            checkpoint_id=checkpoint_id,
            conversation_id=self.conversation_id,
            question=message,
            context=ctx_text,
            assumptions=assumptions,
            questions=questions,
            style_options=style_options,
            format_options=format_options,
            intent=intent,
        )
        # 结构化挂起 2b + D11: persist the durable frame BEFORE finalize. Save success
        # ⇒ 挂起即收口 (②); save failure ⇒ explicit error (no in-memory wait fallback).
        # CEO 协调模式 Phase 2: snapshot coordination state into the journal before
        # SUSPEND so resume can rebuild draft / completed / budget.
        from agentcore.runtime.coordination.session import active_coordination

        coord = active_coordination(context.execution_id)
        if coord is not None:
            from agentcore.runtime.coordination.journal import record_coordination_snapshot

            record_coordination_snapshot(coord)
            # Soft-stop the background scheduler — resume re-drives unfinished workers
            # from the journal seed. Cancelling avoids orphan tasks after turn end.
            # Mark soft_stop BEFORE cancel so the drive cancel handler skips wake
            # events (no ALL_COMPLETED / DRIVE_CANCELLED in the hang-frame snapshot).
            if coord.drive_task is not None and not coord.drive_task.done():
                coord.soft_stop = True
                coord.drive_task.cancel()
        try:
            saved = await persist_suspension(
                self,
                checkpoint_id=checkpoint_id,
                context=context,
                message=message,
                ctx_text=ctx_text,
                assumptions=assumptions,
                questions=questions,
                style_options=style_options,
                format_options=format_options,
                required_event=required,
                intent=intent,
            )
        except Exception:
            # D11：运行态落帧失败 ⇒ 显式失败终止回合（与配置态不可用同文案）。
            logger.exception(
                "checkpoint.persist_failed",
                checkpoint_id=checkpoint_id,
            )
            return ToolResult(
                tool_call_id="",
                success=False,
                output="无法持久化检查点，回合已终止。请重试。",
            )
        # 挂起即收口 (②): once the durable frame is saved, END the turn in place.
        # D11：删窄兜底——无法落盘则显式失败终止回合（不再假等待）。
        if saved:
            self.sink.emit(required)
            logger.info(
                "checkpoint.finalized",
                checkpoint_id=checkpoint_id,
                intent=intent,
                card=card,
            )
            return ToolResult(tool_call_id="", success=True, output="", effect=ToolEffect.SUSPEND)
        logger.error(
            "checkpoint.persist_unavailable",
            checkpoint_id=checkpoint_id,
            reason="no_durable_frame",
        )
        return ToolResult(
            tool_call_id="",
            success=False,
            output="无法持久化检查点，回合已终止。请重试。",
        )

    def _post_nonblocking(
        self,
        message: str,
        ctx_text: str,
        assumptions: list[dict[str, Any]],
        questions: list[dict[str, Any]],
        style_options: list[dict[str, Any]],
        format_options: list[dict[str, Any]],
    ) -> ToolResult:
        """非阻塞发问 (Cursor 式)：抛出确认但不挂起——CEO 按既定默认续跑，答复后续并入。

        The counterpart to suspend+resume: rather than freezing the turn on the user's
        answer, surface the question as a non-gating ``question_posted`` card (the client
        renders chips that 回填 the composer; the answer rides an ordinary next-turn
        message) and feed the CEO a ``CONTINUE`` that orders it to keep working on its
        stated default. Guarded: a non-blocking ask MUST carry a fallback (an assumption,
        or a question ``default``) or the user can't trust the CEO to proceed — without
        one it returns an error steering the model to ``blocking=true`` instead. No
        suspend / frame / extra round, so it costs nothing the worker-side ``escalate``
        doesn't.
        """
        has_fallback = bool(assumptions) or any(q.get("default") for q in questions)
        if not has_fallback:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "非阻塞发问（blocking=false）必须写明你将先采用的默认：在 assumptions "
                    "列出你的暂定决策，或给某个 question 填 default。否则用户无从判断能否放心"
                    "不管。若你确实要等用户拍板再动，请改用 blocking=true。"
                ),
            )
        self.sink.emit(
            question_posted(
                ask_id=new_id(),
                conversation_id=self.conversation_id,
                question=message,
                context=ctx_text,
                assumptions=assumptions,
                questions=questions,
                style_options=style_options,
                format_options=format_options,
            )
        )
        logger.info(
            "ask_user.nonblocking",
            conversation_id=self.conversation_id,
            questions=len(questions),
            assumptions=len(assumptions),
        )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=(
                "已（非阻塞）把这个确认抛给用户，并按你写明的默认继续。【不要等待、不要停】："
                "立刻继续推进手头工作、把本回合做完；用户若回复会作为新消息在后续轮次到达，"
                "届时再据此调整。"
            ),
        )

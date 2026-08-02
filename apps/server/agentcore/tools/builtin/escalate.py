"""escalate — a worker's upward channel: flag a decision/blocker for the CEO.

Worker-only. Wired into the delegated worker toolset (``build_worker_registry``) and
deliberately NOT in ``build_builtin_registry`` — so it never reaches the CEO's own
toolset (``build_ceo_tool_registry`` derives from the builtins) or the read-only
``GET /tools`` capability catalog. It is the WORKER's counterpart to the CEO's
``ask_user``: a delegated worker can't talk to the user (隔离边界), so when it hits a
fork only a human / 上级 can settle, it escalates to the CEO instead of either
silently guessing or burying a clarifying question in its prose.

Two modes, one primitive — the worker picks via ``blocking`` (the dual of the CEO's
``ask_user``). NON-BLOCKING (default, ``blocking`` false): the call returns immediately
(``ToolEffect.CONTINUE``) and tells the worker to PROCEED on its best assumption — it is
NOT a stop. The escalation is harvested from the worker's transcript
(``runs.serialize.escalations_from_transcript``) into ``RunState.escalations`` and surfaced
PROMINENTLY in the CEO-facing aggregate (``ceo_format.format_for_ceo``), where the CEO
resolves it at synthesis with its OWN levers: ``ask_user`` (if the user must decide),
``delegate``（设 ``continue_from_run_id`` 带现场续派），或冷委派新人。A wrong assumption
is corrected at synthesis, not propagated silently down the chain.

BLOCKING (阻塞式求决策, ``blocking`` true): for a「猜错你的产物基本作废」fork, the worker
SUSPENDS in place. Who mediates depends on mode:

- **经典路径**（无活跃协调 session）：波内没有在跑的 CEO，故直挂用户（同 ``ask_user`` 交互桥，
  ``InteractionKind.ESCALATION``）。
- **协调模式**（根 CEO 协调 session 活跃，≥2 worker 默认）：CEO 波内存活，阻塞升级改由 CEO
  仲裁——worker
  挂起等 ``resolve_escalation``；初始不发用户可答卡。偏好/授权/费用类由 CEO 先 ``ask_user``
  再 resolve（单一兑现路径）。默认无限期等待（D2：``checkpoint_timeout_seconds`` 默认 None）；
  用户 / CEO 可显式「按假设继续」；仅运维配置了超时上限时才出现 ``timed_out`` 并回落
  ``assumption``。

Un-armed turns (autonomous / handoff) and a full concurrency cap degrade to the
non-blocking path (自动按 ``assumption`` 继续). The mechanism (cap / suspend / SSE events /
RunState recording) lives behind ``ToolContext.escalation`` so this tool stays off the event
vocabulary (引擎纯化); the tool owns only the decision + the outcome→result mapping
(:func:`escalate_tool_result`).
设计见 docs/03-AI核心/Agent协作模式.md / 执行引擎架构设计.md（D2）；对比见编排器文档。
"""

from __future__ import annotations

from typing import Any

from agentcore.core.logging import get_logger
from agentcore.core.text import clip_preview
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.runs.constants import ESCALATE_TOOL_NAME
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)

logger = get_logger(__name__)


class EscalateTool:
    """The worker's「向上求决策」primitive: record a待决问题 for the CEO, keep working.

    Stateless: the call's structured args ride the worker's transcript, from which the
    executor harvests them into ``RunState.escalations``. ``execute`` only validates and
    returns a CONTINUE acknowledgement that steers the worker to deliver its best-effort
    result under its stated assumption (so an escalation never becomes an excuse to stop).
    """

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=ESCALATE_TOOL_NAME,
            description=(
                "把一个【必须由上级/用户拍板】的待决问题、或一个【职责/范围偏离】上报。你是被"
                "委派的 worker、够不到用户，这是你唯一的向上通道。仅在遇到【缺了就会让整件事"
                "走偏的关键信息】【只有上级/用户能定的关键岔路】或【发现真正该做的与初始计划"
                "不符】时才用——能自行合理假设的小事不要升级。\n"
                "blocking 维度：默认 false【非阻塞】——上报后你立刻按假设继续、主管收尾时纠偏；"
                "true【阻塞·求决策】——仅当岔路【猜错你的产物基本作废】时用：你原地挂起、拿到"
                "答复再继续（须写明 assumption）。协调模式下由主管仲裁；经典路径直送用户。\n"
                "kind 维度（正交）：默认 normal=普通待决问题；scope=【职责偏离】——你发现真正"
                "该做的与初始计划/子任务设定不符（如上游产出显示真问题是 X 不是 Y）；dep=【卡在"
                "缺输入】——你缺一个【还不存在】的输入 / 依赖才能继续（没人产出过、计划也没安排；"
                "先用 read_notes 翻墙确认队友确实没贴过再上报）。dep 该主动：真卡在这种再猜也是"
                "错的缺口上时别硬猜瞎编一个，发 dep 让上级在波边界补，强过闷头产出一堆作废的东西。"
                "scope / dep 主管 / lead 都会在波"
                "边界据此校准【尚未运行】的下游（scope→操舵已有步骤，dep→replan 追加一个产出它的"
                "步骤 / 接一条依赖边）；两者都【不停工】——你照常按假设把当前能做的做完。"
                "克制使用 normal 与 blocking——能自行合理假设的小事别升级、blocking 省着用；"
                "唯独 dep（卡在【不存在】的输入、再猜也是错）该喊就喊、别硬猜瞎编。"
                "browser_login：仅 blocking 有意义；为 true 时强制阻塞语义，挂起后允许用户在"
                "回合仍 running 时接管浏览器完成登录（AI 永不经手密码）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "必填。需要上级拍板的具体问题，写清楚、自包含——主管可能会把它"
                            "near-verbatim 转给用户，所以别依赖只有你才懂的局部上下文。"
                        ),
                    },
                    "assumption": {
                        "type": "string",
                        "description": (
                            "在拿到答复前你暂时采用的假设（你正/将据此继续）。blocking=true 时"
                            "【必填】：用户 / 主管显式「按假设继续」、或未武装 / 并发满退化为非阻"
                            "塞、或运维配置了超时上限且届时未答复时，按它继续；blocking=false 时"
                            "强烈建议——写明它，主管才能判断你的产物是否需要据真实答案返工。"
                        ),
                    },
                    "blocking": {
                        "type": "boolean",
                        "description": (
                            "可选，默认 false。false=【非阻塞】：上报后你立刻按假设把活做完、"
                            "主管收尾纠偏。true=【阻塞·求决策】：仅当这个岔路【猜错你的产物基本"
                            "作废】时用——你会原地挂起等裁决再继续（须写明 assumption；默认无限"
                            "期等待，用户 / 主管可点「按假设继续」；仅未武装 sink、并发满、或运维"
                            "显式配置超时时才自动按假设继续）。"
                        ),
                    },
                    "browser_login": {
                        "type": "boolean",
                        "description": (
                            "可选，默认 false。true=请求用户接管云端浏览器完成登录（密码由用户"
                            "亲手输入，AI 永不经手）。仅 blocking 有意义：为 true 时强制升格为"
                            "blocking=true（须写明 assumption）。典型触发：browser_type 对 "
                            "password 框硬拒（metadata.code=password_blocked）之后。"
                        ),
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["normal", "scope", "dep"],
                        "description": (
                            "可选，默认 normal。scope=【职责偏离】：你发现真正要做的事与初始计划"
                            "/你的子任务设定不符（例如上游产出显示真问题是 X 不是 Y），需要主管据此"
                            "校准【尚未运行】的下游步骤——主管会在波边界读到你的偏离信号并操舵下游。"
                            "dep=【卡在缺输入】：你缺一个【还不存在】的输入 / 依赖才能继续——没人产"
                            "出过、计划也没安排（先用 read_notes 翻墙确认队友确实没贴过；若墙上已有"
                            "就直接读、不必升级）。这一类该【主动】：真卡在再猜也是错的缺口上时，别硬"
                            "猜瞎编、主动发 dep，强过闷头产出一堆作废的东西。"
                            "主管 / lead 会在波边界用 replan 追加一个产出它的"
                            "步骤 / 接一条依赖边。scope / dep 你都仍照常把当前能做的做完、"
                            "不必阻塞。"
                            "normal=普通待决问题（默认）。"
                        ),
                    },
                    "questions": {
                        "type": "array",
                        "description": (
                            "可选，仅 blocking=true 时有意义：把这个【关键岔路】"
                            "拆成结构化选项，便于一键拍板、不必读散文再手敲。"
                            "岔路是干净的 A/B 或多选时强烈建议给（结构同 ask_user 的 "
                            "questions，最多 5 个）；纯开放问题（无明确候选）则省略，"
                            "文本作答。"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "问题本身，简洁清楚。",
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["choice", "text"],
                                    "description": (
                                        "choice=从 options 里选；text=让用户填一句。默认 choice。"
                                    ),
                                },
                                "options": {
                                    "type": "array",
                                    "description": "kind=choice 时的候选项（最多 6 个）。",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "description": (
                                                    "选项文字（即选它时回传的答案）。"
                                                ),
                                            },
                                            "detail": {
                                                "type": "string",
                                                "description": (
                                                    "可选：这一项的一行权衡 / 代价，"
                                                    "帮看懂取舍。"
                                                ),
                                            },
                                            "recommended": {
                                                "type": "boolean",
                                                "description": (
                                                    "可选：标记倾向的那一项（至多一个，仅高亮"
                                                    "不预选；要预选用 default）。"
                                                ),
                                            },
                                        },
                                        "required": ["label"],
                                    },
                                },
                                "multiple": {
                                    "type": "boolean",
                                    "description": "可选：options 是否允许多选，默认 false。",
                                },
                                "default": {
                                    "type": "string",
                                    "description": (
                                        "可选：暂定倾向（choice 时应是 options 中某项 label）。"
                                    ),
                                },
                            },
                            "required": ["prompt"],
                        },
                    },
                },
                "required": ["question"],
            },
            category=ToolCategory.ORCHESTRATION,
            approval=ToolApproval.NEVER,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        question = str(arguments.get("question") or "").strip()
        if not question:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error="escalate 需要非空的 question（写清你要上级拍板的问题）。",
            )
        assumption = str(arguments.get("assumption") or "").strip()
        blocking = bool(arguments.get("blocking"))
        # browser_login forces blocking semantics (narrow D16 exception for user login
        # takeover while the escalate is pending). Promote rather than reject so a model
        # that sets browser_login without blocking still lands on the suspend path.
        browser_login = bool(arguments.get("browser_login"))
        if browser_login:
            blocking = True
        # 执行引擎架构设计.md §受监督的波循环: kind=scope marks a 职责/范围 deviation and
        # kind=dep a 依赖缺口 (卡在缺输入 X, §2.4) — BOTH are consumed at the reactive wave
        # boundary (the CEO re-steers / replan(add)s the un-run tail), distinct from the
        # 阻塞式求决策 blocking axis. Unknown values degrade to "normal".
        kind = str(arguments.get("kind") or "normal").strip().lower()
        if kind not in ("normal", "scope", "dep"):
            kind = "normal"
        # blocking=true 须带 assumption: dual of ask_user(blocking=false) requiring a
        # fallback — used when the user/CEO explicitly「按假设继续」, when the call degrades
        # to non-blocking (unarmed / concurrency cap), or when ops configured a timeout.
        # Without it those paths would have nowhere to land — reject rather than guess.
        if blocking and not assumption:
            return ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "escalate(blocking=true) 必须写明 assumption：显式「按假设继续」、未武装/"
                    "并发满退化、或运维配置超时未答复时，你将按它继续。"
                    "若你本就能自行假设、不需拍板，请改用 blocking=false。"
                    + (
                        "（browser_login=true 已强制升格为 blocking，同样需要 assumption。）"
                        if browser_login
                        else ""
                    )
                ),
            )
        logger.info(
            "worker.escalate",
            run_id=context.run_id,
            blocking=blocking,
            kind=kind,
            browser_login=browser_login,
            has_assumption=bool(assumption),
            # The 决策/blocker itself + the worker's fallback assumption — the「为什么升级」an
            # offline analysis needs (kind/blocking alone say一次 escalation happened, not什么).
            question=clip_preview(question, 200),
            assumption=clip_preview(assumption, 160),
        )
        # 阻塞·求决策: suspend when the turn is armed (a live interactive client).
        # Classic path → user; coordination-active → CEO arbitration (D1). The channel owns
        # cap / suspend / SSE / RunState recording; we only map its outcome. A ``degraded``
        # outcome (concurrency cap full) or an unarmed turn (no channel) falls through to the
        # non-blocking path below — so blocking is a strict superset of non-blocking, never a
        # regression (设计 §4.4).
        # 结构化升级（复用 ask_user 的问题规整）：把岔路拆成 choice/text 选项随挂起卡下发。
        # Local import 避免经 ask_user 包 __init__ 触发 runtime 依赖环。
        from agentcore.tools.builtin.ask_user.schema import ListArgError, normalize_questions

        channel = context.escalation
        if blocking and channel is not None and channel.armed:
            try:
                questions = normalize_questions(arguments.get("questions"))
            except ListArgError as exc:
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=(
                        f"{exc} 请直接传 JSON 数组，不要把数组再序列化成字符串。"
                    ),
                )
            # browser_login / 写权冲突 must reach the human (password never touches AI;
            # 「移交」自然语言不会自动转锁). Skip coordination CEO arbitration.
            from agentcore.workspace.write_claims import ownership_escalation_hints

            ownership_hints = ownership_escalation_hints(
                escalator_run_id=context.run_id,
                question=question,
                execution_id=context.execution_id,
                write_ancestors=context.write_ancestors,
                write_coordinator=context.write_coordinator,
            )
            ownership_paths = ownership_hints.get("ownership_paths")
            # 用户写权卡仅锁主仍在跑；已完成占位靠同座续派/declare 接手，不直达用户移交。
            user_ownership_card = bool(ownership_paths) and (
                ownership_hints.get("owner_status") == "running"
            )
            awaiting = "user"
            if not browser_login and not user_ownership_card:
                try:
                    from agentcore.runtime.coordination.session import active_coordination

                    coord = active_coordination(context.execution_id)
                    if coord is not None and coord.active:
                        awaiting = "ceo"
                except Exception:  # noqa: BLE001
                    awaiting = "user"
            outcome = await channel.request(
                question,
                assumption,
                questions,
                kind,
                awaiting,
                browser_login=browser_login,
                ownership_paths=ownership_paths if user_ownership_card else None,
                lock_owner_run_id=(
                    str(ownership_hints.get("lock_owner_run_id") or "")
                    if user_ownership_card
                    else ""
                ),
            )
            if outcome.status != "degraded":
                return escalate_tool_result(
                    outcome.status,
                    outcome.answer,
                    assumption,
                    arbitrated_by=awaiting,
                )
        # 非阻塞 (default) / degraded / unarmed: surface the escalation live (best-effort,
        # non-fatal — the durable transcript → RunState.escalations path is unconditional)
        # and steer the worker to deliver under its assumption; the CEO纠偏 at synthesis.
        if context.on_escalate is not None:
            try:
                context.on_escalate(question, assumption, blocking, kind)
            except Exception:  # noqa: BLE001 — liveliness only; never break the worker
                logger.warning("worker.escalate.emit_failed", run_id=context.run_id)
        # CEO 协调模式 Phase 3: route into the living CEO's event queue (not wave-boundary
        # YIELD). Best-effort — never break the worker if the bridge is unavailable.
        # (Blocking+CEO path already posted inside the channel; this covers non-blocking.)
        try:
            from agentcore.runtime.coordination.bridge import post_escalation_to_coordination
            from agentcore.workspace.write_claims import ownership_escalation_hints

            hints = ownership_escalation_hints(
                escalator_run_id=context.run_id,
                question=question,
                execution_id=context.execution_id,
                write_ancestors=context.write_ancestors,
                write_coordinator=context.write_coordinator,
            )
            post_escalation_to_coordination(
                run_id=context.run_id,
                role=context.agent_role or "",
                kind=kind,
                question=question,
                assumption=assumption,
                blocking=blocking,
                source="escalate",
                execution_id=context.execution_id,
                ownership_paths=hints.get("ownership_paths"),
                lock_owner_run_id=str(hints.get("lock_owner_run_id") or ""),
                escalator_is_lock_owner_nested_child=hints.get(
                    "escalator_is_lock_owner_nested_child"
                ),
                ownership_kind=hints.get("ownership_kind"),
                owner_status=hints.get("owner_status"),
            )
        except Exception:  # noqa: BLE001
            logger.warning("worker.escalate.coordination_route_failed", run_id=context.run_id)
        if kind == "scope":
            note = (
                "已记录你的职责偏离信号，主管会在波边界据此校准尚未运行的下游步骤。"
                "这不是停工：请立刻按你当前最合理的假设把任务继续做完、交付最佳结果"
            )
        elif kind == "dep":
            note = (
                "已记录你的依赖缺口（卡在缺输入）信号，主管 / lead 会在波边界用 replan 追加一个"
                "产出它的步骤 / 接一条依赖边。这不是停工，也不会同步等队友：请立刻按你当前最合理的"
                "假设把任务继续做完、交付最佳结果"
            )
        else:
            note = (
                "已记录你的升级，主管会在汇总你的产物时处理。"
                "这不是停工：请立刻按你当前最合理的假设把任务继续做完、交付最佳结果"
            )
        note += (
            "（你已写明假设，主管能据此判断是否需要返工）。"
            if assumption
            else "，并尽量在产出里写明你采用了什么假设，方便主管纠偏。"
        )
        return ToolResult(tool_call_id="", success=True, output=note)


def escalate_tool_result(
    status: str,
    answer: str | None,
    assumption: str,
    *,
    arbitrated_by: str = "user",
) -> ToolResult:
    """Map a blocking escalate's outcome to the CONTINUE result the worker loop consumes.

    The single source of truth for the live suspend path (and any future durable resume),
    the worker-side dual of :func:`~agentcore.tools.builtin.ask_user.ask_user_tool_result`:

    - ``"resolved"`` → feed the ``answer`` back into the worker's loop;
    - ``"assumed"`` → explicit 按假设继续 (user or CEO);
    - ``"timed_out"`` → wall-clock miss;
    - both assumed and timed_out steer the worker onto its stated ``assumption``.

    Never terminal: an escalation RESUMES the worker, it never ends the turn (停回合 is the
    CEO ``ask_user`` / 对话级 job, never a single worker's call — 设计 §4.5).
    """
    if status == "resolved":
        ans = (answer or "").strip()
        if arbitrated_by == "ceo":
            output = (
                f"主管就你的升级问题裁决：\n{ans}\n"
                "请据此继续；与你的暂定假设冲突处以裁决为准，并回改已按假设做出的部分。"
            )
        else:
            output = (
                f"用户就你的升级问题答复：\n{ans}\n"
                "请据此继续；与你的暂定假设冲突处以用户答复为准，并回改已按假设做出的部分。"
            )
        return ToolResult(tool_call_id="", success=True, output=output)
    who = "主管" if arbitrated_by == "ceo" else "用户"
    # timed_out (and any other non-resolved/assumed settlement) → second branch
    lead = (
        f"{who}选择按你的假设继续。"
        if status == "assumed"
        else f"未在时限内得到{who}答复。"
    )
    return ToolResult(
        tool_call_id="",
        success=True,
        output=f"{lead}请按你写明的假设把任务继续做完：{assumption}。",
    )

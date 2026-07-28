"""Tool Protocol, ToolSchema, and approval three-state.

Defines the unified contract for all tools (built-in and external).
Tools declare their schema (for LLM function calling) and implement execute().
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from agentcore.core.text import truncate_head_tail
from agentcore.core.types import ToolApproval, ToolCategory, ToolEffect

if TYPE_CHECKING:
    from agentcore.board.channel import BoardChannel
    from agentcore.desktop.channel import DesktopClientChannel
    from agentcore.runtime.costing import RunCost
    from agentcore.runtime.runs.notewall import NoteWall, TeamNote
    from agentcore.vision.protocol import VisionReader
    from agentcore.workspace.channel import WorkspaceChannel
    from agentcore.workspace.protocol import WorkspaceBackend
    from agentcore.workspace.write_claims import WriteCoordinator


@dataclass(frozen=True)
class EscalationOutcome:
    """The result of a worker's blocking escalate (阻塞式求决策 §4.4).

    ``status``:
    - ``"resolved"`` — answered (``answer`` carries it);
    - ``"assumed"`` — explicit 按假设继续 (user or CEO);
    - ``"timed_out"`` — wall-clock miss (no answer within the window);
    - ``"degraded"`` — never suspended (concurrency cap) → proceed on assumption
      like a non-blocking escalate.

    ``assumed`` and ``timed_out`` share the worker fallback (use stated assumption)
    but must stay distinct on the wire — conflating them as ``timeout`` made
    「点了按假设继续」look like「系统超时没收到点击」.
    """

    status: str
    answer: str | None = None


@dataclass
class EscalationChannel:
    """Per-run wiring that lets a worker's ``escalate(blocking=true)`` suspend.

    Built by ``build_agent_executor`` for each delegated worker and ``None`` on the
    CEO / tests / unarmed turns (then ``escalate`` keeps its non-blocking behaviour).
    ``armed`` is the live-user gate (the SAME gate as ``ask_user`` — a live
    interactive client). ``request`` owns the mechanism the tool must stay clear of
    (引擎纯化): it enforces the concurrency cap, suspends on the interaction bridge,
    emits the ``escalation_required`` / ``escalation_resolved`` pair, records the
    resolution into the worker's ``RunState`` for CEO synthesis, and returns the
    :class:`EscalationOutcome`. The tool only decides WHETHER to block and maps the
    outcome to its ``ToolResult``.

    ``awaiting`` on ``request``: ``"user"`` (经典直挂用户) or ``"ceo"`` (协调模式等主管
    仲裁；初始不发用户可答卡，由 ``resolve_escalation`` 兑现).
    """

    armed: bool
    # ``request(question, assumption, questions, kind, awaiting="user",
    # browser_login=False)`` — trailing ``browser_login`` is optional for
    # backward-compatible mocks (defaults False on the production channel).
    request: Callable[..., Awaitable[EscalationOutcome]]


@dataclass(frozen=True)
class ToolSchema:
    """Tool metadata declaration for LLM function calling."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema format
    category: ToolCategory
    approval: ToolApproval = ToolApproval.NEVER
    # Engine-level hard ceiling (seconds) for ONE call of this tool — a B1 backstop
    # so a wedged tool can't stall a whole turn. ``None`` ⇒ the engine applies a
    # per-category default (``runtime.engine.resolve_tool_timeout``); ORCHESTRATION
    # / INTERACTION tools are exempt (they legitimately wait minutes on sub-runs or
    # the user). Set explicitly only for a non-default ceiling. This is a coarse
    # safety net layered ABOVE a tool's own finer timeout (e.g. ``code_execute``
    # caps its sandbox itself), never a replacement for it.
    timeout_seconds: float | None = None


@dataclass
class RetrievalBudgetState:
    """Per-run ``web_search`` / ``read_url`` counter (提案 A1).

    Wired onto :class:`ToolContext` by the worker executor. ``used`` is reserved
    before a live call and refunded on cache hits / uncharged results so parallel
    tool_exec calls cannot overshoot ``limit``.

    ``consecutive_empty_searches`` tracks live empty SERPs in this run so the
    search tool can require a strategy change after a streak (成篇质量定案).
    """

    limit: int
    used: int = 0
    consecutive_empty_searches: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def note_search_empty(self) -> int:
        """Record an empty SERP; return the new consecutive-empty streak."""
        self.consecutive_empty_searches += 1
        return self.consecutive_empty_searches

    def note_search_hit(self) -> None:
        """Reset empty streak after a non-empty injection."""
        self.consecutive_empty_searches = 0

    async def try_reserve(self) -> bool:
        """Reserve one slot. False ⇒ exhausted (caller must not run the tool)."""
        async with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True

    async def refund(self) -> None:
        """Return a reserved slot (cache hit / uncharged call)."""
        async with self._lock:
            if self.used > 0:
                self.used -= 1

    async def refill(self, extra: int) -> int:
        """Grant ``extra`` additional retrieval slots (contract rework slice).

        Raises the ``limit`` (not a used-reset) so prior charges stay honest while
        the rework pass gets a fresh slice. Returns the new remaining count.
        Prefer :meth:`refill_within_cap` for budget-bounded rework.
        """
        async with self._lock:
            add = max(0, int(extra))
            self.limit += add
            return max(0, self.limit - self.used)

    async def refill_within_cap(self, extra: int, *, cap: int) -> int:
        """Grant up to ``extra`` slots without raising ``limit`` above ``cap``.

        Contract rework must not bypass the original retrieval budget ceiling.
        When ``cap <= 0`` or there is no headroom, this is a no-op (returns current
        remaining). Returns the new remaining count.
        """
        async with self._lock:
            add = max(0, int(extra))
            add = min(add, max(0, int(cap) - self.limit)) if cap > 0 else 0
            self.limit += add
            return max(0, self.limit - self.used)


@dataclass
class ToolContext:
    """Context provided to tools during execution."""

    execution_id: str
    run_id: str
    agent_id: str
    backend: WorkspaceBackend
    user_id: str
    # The owning conversation, used by conversation-scoped tool state (e.g. the
    # read_url fetch cache, web/url_cache.py). Set once on the pipeline's base
    # context and inherited by every worker via ``dataclasses.replace``. Defaults
    # to "" for unscoped call sites (tests / evals) — a tool simply skips its
    # conversation-scoped optimisation when this is empty.
    conversation_id: str = ""
    # Session permission mode (observe / workspace / full_trust). Used by sandbox
    # network grading (P2: full_trust → restricted egress on cloud gVisor).
    permission_preset: str | None = None
    # 深度研究自治：会话旗标 + 本会话已自动开辩次数（cap 见 runtime.deep_research_auto）。
    # Set once on the pipeline base context; debate kickoff mutates the count in place
    # after a waived auto-adopt start so a same-turn second debate sees the cap.
    deep_research_auto: bool = False
    deep_research_auto_debate_count: int = 0
    # Intra-batch write-conflict guard (并行写隔离·硬约束). Set per delegated-worker
    # node by ``build_agent_executor``; ``None`` for the CEO / tests (no concurrent
    # siblings to coordinate, so ``file_write`` skips the check). ``write_ancestors`` is
    # this node's ``depends_on`` transitive closure ∪ nested ``parent_run_id``, so it
    # MAY overwrite a file owned by an upstream / lead it consolidates but not one a
    # concurrent sibling did.
    write_coordinator: WriteCoordinator | None = None
    write_ancestors: frozenset[str] = frozenset()
    # 团队便签墙 (§2.2 通): the per-batch sticky-note wall the worker-only ``post_note`` tool
    # broadcasts onto and that the engine pushes fresh sibling notes from before each step.
    # Set per delegated-worker node by ``build_agent_executor`` (one wall shared by the batch);
    # ``None`` for the CEO / solo worker / tests (no concurrent siblings) — then ``post_note``
    # returns a clean「无并行队友」result and no notes are injected. ``agent_role`` is this
    # worker's display role, stamped onto its notes for sibling-facing attribution (谁贴的).
    note_wall: NoteWall | None = None
    agent_role: str = ""
    # 团队便签墙 实时可见: a narrow callback the ``post_note`` tool fires the INSTANT a note is
    # pinned, so the team-notes panel lights up live (the durable record rides the journaled
    # ``team_note_posted`` event this callback emits). Set per delegated-worker node by
    # ``build_agent_executor`` (it closes over the run's EventSink + execution_id); ``None``
    # for the CEO / tests — the tool still records onto the wall, only the live banner is
    # skipped. A narrow callback (not the EventSink itself) keeps tools off the event
    # vocabulary — the executor owns event shape (引擎纯化), exactly like ``on_escalate``.
    on_note: Callable[[TeamNote], None] | None = None
    # 升级实时可见 (escalation 实时 SSE): a run-scoped live channel for the worker-only
    # ``escalate`` tool to surface its escalation the INSTANT it is raised, called with
    # ``(question, assumption, blocking, kind)`` — kind is normal/scope/dep. Set per
    # delegated-worker node by ``build_agent_executor`` (it closes over the run's EventSink
    # + run/agent id to emit ``escalation_raised``); ``None`` for the CEO / tests — the tool
    # keeps working (escalate 非阻塞), the live banner is simply skipped, and the durable
    # record still rides the transcript into ``RunState.escalations``. A narrow callback
    # (not the EventSink itself) keeps tools off the event vocabulary — the executor owns
    # event shape (引擎纯化).
    on_escalate: Callable[[str, str, bool, str], None] | None = None
    # 阻塞式求决策 (escalate blocking=true): the per-run channel that suspends this worker
    # for the user when it hits a「只有用户能定、且猜错就作废」fork. Set per delegated-worker
    # node by ``build_agent_executor`` (closes over the interaction bridge + EventSink +
    # run/agent id); ``None`` for the CEO / tests / unarmed turns — then ``escalate`` stays
    # non-blocking (its existing behaviour). The tool owns the decision (whether to block,
    # the assumption fallback); this channel owns the mechanism (cap / suspend / events /
    # RunState recording) so the tool stays off the event vocabulary (引擎纯化).
    escalation: EscalationChannel | None = None
    # AI 协作白板 (AI协作白板.md §六 M2): the per-run channel that lets ``board_ops`` apply
    # structured ops to the user's open whiteboard canvas via the bound desktop. Set per
    # run by the assembler ONLY when the conversation is bound to a board (a 白板会话);
    # ``None`` for every ordinary chat / worker / test — then ``board_ops`` returns a clean
    # "not on a board" error instead of touching anything. The channel owns the mechanism
    # (suspend / emit / await the desktop); the tool owns only the op→result mapping (引擎纯化).
    board_channel: BoardChannel | None = None
    # Desktop Client Tools: per-run channel for ``desktop_notify`` + Host ops.
    # Set when the desktop client is online (local workspace **or** cloud +
    # ``desktop_online``) so tools can backfill via ClientTool SSE; ``None`` when
    # no desktop is attached.
    desktop_channel: DesktopClientChannel | None = None
    # Background process ops (terminal tool): the same ``workspace_op_required`` channel
    # LocalWorkspace already uses for file/execute ops. Reused from LocalWorkspace when
    # present; for sidecar (ServerWorkspace location=local) a channel is built so process
    # ops still leave the short-lived sidecar and land in the desktop main process.
    # ``None`` on cloud-only runs — ``terminal`` is not registered there.
    workspace_channel: WorkspaceChannel | None = None
    # AI 协作白板 (AI协作白板.md §九.4): the optional vision port ``board_read`` uses to turn a
    # rasterized hand-drawn / screenshot selection into text (DeepSeek V4 无多模态, so 读图 is a
    # separate model). Wired by ``build_vision_reader`` when ``VISION_API_KEY`` is set; ``None``
    # without a key (and on workers / tests) ⇒ ``board_read`` returns a clean「读图能力未配置」
    # error instead of pretending. Set here (CEO, not workers) alongside ``board_channel``.
    vision_reader: VisionReader | None = None
    # AI 协作白板 (AI协作白板.md §九.4 Gap ②): a turn-level sink ``board_read`` appends a priced
    # vision sub-call ledger row (:class:`~agentcore.runtime.costing.RunCost`) to. The vision
    # model (qwen-vl) ≠ the run's DeepSeek, so the spend can't fold into the run usage; it
    # becomes its own ``role=vision`` row the pipeline collects into the turn's ``cost_runs``
    # (→ cost_events on the turn's message_id). Set once on the pipeline's base context and
    # shared by every derived run via ``replace`` (a plain list, shared by reference); only
    # ``board_read`` writes it, only in a 白板会话. ``None`` everywhere else (tests / no board).
    cost_sink: list[RunCost] | None = None
    # 项目共享工作区 (folder 绑定): True ⇒ CEO overview / worker manifest 用稀疏清单
    # (附件 + 少量最近触达 + 「另有 N 个」)；False ⇒ 裸聊 scratch，非附件文件照常列入。
    # Set on the pipeline base context from ``folder_id``; inherited by workers via
    # ``dataclasses.replace``. Defaults False for tests / evals / 裸聊.
    shared_workspace: bool = False
    # 工具执行阶段进度 (联网搜索前端展示优化): a narrow callback a long-running tool fires to report
    # a coarse EXECUTION phase (web_search → "querying" 正在检索 / "queued" 排队中 / "fallback"
    # 改用备用引擎) so the waiting UI shows a live, honest state instead of a dead spinner. Called
    # with the phase token ONLY; the executor (``execute_tools``) owns event shape — it closes over
    # this call's tool_call_id / tool_name / run_id and emits the
    # transport-only ``tool_use_progress``
    # (引擎纯化, exactly like ``on_note`` / ``on_escalate``). ``None`` for call sites without a live
    # sink (tests / evals) — the tool simply skips the ping.
    on_phase: Callable[[str], None] | None = None
    # 工具执行流式进度 (code_execute 前端展示优化): a narrow callback a long-running tool fires
    # to push incremental output (``code_execute`` → phase ``"output"`` + ``{stream, chunk}``) so
    # the waiting UI shows live stdout/stderr instead of a bare spinner. Called with ``(phase, data)``
    # where ``data`` is an optional dict merged into the transport-only ``tool_use_progress`` payload
    # by the executor (引擎纯化, twin of ``on_phase``). ``None`` for call sites without a live sink
    # (tests / evals) — the tool simply skips the ping.
    on_progress: Callable[[str, dict[str, Any] | None], None] | None = None
    # 检索预算 (提案 A1): per-run counter for ``web_search`` / ``read_url``. Wired by the
    # worker executor from ``RunSpec.retrieval_budget``; ``None`` for CEO / tests without a
    # budget (no enforcement). Shared by reference across ``replace`` so parallel tool
    # calls in one run share one reserve/refund lock. Orthogonal to LoopController.
    retrieval_budget: RetrievalBudgetState | None = None
    # Per-run web_search posture (structured run signal — never prompt text).
    # ``""`` = default research; ``"debate_evidence"`` = debate investigator / debater
    # speech research (reject weak-tier + mall/dict/hospital-encyclopedia). Wired from
    # ``RunSpec.search_policy`` by the worker executor.
    search_policy: str = ""
    # Same-round streamed prose length (chars) before tool calls. Set by tool_round so
    # ``handoff`` can log ``body_chars`` (deliverable) separately from ``chars`` (summary).
    # ``None`` when unset (CEO / tests / tools that do not need it).
    round_content_chars: int | None = None
    # 成篇交接：有下游依赖时 handoff 须带非空交付正文（或已落盘 prose）；由 worker
    # executor 按 DAG 写入。False/默认 = 叶节点或不强制。
    handoff_requires_body: bool = False
    # True when this run already landed at least one file (file_write / append /
    # str_replace) on the *current* ToolContext object. Best-effort same-ctx
    # signal only — ``dataclasses.replace`` drops this bool. Handoff / executor
    # body-floor exemption must read ``landed_artifact_kinds`` (prose) instead.
    has_landed_files: bool = False
    # Wave3 B：本 run 内各相对路径成功 ``file_read`` 次数（共享可变 dict；
    # ``dataclasses.replace`` 浅拷贝仍指向同一计数器）。超 ``FILE_READ_SAME_PATH_MAX``
    # 时工具拒绝重复读。
    file_read_counts: dict[str, int] = field(default_factory=dict)
    # R1 tool_clear 双态：engine 在每轮 ``execute_tools`` 前对 canonical 再跑
    # ``project_cleared_window`` 后写入。``None`` = 未同步（单测/旁路）→ 视为正文仍在，
    # 保持纯 ``FILE_READ_SAME_PATH_MAX`` 硬顶。``frozenset`` = 投影窗内仍有 verbatim
    # ``file_read`` 正文的 path 集合（空集 = 该窗内全部已清）。
    file_read_verbatim_paths: frozenset[str] | None = None
    # R1：每 path 每 run sticky「已授再读」标记（共享可变 dict；值恒 True）。
    # 一旦发出，清窗再次发生也不二次授额。
    file_read_reread_issued: dict[str, bool] = field(default_factory=dict)
    # R1：各 path 剩余再读次数（共享可变 dict）。engine 授额时写入；成功再读时工具扣减。
    file_read_reread_remaining: dict[str, int] = field(default_factory=dict)
    # Artifact-first Writing：本 execution 已落盘 path → ``skeleton`` | ``prose``（共享可变
    # dict；``dataclasses.replace`` 浅拷贝与 ``file_read_counts`` 同模式）。``prose`` = 成篇
    # 正文，同 path 后续 ``file_append`` 硬拒。配 ``landed_artifact_authors``：首次落盘
    # 该 path 的 ``agent_id``（归属/可观测；作者与读者 ``file_read`` 走同一
    # ``FILE_READ_SAME_PATH_MAX``，无身份硬闸）。
    landed_artifact_kinds: dict[str, Literal["skeleton", "prose"]] = field(
        default_factory=dict
    )
    # path → 首次落盘该 path 的 ``agent_id``（共享可变 dict，与 kinds 同生命周期）。
    landed_artifact_authors: dict[str, str] = field(default_factory=dict)
    # 冷启动探索幕未完成（本回合有 explore 原因且尚未成功 ``update_project_profile``）。
    # assemble 在注入 ``<cold_start_explore>`` 时置 True；画像写入成功后清 False。
    # Delegate 读此旗标：抑制 form/artifacts→files_written 推断，并硬拒 form=files/artifacts。
    # 与 deep_research_auto_debate_count 同模式——CEO base ToolContext 上就地翻转。
    cold_start_explore_pending: bool = False


@dataclass
class ToolResult:
    """Result of a tool execution.

    ``effect`` steers the ReAct loop and is the ONLY signal the engine acts on to
    decide whether the turn continues — never the tool's name or category (引擎纯化,
    设计 §8.5). The default ``ToolEffect.CONTINUE`` feeds ``output`` back to the
    model and loops; a terminal effect (``HANDOFF`` / ``INTERACT``) stops the loop
    because the tool already produced the turn's final user-facing answer, carried
    in ``final_text`` (so the model does not generate a second, duplicate reply).
    The CEO ``ask_user`` checkpoint sets ``INTERACT`` on a "stop" decision — its
    closing note is the ``final_text`` — so the turn ends gracefully in-band rather
    than via an SSE abort; ``delegate`` stays ``CONTINUE`` (its workers' products
    return to the CEO loop). ``final_text`` is persisted but NOT re-emitted and is
    exempt from ``output`` truncation (which only guards the model-facing
    ``output`` string).

    ``output_limit`` overrides the default model-facing truncation budget for the
    ``output`` string. Most tools leave it ``None`` (4000 chars); read-heavy tools
    (e.g. ``read_url``) raise it so a full page body is not truncated into invalid
    JSON. An over-budget output is HEAD+TAIL trimmed (``core.text.truncate_head_tail``)
    so trailing details survive rather than being head-chopped. ``final_text`` is never
    subject to this cap.

    ``citations`` carries structured web sources a tool consulted (each a
    ``{url, title, snippet, site}`` dict). Research tools (``web_search`` /
    ``read_url``) populate it so the engine can aggregate per-turn sources and the
    client can render source cards under the answer; non-web tools leave it
    ``None``. The dicts themselves are UI metadata; the engine additionally
    assigns each source a canonical number (its card index) and folds *that
    number* back into the tool's model-facing output, so the model can cite by a
    card-aligned number (see ``engine._annotate_tool_citations``).

    ``display`` is an OPTIONAL render-oriented payload, distinct from the
    model-facing ``output`` string: a tool that has a richer client rendering than
    plain text (``web_search`` → result cards, ``read_url`` → source card + body
    preview, ``code_execute`` → a terminal stdout/stderr view) populates it, and
    the desktop renders per tool — falling back to the ``output`` text when
    absent (工具结果富渲染). It rides the ``tool_use_end`` event → the process
    timeline / journal → the client (size-capped on the way,
    ``events._cap_display``), so a live turn and its reloaded twin render the
    same card. 形状是数据不是模式: the frontend keys the renderer off the tool
    name, so ``display`` is just the data that name's view needs (most tools
    leave it ``None``; edits like ``str_replace`` need nothing here — the client
    derives their diff from the call ``arguments`` it already has).
    """

    tool_call_id: str
    success: bool
    output: str
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    effect: ToolEffect = ToolEffect.CONTINUE
    final_text: str | None = None
    output_limit: int | None = None
    citations: list[dict[str, Any]] | None = None
    display: dict[str, Any] | None = None
    # 参数契约拒绝 (零成本可修正的参数打回): a deterministic argument-contract rejection at
    # the tool boundary (e.g. web_search A3 query 过长/过多) whose ``error`` already carries a
    # concrete fix hint. It is an honest failed call for the model, but must NOT feed the
    # run-scoped tool-failure circuit breaker (warn/disable) — a research worker that fans out
    # several over-long queries in one round would otherwise burn the disable threshold before
    # ever seeing the「改用 2–4 个核心词重试」tip and permanently lose the tool. The engine
    # forwards this onto the ToolAttempt (loop_controller), which skips the cumulative breaker
    # tally; every other governance signal (REPEATED_FAILURE window, unproductive early-stop,
    # round recording) still treats it as a normal failure. Twin of ``ToolAttempt.policy_failure``
    # (upstream policy/environment block) but for a self-correctable参数打回, not a refusal.
    contract_failure: bool = False

    _MAX_OUTPUT_LEN = 4000

    @property
    def is_terminal(self) -> bool:
        """Whether this result ends the turn (any non-``CONTINUE`` effect)."""
        return self.effect is not ToolEffect.CONTINUE

    def __post_init__(self):
        limit = self.output_limit if self.output_limit is not None else self._MAX_OUTPUT_LEN
        if len(self.output) > limit:
            # HEAD+TAIL, not a head-only chop: an agentic CEO leans on grep / file_read,
            # whose hits / numbers / 法条编号 often sit at the END — a head cut drops them
            # silently. Same primitive the dep-injection / compaction paths already use.
            self.output = truncate_head_tail(self.output, limit)


class Tool(Protocol):
    """Unified protocol for tool implementations."""

    @property
    def schema(self) -> ToolSchema:
        """Return tool metadata (name, description, parameters JSON Schema)."""
        ...

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the tool with given arguments and context."""
        ...


def tool_schema_to_openai_format(schema: ToolSchema) -> dict:
    """Convert a ToolSchema to the OpenAI function calling format."""
    return {
        "type": "function",
        "function": {
            "name": schema.name,
            "description": schema.description,
            "parameters": schema.parameters,
        },
    }

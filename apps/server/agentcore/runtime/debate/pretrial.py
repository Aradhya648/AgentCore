"""庭前取证与辩方团队（辩论编排设计.md §二之二）。

开赛后、首轮立论前的固有阶段：主辩点单 → 主持人代派取证员 → 并行取证 → 定焦开辩。

边界（就地否决）：
- 取证员由主持人代派；``parent_run_id`` 指向本方主辩；与辩手同 depth 只读叶子
- 不给辩手 ``delegate``、不动 ``MAX_DELEGATION_DEPTH``
- ``thorough=False`` 不带队（秒过）；预算对称；台账强制汇流
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from agentcore.core.logging import get_logger
from agentcore.runtime.costing import ROLE_ARENA
from agentcore.runtime.debate.constants import (
    DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET,
    INVESTIGATOR_TOOLS,
    MAX_EVIDENCE_ORDER_TASKS,
    MAX_INVESTIGATORS_PER_SIDE,
)
from agentcore.runtime.debate.moderator_common import _parse_json_object
from agentcore.workspace.stage_dirs import RESEARCH_DIR

if TYPE_CHECKING:
    from agentcore.runtime.debate.evidence_ledger import EvidenceLedger
    from agentcore.runtime.debate.moderator_common import CompleteJson
    from agentcore.runtime.debate.types import DebateConfig, DebateSide
    from agentcore.tools.builtin.debate.tool import DebateTool

logger = get_logger(__name__)

OrderSource = Literal["debater", "auto", "empty"]
SkipReason = Literal["", "fast", "dossier_sufficient"]

_ORDER_SYSTEM = (
    "你是辩论主持人，代各方主辩产出【庭前取证任务单】。"
    "每方至多 3 条；带着该方立场找证据，只补案卷未覆盖的增量，禁重搜已覆盖项。"
    "案卷已充分时可给该方空数组。严格只输出要求的 JSON。"
)


@dataclass(frozen=True)
class EvidenceTask:
    """一条取证任务（主辩点单条目）。"""

    query: str
    purpose: str = ""

    def to_wire(self) -> dict[str, str]:
        out = {"query": self.query}
        if self.purpose:
            out["purpose"] = self.purpose
        return out


@dataclass
class SideOrder:
    side_key: str
    tasks: list[EvidenceTask] = field(default_factory=list)
    source: OrderSource = "empty"

    def to_wire(self) -> dict[str, Any]:
        return {
            "side_key": self.side_key,
            "tasks": [t.to_wire() for t in self.tasks],
            "source": self.source,
        }


@dataclass
class InvestigatorOutcome:
    side_key: str
    run_id: str
    parent_run_id: str
    ok: bool
    notes: str = ""
    task_query: str = ""

    def to_wire(self) -> dict[str, Any]:
        return {
            "side_key": self.side_key,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "ok": self.ok,
            "task_query": self.task_query,
        }


@dataclass
class PretrialResult:
    skipped: bool = False
    skip_reason: SkipReason = ""
    orders: list[SideOrder] = field(default_factory=list)
    investigators: list[InvestigatorOutcome] = field(default_factory=list)
    fallback_self_search: bool = False
    evidence_ready: bool = False
    debater_run_ids: dict[str, str] = field(default_factory=dict)

    def to_completed_payload(self) -> dict[str, Any]:
        status = "skipped" if self.skipped else (
            "degraded" if self.fallback_self_search else "done"
        )
        return {
            "status": status,
            "skip_reason": self.skip_reason or None,
            "orders": [o.to_wire() for o in self.orders],
            "investigators": [i.to_wire() for i in self.investigators],
            "fallback_self_search": self.fallback_self_search,
            "evidence_ready": self.evidence_ready,
        }


def parse_order_tasks(raw: Any) -> list[EvidenceTask]:
    """解析单方任务列表；不合规条目丢弃；硬顶 ``MAX_EVIDENCE_ORDER_TASKS``。"""
    if not isinstance(raw, list):
        return []
    out: list[EvidenceTask] = []
    for item in raw:
        if isinstance(item, str):
            q = item.strip()
            if q:
                out.append(EvidenceTask(query=q[:200]))
        elif isinstance(item, Mapping):
            q = str(item.get("query") or item.get("q") or "").strip()
            if not q:
                continue
            purpose = str(item.get("purpose") or item.get("why") or "").strip()[:120]
            out.append(EvidenceTask(query=q[:200], purpose=purpose))
        if len(out) >= MAX_EVIDENCE_ORDER_TASKS:
            break
    return out


def auto_order_sheet(side: DebateSide, motion: str) -> list[EvidenceTask]:
    """点单降级：按 motion + stance 自动派单（至多 2 条，守对称上限）。"""
    stance = (side.stance or side.name or side.key).strip()
    topic = (motion or "").strip() or "本场辩题"
    return [
        EvidenceTask(
            query=f"{topic}：支持「{stance}」的关键事实与权威来源",
            purpose="立论底料",
        ),
        EvidenceTask(
            query=f"{topic}：反驳「{stance}」常见攻击点的反证或限定条件",
            purpose="预判攻防",
        ),
    ][:MAX_INVESTIGATORS_PER_SIDE]


def symmetric_investigator_count(orders: Sequence[SideOrder]) -> int:
    """各方取证员数量：取各方任务数的上确界，夹在 1..MAX 之间；全空 → 0。"""
    lengths = [len(o.tasks) for o in orders]
    if not lengths or max(lengths) == 0:
        return 0
    return max(1, min(MAX_INVESTIGATORS_PER_SIDE, max(lengths)))


def pad_orders_for_symmetry(
    orders: list[SideOrder],
    *,
    n: int,
    config: DebateConfig,
) -> list[SideOrder]:
    """不足 n 条的方用 auto 补齐，保证预算对称。"""
    by_key = {s.key: s for s in config.sides}
    padded: list[SideOrder] = []
    for order in orders:
        tasks = list(order.tasks)
        source: OrderSource = order.source
        if len(tasks) < n:
            side = by_key.get(order.side_key)
            if side is not None:
                for auto in auto_order_sheet(side, config.motion):
                    if len(tasks) >= n:
                        break
                    if all(auto.query != t.query for t in tasks):
                        tasks.append(auto)
            source = "auto" if order.source == "empty" else order.source
            if order.source == "debater" and len(order.tasks) < n:
                source = "debater"  # 仍保留主辩点单来源标记；补齐不改写
        padded.append(
            SideOrder(side_key=order.side_key, tasks=tasks[:n], source=source)
        )
    return padded


def parse_orders_payload(
    data: Mapping[str, Any],
    sides: Sequence[DebateSide],
) -> dict[str, list[EvidenceTask]]:
    """从主持人 JSON 抽各方任务；缺方 → 空列表。"""
    raw_orders = data.get("orders")
    if not isinstance(raw_orders, Mapping):
        # 兼容顶层即 {side_key: [...]}
        raw_orders = data
    out: dict[str, list[EvidenceTask]] = {}
    for side in sides:
        chunk = raw_orders.get(side.key) if isinstance(raw_orders, Mapping) else None
        out[side.key] = parse_order_tasks(chunk)
    return out


async def collect_order_sheets(
    complete_json: CompleteJson,
    config: DebateConfig,
) -> list[SideOrder]:
    """主辩点单：主持人一次结构化调用代各方产出任务单；失败 → 各方 auto。"""
    dossier = (config.research_dossier_index or "").strip()
    sides_block = "\n".join(
        f"- {s.key}（{s.name}）：立场「{s.stance}」" for s in config.sides
    )
    user = (
        f"辩题：{config.motion}\n"
        f"各方：\n{sides_block}\n"
    )
    if dossier:
        user += f"\n已有案卷索引（只补增量、可空单）：\n{dossier[:3000]}\n"
    user += (
        "\n输出 JSON：{\"orders\": {\"<side_key>\": "
        "[{\"query\": \"检索问句\", \"purpose\": \"用途\"}, ...]}}\n"
        f"每方 0–{MAX_EVIDENCE_ORDER_TASKS} 条。"
    )
    try:
        data = await complete_json(_ORDER_SYSTEM, user, "pretrial_orders")
    except Exception:  # noqa: BLE001
        logger.exception("debate.pretrial.order_llm_failed")
        data = {}
    if not isinstance(data, dict) or not data:
        return [
            SideOrder(
                side_key=s.key,
                tasks=auto_order_sheet(s, config.motion),
                source="auto",
            )
            for s in config.sides
        ]
    parsed = parse_orders_payload(data, config.sides)
    # 任一方解析结果都缺且 JSON 无 orders 键 → 整场降级 auto
    if "orders" not in data and not any(parsed.values()):
        return [
            SideOrder(
                side_key=s.key,
                tasks=auto_order_sheet(s, config.motion),
                source="auto",
            )
            for s in config.sides
        ]
    orders: list[SideOrder] = []
    for side in config.sides:
        tasks = parsed.get(side.key) or []
        if tasks:
            orders.append(SideOrder(side_key=side.key, tasks=tasks, source="debater"))
        else:
            # 空单合法（案卷充分）；不强制 auto——对称补齐在 pad 阶段按 n 决定
            orders.append(SideOrder(side_key=side.key, tasks=[], source="empty"))
    return orders


def debater_run_id(moderator_run_id: str, side_key: str) -> str:
    """庭前即铸主辩 run_id，与首轮立论 ``_r1_{side}`` 同构，供取证员 parent。"""
    return f"{moderator_run_id}_r1_{side_key}"


def investigator_run_id(moderator_run_id: str, side_key: str, index: int) -> str:
    return f"{moderator_run_id}_inv_{side_key}_{index}"


def investigator_delivery_notes(state: Any) -> str:
    """取证员有效交付文本：正文优先；空正文时回落 handoff summary / key_points。

    对齐 worker 交付契约（``check_contract`` 基线：content / files / debrief 任一即可）。
    取证员工具集只读、无写盘——笔记通常在正文；若模型只交了 handoff 摘要亦算有效。
    """
    if state is None:
        return ""
    text = str(getattr(state, "content", "") or "").strip()
    if text:
        return text
    debrief = getattr(state, "debrief", None) or {}
    if not isinstance(debrief, Mapping):
        return ""
    summary = str(debrief.get("summary") or "").strip()
    if summary:
        return summary
    points = debrief.get("key_points") or []
    if isinstance(points, (list, tuple)):
        lines = [f"- {str(p).strip()}" for p in points if str(p).strip()]
        if lines:
            return "\n".join(lines)
    return ""


def investigator_delivery_ok(state: Any) -> bool:
    """COMPLETED 且（正文或 handoff 摘要）非空 → 有效交付。"""
    from agentcore.runtime.runs import RunPhase

    if state is None:
        return False
    if getattr(state, "phase", None) is not RunPhase.COMPLETED:
        return False
    return bool(investigator_delivery_notes(state))


def investigator_task_payload(
    *,
    config: DebateConfig,
    side: DebateSide,
    task: EvidenceTask,
    index: int,
    retrieval_budget: int,
    turn_model: str = "",
) -> dict[str, Any]:
    """取证员 task：只检索/只读，交付证据笔记，无发言、无成稿。"""
    dossier = (config.research_dossier_index or "").strip()
    dossier_line = (
        f"已有案卷索引：\n{dossier[:2000]}\n只补增量，禁重搜已覆盖项。\n"
        if dossier
        else ""
    )
    purpose = f"（用途：{task.purpose}）" if task.purpose else ""
    body = (
        f"你是「{side.name}」队的取证员（不发言、不写辩词）。\n"
        f"本方立场：{side.stance}\n"
        f"辩题：{config.motion}\n"
        f"{dossier_line}"
        f"取证任务：{task.query}{purpose}\n\n"
        "用 web_search / read_url / file_read 取证；【证据笔记写进正文交付】："
        "条目化事实 + 来源 URL/标题；关键事实标【已核实·#eN】（沿用工具注解 id）。"
        "勿只靠 handoff 摘要、勿尝试写盘（工具集只读）。\n"
        "来源策略：优先判决书/裁判文书、权威媒体与官方通报；"
        "与辩题无关的工具站、商城、词典条目不算证据。\n"
        "禁止正式发言、禁止收工汇报、禁止为对方写剧本。"
    )
    payload: dict[str, Any] = {
        "id": f"inv_{side.key}_{index}",
        "role": f"取证·{side.name}",
        "task": body,
        "objective": f"为「{side.name}」取证：{task.query[:80]}",
        "tools": list(INVESTIGATOR_TOOLS),
        # 离开 debate: 参与者命名空间——前端 isDebateParticipant 只认辩形态白名单；
        # 若挂 debate:* 且 parent=主辩，会把主辩晋升独立 debateUnits → ELK 假分带。
        "group": f"pretrial:investigators:{side.key}",
        "retrieval_budget": retrieval_budget,
        # 结构化检索姿态：庭前取证收紧（weak / 商城词典硬剔），不靠 prompt 触发。
        "search_policy": "debate_evidence",
        "side_key": side.key,
        "evidence_ledger_check": True,
        # 无成稿：检索笔记即交付物
        "research_then_draft": False,
    }
    from agentcore.runtime.debate.models import side_route_model

    route = side_route_model(side, turn_model=turn_model)
    if route:
        payload["model"] = route
    return payload


async def _persist_investigator_notes(
    tool: DebateTool,
    *,
    side: DebateSide,
    index: int,
    notes: str,
    ledger: EvidenceLedger,
) -> None:
    """证据笔记落 ``AgentCore/文档/research/`` + 提交场级台账（side_key=本方）。"""
    text = (notes or "").strip()
    if not text:
        return
    from agentcore.runtime.debate.evidence_ledger import extract_ledger_ids

    cited = extract_ledger_ids(text)
    # 检索期命中在 research_proxy 核内；按笔记引用 + deep_read 提交进 wire。
    ledger.commit_research(note_cited_ids=cited)
    if not cited:
        ledger.register(
            url="",
            title=f"庭前取证·{side.name}·{index + 1}",
            snippet=text[:240],
            site=side.name,
            side_key=side.key,
            tier="unknown",
            dossier_path=f"{RESEARCH_DIR}/庭前·{side.name}·{index + 1}.md",
            dossier_label=side.name,
        )
    else:
        for eid in cited:
            entry = ledger.get(eid)
            if entry is None:
                continue
            ledger.register(
                url=str(entry.get("url") or ""),
                title=str(entry.get("title") or ""),
                snippet=str(entry.get("snippet") or ""),
                site=str(entry.get("site") or ""),
                side_key=side.key,
                tier=str(entry.get("tier") or "unknown"),
            )
    backend = tool._base_tool_context.backend
    path = f"{RESEARCH_DIR}/庭前·{side.name}·{index + 1}.md"
    try:
        await backend.write(path, text)
    except Exception:  # noqa: BLE001
        logger.exception("debate.pretrial.persist_notes_failed", path=path)


async def run_investigators(
    tool: DebateTool,
    *,
    execution_id: str,
    moderator_run_id: str,
    config: DebateConfig,
    orders: Sequence[SideOrder],
    debater_ids: Mapping[str, str],
    retrieval_budget: int = DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> list[InvestigatorOutcome]:
    """并行派取证员：同 depth 叶子、parent=本方主辩。"""
    from agentcore.runtime.runs import (
        BatchMetrics,
        RunPhase,
        WaveScheduler,
        build_agent_executor,
        build_run_plan,
        resolve_max_parallel,
    )

    sides_by_key = {s.key: s for s in config.sides}
    tasks_raw: list[dict[str, Any]] = []
    meta: list[tuple[str, int, str, EvidenceTask]] = []  # side, idx, parent, task
    turn_model = tool._profile_set.model

    for order in orders:
        side = sides_by_key.get(order.side_key)
        if side is None:
            continue
        parent = debater_ids.get(order.side_key) or debater_run_id(
            moderator_run_id, order.side_key
        )
        for idx, task in enumerate(order.tasks):
            tasks_raw.append(
                investigator_task_payload(
                    config=config,
                    side=side,
                    task=task,
                    index=idx,
                    retrieval_budget=retrieval_budget,
                    turn_model=turn_model,
                )
            )
            meta.append((side.key, idx, parent, task))

    if not tasks_raw:
        return []

    valid_tools = {s.name for s in tool._tools.list_all()}
    plan, errors = build_run_plan(
        tasks_raw,
        valid_tools=valid_tools,
        id_prefix=f"{moderator_run_id}_inv",
        parent_run_id=moderator_run_id,  # 稍后按节点覆写为各方主辩
        depth=tool._depth + 2,
    )
    if errors or not plan.nodes:
        logger.warning("debate.pretrial.investigators_build_failed", errors=errors)
        return [
            InvestigatorOutcome(
                side_key=sk,
                run_id=investigator_run_id(moderator_run_id, sk, idx),
                parent_run_id=parent,
                ok=False,
                task_query=task.query,
            )
            for sk, idx, parent, task in meta
        ]

    plan.nodes = [
        replace(
            node,
            run_id=investigator_run_id(moderator_run_id, sk, idx),
            agent_id=investigator_run_id(moderator_run_id, sk, idx),
            parent_run_id=parent,
            role=f"取证·{sides_by_key[sk].name}",
            # builder 不解析 task 级 retrieval_budget；内部取证额度在此补写。
            retrieval_budget=retrieval_budget,
        )
        for node, (sk, idx, parent, _task) in zip(plan.nodes, meta, strict=False)
    ]

    from agentcore.runtime.debate.rounds import debater_plan_event

    tool._sink.emit(debater_plan_event(tool, execution_id, moderator_run_id, plan))

    worker_gate = (
        tool._approval_gate if tool._base_tool_context.backend.location == "local" else None
    )
    executor = build_agent_executor(
        plan=plan,
        llm=tool._llm,
        tools=tool._tools,
        sink=tool._sink,
        base_tool_context=tool._base_tool_context,
        profile_set=tool._profile_set,
        cost_role=ROLE_ARENA,
        system_prompt=tool._system_prompt,
        user_message=tool._user_message,
        execution_id=execution_id,
        approval_gate=worker_gate,
        collaboration=False,
        evidence_ledger=tool._evidence_ledger,
    )
    scheduler = WaveScheduler(tool._max_parallel or resolve_max_parallel())
    batch_metrics: list[BatchMetrics] = []
    from agentcore.runtime.events import run_skipped

    # side/idx/parent/task keyed by final run_id for per-node completion.
    meta_by_rid = {
        investigator_run_id(moderator_run_id, sk, idx): (sk, idx, parent, task)
        for sk, idx, parent, task in meta
    }
    nodes_by_rid = {n.run_id: n for n in plan.nodes}
    outcomes_by_rid: dict[str, InvestigatorOutcome] = {}

    async def _on_investigator_done(run_id: str, state: Any) -> None:
        """每员完工即落盘笔记、登记台账、上报 progress（含台账计数增量）。"""
        info = meta_by_rid.get(run_id)
        node = nodes_by_rid.get(run_id)
        if info is None or node is None:
            return
        sk, idx, parent, task = info
        tool._acc.add_run(node, state, parent_run_id=parent, role=ROLE_ARENA)
        notes = investigator_delivery_notes(state)
        ok = investigator_delivery_ok(state)
        if ok:
            await _persist_investigator_notes(
                tool,
                side=sides_by_key[sk],
                index=idx,
                notes=notes,
                ledger=tool._evidence_ledger,
            )
        outcomes_by_rid[run_id] = InvestigatorOutcome(
            side_key=sk,
            run_id=run_id,
            parent_run_id=parent,
            ok=ok,
            notes=notes if ok else "",
            task_query=task.query,
        )
        if on_progress is not None:
            await on_progress(
                {
                    "side_key": sk,
                    "investigator_run_id": run_id,
                    "parent_run_id": parent,
                    "status": "completed" if ok else "failed",
                    "evidence_ledger_count": len(tool._evidence_ledger),
                }
            )

    t0 = time.monotonic()
    results = await scheduler.run(
        plan,
        executor,
        on_skipped=lambda rid, aid, reason: tool._sink.emit(
            run_skipped(rid, aid, reason=reason)
        ),
        on_node_done=_on_investigator_done,
        metrics_sink=batch_metrics,
    )
    logger.info(
        "debate.pretrial.investigators_done",
        nodes=len(plan.nodes),
        wall_ms=int((time.monotonic() - t0) * 1000),
        completed=sum(
            1
            for n in plan.nodes
            if (results.get(n.run_id) and results[n.run_id].phase is RunPhase.COMPLETED)
        ),
    )

    # Stable order matching plan.nodes / meta（回调可能乱序完成）。
    outcomes: list[InvestigatorOutcome] = []
    for node, (sk, idx, parent, task) in zip(plan.nodes, meta, strict=False):
        outcome = outcomes_by_rid.get(node.run_id)
        if outcome is None:
            state = results.get(node.run_id)
            if state is not None:
                tool._acc.add_run(node, state, parent_run_id=parent, role=ROLE_ARENA)
            notes = investigator_delivery_notes(state)
            ok = investigator_delivery_ok(state)
            if ok:
                await _persist_investigator_notes(
                    tool,
                    side=sides_by_key[sk],
                    index=idx,
                    notes=notes,
                    ledger=tool._evidence_ledger,
                )
            outcome = InvestigatorOutcome(
                side_key=sk,
                run_id=node.run_id,
                parent_run_id=parent,
                ok=ok,
                notes=notes if ok else "",
                task_query=task.query,
            )
        outcomes.append(outcome)
    return outcomes


def declare_debater_skeleton(
    tool: DebateTool,
    *,
    execution_id: str,
    moderator_run_id: str,
    config: DebateConfig,
) -> dict[str, str]:
    """庭前声明主辩节点（未执行立论），供取证员 parent_run_id 嵌套。

    首轮 ``first_round`` 会以同 id 再声明并执行；前端 run_plan dedupe。
    """
    from agentcore.runtime.debate.events import debate_act_payload, run_payload, side_card
    from agentcore.runtime.events import run_plan
    from agentcore.runtime.runs.types import RunSpec

    ids: dict[str, str] = {}
    agents: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for idx, side in enumerate(config.sides):
        rid = debater_run_id(moderator_run_id, side.key)
        ids[side.key] = rid
        stance = ""
        if config.form.value == "debate" and len(config.sides) == 2:
            stance = "pro" if idx == 0 else "con"
        node = RunSpec(
            run_id=rid,
            agent_id=rid,
            task=f"【庭前点单】代表「{side.name}」准备取证任务",
            role=side.name,
            parent_run_id=moderator_run_id,
            depth=tool._depth + 2,
            group=f"debate:{config.form.value}",
            round=1,
            stance=stance,
            side_key=side.key,
            thinking=True,
        )
        agents.append(side_card(tool, node))
        runs.append(run_payload(node))

    host_message_id = getattr(tool, "_debate_host_message_id", None)
    tool._sink.emit(
        run_plan(
            execution_id=execution_id,
            plan_type="debate",
            task_summary="庭前取证·主辩点单",
            agents=agents,
            runs=runs,
            host_message_id=host_message_id,
            act=debate_act_payload(tool),
        )
    )
    return ids


async def run_pretrial_phase(
    tool: DebateTool,
    *,
    execution_id: str,
    moderator_run_id: str,
    config: DebateConfig,
    complete_json: CompleteJson,
    on_started: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_orders: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_completed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> PretrialResult:
    """庭前阶段编排入口。"""
    base_payload = {
        "execution_id": execution_id,
        "moderator_run_id": moderator_run_id,
        "thorough": bool(config.policy.thorough),
        "sides": [{"key": s.key, "name": s.name} for s in config.sides],
    }

    # 快速档：不带队秒过
    if not config.policy.thorough:
        result = PretrialResult(skipped=True, skip_reason="fast")
        if on_started is not None:
            await on_started({**base_payload, "skip_reason": "fast"})
        if on_completed is not None:
            await on_completed({**base_payload, **result.to_completed_payload()})
        return result

    if on_started is not None:
        await on_started(base_payload)

    orders = await collect_order_sheets(complete_json, config)
    n = symmetric_investigator_count(orders)
    if n == 0:
        result = PretrialResult(
            skipped=True,
            skip_reason="dossier_sufficient",
            orders=orders,
        )
        if on_orders is not None:
            await on_orders(
                {
                    **base_payload,
                    "orders": [o.to_wire() for o in orders],
                    "investigator_count_per_side": 0,
                }
            )
        if on_completed is not None:
            await on_completed({**base_payload, **result.to_completed_payload()})
        return result

    orders = pad_orders_for_symmetry(orders, n=n, config=config)
    # 对称后仍可能某方空（极端）——再 pad 保证每方恰好 n
    for i, order in enumerate(orders):
        if len(order.tasks) < n:
            side = next(s for s in config.sides if s.key == order.side_key)
            extra = auto_order_sheet(side, config.motion)
            tasks = list(order.tasks)
            for t in extra:
                if len(tasks) >= n:
                    break
                tasks.append(t)
            orders[i] = SideOrder(
                side_key=order.side_key, tasks=tasks[:n], source=order.source
            )

    if on_orders is not None:
        await on_orders(
            {
                **base_payload,
                "orders": [o.to_wire() for o in orders],
                "investigator_count_per_side": n,
                "retrieval_budget_per_investigator": DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET,
            }
        )

    debater_ids = declare_debater_skeleton(
        tool,
        execution_id=execution_id,
        moderator_run_id=moderator_run_id,
        config=config,
    )

    investigators = await run_investigators(
        tool,
        execution_id=execution_id,
        moderator_run_id=moderator_run_id,
        config=config,
        orders=orders,
        debater_ids=debater_ids,
        retrieval_budget=DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET,
        on_progress=on_progress,
    )

    any_ok = any(i.ok for i in investigators)
    all_failed = bool(investigators) and not any_ok
    result = PretrialResult(
        skipped=False,
        orders=orders,
        investigators=investigators,
        fallback_self_search=all_failed,
        evidence_ready=any_ok,
        debater_run_ids=debater_ids,
    )

    # 刷新案卷索引（新落盘的庭前笔记）
    if any_ok:
        try:
            from agentcore.runtime.debate.research_dossier import (
                format_research_dossier_index,
                list_research_artifact_paths,
                preregister_research_dossier,
            )

            # 再跑一遍预登记以纳入新文件（已有 #eN 去重）
            await preregister_research_dossier(
                tool._evidence_ledger, tool._base_tool_context.backend
            )
            paths = await list_research_artifact_paths(tool._base_tool_context.backend)
            # 索引文案：用现有 ledger 映射行（简化：路径列表 + 台账提示）
            ledger_lines = [
                f"- {e.get('id')} · {e.get('title') or e.get('site') or ''}"
                for e in tool._evidence_ledger.all_entries()
                if (e.get("side_key") or "") not in ("", "dossier", "moderator")
            ][:40]
            config.research_dossier_index = format_research_dossier_index(
                paths, ledger_lines=ledger_lines or None
            )
            config.pretrial_evidence_ready = True
        except Exception:  # noqa: BLE001
            logger.exception("debate.pretrial.refresh_dossier_failed")
            config.pretrial_evidence_ready = True

    if on_completed is not None:
        payload = {
            **base_payload,
            **result.to_completed_payload(),
            "evidence_ledger_count": len(tool._evidence_ledger),
            "evidence_ledger_delta": tool._evidence_ledger.drain_delta(),
        }
        await on_completed(payload)
    return result


def extract_json_object(text: str) -> dict[str, Any]:
    """测试辅助：从模型正文抽 JSON 对象。"""
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return {}
        return _parse_json_object(m.group(0)) or {}

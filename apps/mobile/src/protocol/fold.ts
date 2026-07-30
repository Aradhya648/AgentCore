// The mobile protocol fold: SSE events → normalized ProjectedTurn (前端技术与架构 §十二).
//
// This is the ONE dangerous surface the conformance巡检 guards (cross-platform-
// frontend.mdc §四): it must match the backend oracle's golden for every vector
// (`pnpm conformance`). It is a brand-new mobile implementation — NOT shared with
// desktop's `projectExecution` — but behaviorally aligned to the same golden.
//
// Exhaustive `switch` + `assertNever` (支柱2): a new backend SSE type added to
// @agentcore/contract-types breaks this build until it is handled here.

import { mergeEvidenceLedger } from "@/lib/evidenceLedger";
import type {
  ApprovalRequiredPayload,
  ApprovalResolvedPayload,
  AskAssumption,
  AskFormatOption,
  AskQuestion,
  AskStyleOption,
  CheckpointRequiredPayload,
  CitationsPayload,
  ContentDeltaPayload,
  ContentResetPayload,
  ContextBlockWire,
  CostBreakdown,
  DebateNarrativeRound,
  DebatePretrialCompletedPayload,
  DebatePretrialOrdersPayload,
  DebatePretrialProgressPayload,
  DebatePretrialStartedPayload,
  DebateResultPayload,
  DebateRoundPayload,
  DebateRoundStartedPayload,
  DelegationAuthorizationRequiredPayload,
  DelegationAuthorizationResolvedPayload,
  DeliveryStatusPayload,
  EscalationRequiredPayload,
  EscalationResolvedPayload,
  EvidenceLedgerEntry,
  EvidenceLedgerPayload,
  FollowupsGeneratedPayload,
  GraphAppendPayload,
  MessageEndPayload,
  MessageStartPayload,
  PlanAgentPayload,
  PlanReviewRequiredPayload,
  PlanReviewResolvedPayload,
  PlanRevisedPayload,
  QuestionPostedPayload,
  ReasoningDeltaPayload,
  RunCancelledPayload,
  RunCompletedPayload,
  RunContextPayload,
  RunEscalationPayload,
  RunFailedPayload,
  RunOutputDeltaPayload,
  RunOutputResetPayload,
  RunPlanPayload,
  RunReasoningDeltaPayload,
  RunSkippedPayload,
  RunStartedPayload,
  RunToolProgressPayload,
  SSEEvent,
  TeamNotePostedPayload,
  TeamPreviewRequiredPayload,
  TeamSynthesisPreviewPayload,
  ToolPhase,
  ToolUseEndPayload,
  ToolUseProgressPayload,
  ToolUseStartPayload,
  TurnEvidenceLedgerEntry,
  TurnWarningPayload,
} from "@agentcore/contract-types";
import type {
  ActKind,
  DebatePretrialProjection,
  ProcessStep,
  ProjectedAct,
  ProjectedAgent,
  ProjectedCitation,
  ProjectedEvidenceLedgerEntry,
  ProjectedRun,
  ProjectedTeamNote,
  ProjectedTurn,
  TurnStatus,
} from "@agentcore/protocol-conformance";
import { foldInteractions, hasGatePending } from "./foldInteractions";

const FINISH_TO_STATUS: Record<string, TurnStatus> = {
  end_turn: "completed",
  max_rounds: "completed",
  degraded: "completed",
  unproductive: "completed",
  error: "failed",
  cancelled: "cancelled",
  // Crash / lease-sweeper salvage (流式回复持久化 P4): incomplete → cancelled-class.
  interrupted: "cancelled",
  // 挂起即收口 (②): a turn finalized AT a durable checkpoint ends with finish_reason=paused
  // — a terminal message_end whose turn is NOT done. Stay paused (gate interactions[] already
  // parked; this only adds finishReason + cost) so the resume card renders, not a completed
  // bubble. Without this it'd fall to "completed" below.
  paused: "paused",
};

function assertNever(x: never): never {
  throw new Error(`fold: unhandled SSE event type: ${JSON.stringify(x)}`);
}

// Orchestration tools (delegate/debate) never emit a `tool` step: they are stood in for
// by a `team` marker dropped at their run_plan (统一团队时间线). Mirrors the backend
// sink/oracle ORCHESTRATION_TOOLS — conformance pins this set equal.
const ORCHESTRATION_TOOLS = new Set(["delegate", "debate"]);

// CEO self-calls whose inline-timeline slot is stood in for by a DEDICATED marker, so they
// make NO captain tool step: delegate/debate → `team`; ask_user → `checkpoint`/`ask`. Superset
// of ORCHESTRATION_TOOLS. ask_user is here because a blocking ask SUSPENDs without a
// `tool_use_end` (its card marker represents it) and a rejected ask (card-shape validation)
// must not leak a red tool-error row. Mirrors backend/desktop MARKER_STANDIN_TOOLS —
// conformance pins this set equal.
const MARKER_STANDIN_TOOLS = new Set([...ORCHESTRATION_TOOLS, "ask_user"]);

/** Drop a `team` marker fixing the collaboration graph's chronological slot in the CEO
 * timeline. Deduped by execution_id (a debate's two run_plans share one id ⇒ one slot). */
function pushTeamMarker(process: ProcessStep[], executionId: string): void {
  if (!executionId) return;
  if (process.some((s) => s.kind === "team" && s.execution_id === executionId))
    return;
  process.push({ kind: "team", execution_id: executionId });
}

/** Drop a `graph_append` anchor on the append turn (跨回合同图追加). Growth frames carry
 * `host_message_id` and merge into the host graph; this marker is the append bubble's only
 * collaboration-graph cue. */
function pushGraphAppendMarker(
  process: ProcessStep[],
  p: GraphAppendPayload,
): void {
  const executionId = p.execution_id || "";
  if (!executionId) return;
  process.push({
    kind: "graph_append",
    execution_id: executionId,
    host_message_id: p.host_message_id || "",
    added_count: Number(p.added_count) || 0,
  });
}

/** Pop trailing `content` steps (交付前 blocking ask_user 吸收同轮 CEO 导语进卡，不重复进时间线).
 * Mirrors desktop `dropTrailingContentSteps` + backend `EventSink._accumulate_process`. */
function dropTrailingContentSteps(process: ProcessStep[]): void {
  while (process.length > 0 && process[process.length - 1].kind === "content") {
    process.pop();
  }
}

/** Drop a `checkpoint` marker (blocking ask_user) at its chronological slot. */
function pushCheckpointMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "checkpoint" && s.checkpoint_id === id))
    return;
  process.push({ kind: "checkpoint", checkpoint_id: id });
}

/** Drop an `ask` marker (non-blocking question) at its chronological slot. */
function pushAskMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "ask" && s.ask_id === id)) return;
  process.push({ kind: "ask", ask_id: id });
}

/** Drop a `plan_review` marker (plan-review gate) at its chronological slot. */
function pushPlanReviewMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "plan_review" && s.checkpoint_id === id))
    return;
  process.push({ kind: "plan_review", checkpoint_id: id });
}

/** Drop a `team_preview` marker (开工卡 gate). Event order is run_plan →
 * team_preview_required, but product narrative is 开工卡 → 协作图 — if a `team`
 * marker already exists, insert before the last one; else append. Dedupes by
 * checkpoint_id. Mirrors backend `EventSink._accumulate_process`. */
function pushTeamPreviewMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "team_preview" && s.checkpoint_id === id))
    return;
  const marker = { kind: "team_preview" as const, checkpoint_id: id };
  for (let i = process.length - 1; i >= 0; i--) {
    if (process[i].kind === "team") {
      process.splice(i, 0, marker);
      return;
    }
  }
  process.push(marker);
}

/** Drop an `escalation` marker (blocking required or non-blocking raised). */
function pushEscalationMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "escalation" && s.escalation_id === id))
    return;
  process.push({ kind: "escalation", escalation_id: id });
}

/** Drop an `approval` marker (热审批痕迹锚点). */
function pushApprovalMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "approval" && s.approval_id === id))
    return;
  process.push({ kind: "approval", approval_id: id });
}

/** Drop a `stage_card` marker (阶段推进卡痕迹锚点). */
function pushStageCardMarker(process: ProcessStep[], id: string): void {
  if (!id) return;
  if (process.some((s) => s.kind === "stage_card" && s.stage_card_id === id))
    return;
  process.push({ kind: "stage_card", stage_card_id: id });
}

/** Drop a `delegation_authorization` marker (委派授权痕迹锚点). 产品修正：与
 * team_preview 同锚定（「放行开工」族，授权 → 团队干活）—— insert before the last
 * `team` marker when one exists; else append. Mirrors the backend oracle. */
function pushDelegationAuthorizationMarker(
  process: ProcessStep[],
  id: string,
): void {
  if (!id) return;
  if (
    process.some(
      (s) => s.kind === "delegation_authorization" && s.authorization_id === id,
    )
  )
    return;
  const marker = {
    kind: "delegation_authorization" as const,
    authorization_id: id,
  };
  for (let i = process.length - 1; i >= 0; i--) {
    if (process[i].kind === "team") {
      process.splice(i, 0, marker);
      return;
    }
  }
  process.push(marker);
}

/** Fold one 逐轮叙事 update (`debate_round_started` → focus only, verdict null;
 * `debate_round` → full) into the accumulated list, keyed by `round_no` (a later
 * `debate_round` overwrites the focus-only entry — it carries focus too), kept
 * ascending. Mirrors desktop `upsertDebateRound` (conformance pins them equal). */
function upsertNarrativeRound(
  rounds: DebateNarrativeRound[],
  round: DebateNarrativeRound,
): DebateNarrativeRound[] {
  const idx = rounds.findIndex((r) => r.round_no === round.round_no);
  if (idx === -1) {
    return [...rounds, round].sort((a, b) => a.round_no - b.round_no);
  }
  const next = [...rounds];
  next[idx] = round;
  return next;
}

function emptyRunningPretrial(
  p: DebatePretrialStartedPayload | DebatePretrialOrdersPayload,
): DebatePretrialProjection {
  return {
    status: "running",
    thorough: p.thorough !== false,
    skipReason: ("skip_reason" in p ? p.skip_reason : null) ?? null,
    sides: (p.sides ?? []).map((s) => ({ key: s.key, name: s.name })),
    orders: [],
    investigators: [],
    evidenceLedgerCount: 0,
    fallbackSelfSearch: false,
    evidenceReady: false,
    // running 不宣称完整度（权威=completed）；orders 亦不强吸。
    failedSides: [],
  };
}

/** 折叠 `debate_pretrial_*`（权威 = completed）；与后端 oracle / 桌面 fold 同语义。 */
function foldDebatePretrial(
  current: DebatePretrialProjection | null,
  type:
    | "debate_pretrial_started"
    | "debate_pretrial_orders"
    | "debate_pretrial_progress"
    | "debate_pretrial_completed",
  payload: unknown,
): DebatePretrialProjection | null {
  if (type === "debate_pretrial_started") {
    return emptyRunningPretrial(payload as DebatePretrialStartedPayload);
  }
  if (type === "debate_pretrial_orders") {
    const p = payload as DebatePretrialOrdersPayload;
    const base = current ?? emptyRunningPretrial(p);
    const next: DebatePretrialProjection = {
      ...base,
      thorough: p.thorough !== false,
      sides:
        (p.sides ?? []).length > 0
          ? (p.sides ?? []).map((s) => ({ key: s.key, name: s.name }))
          : base.sides,
      orders: (p.orders ?? []).map((o) => ({
        side_key: o.side_key,
        tasks: (o.tasks ?? []).map((t) => ({
          query: t.query,
          ...(t.purpose ? { purpose: t.purpose } : {}),
        })),
        source: o.source ?? "empty",
      })),
    };
    const perSide = p.investigator_count_per_side ?? 0;
    if (perSide > 0) next.investigatorCountPerSide = perSide;
    return next;
  }
  if (type === "debate_pretrial_progress") {
    if (!current) return null;
    const p = payload as DebatePretrialProgressPayload;
    return {
      ...current,
      evidenceLedgerCount:
        p.evidence_ledger_count ?? current.evidenceLedgerCount,
    };
  }
  const p = payload as DebatePretrialCompletedPayload;
  // 缺 completeness/incomplete（旧 journal）= 未知，勿默认 empty→incomplete。
  const completeness = p.completeness != null ? p.completeness : undefined;
  const incomplete =
    typeof p.incomplete === "boolean" ? p.incomplete : undefined;
  return {
    status: p.status || "done",
    thorough: p.thorough !== false,
    skipReason: p.skip_reason ?? null,
    sides: (p.sides ?? []).map((s) => ({ key: s.key, name: s.name })),
    orders: (p.orders ?? []).map((o) => ({
      side_key: o.side_key,
      tasks: (o.tasks ?? []).map((t) => ({
        query: t.query,
        ...(t.purpose ? { purpose: t.purpose } : {}),
      })),
      source: o.source ?? "empty",
    })),
    investigators: (p.investigators ?? []).map((inv) => ({
      side_key: inv.side_key,
      run_id: inv.run_id,
      parent_run_id: inv.parent_run_id,
      ok: Boolean(inv.ok),
      ...(inv.task_query ? { task_query: inv.task_query } : {}),
    })),
    evidenceLedgerCount: p.evidence_ledger_count ?? 0,
    fallbackSelfSearch: Boolean(p.fallback_self_search),
    evidenceReady: Boolean(p.evidence_ready),
    ...(completeness != null ? { completeness } : {}),
    ...(incomplete != null ? { incomplete } : {}),
    failedSides: Array.isArray(p.failed_sides) ? [...p.failed_sides] : [],
    ...(p.external_evidence_mode != null
      ? { externalEvidenceMode: p.external_evidence_mode }
      : {}),
    ...(p.external_evidence_reason != null
      ? { externalEvidenceReason: p.external_evidence_reason }
      : {}),
    ...("retrieval_budget_per_investigator" in p
      ? {
          retrievalBudgetPerInvestigator:
            p.retrieval_budget_per_investigator ?? 0,
        }
      : {}),
  };
}

function agentFromPlan(a: PlanAgentPayload): ProjectedAgent {
  return {
    id: a.id,
    role: a.role,
    thinking: a.thinking,
    status: "idle",
    currentRunId: null,
    output: "",
    reasoning: "",
    toolProgress: null,
  };
}

function actFromRunPlan(p: RunPlanPayload): ProjectedAct {
  const raw = p.act;
  if (raw?.act_id) {
    const kind: ActKind =
      raw.kind === "debate" || raw.kind === "multi_agent"
        ? raw.kind
        : "multi_agent";
    const auth =
      raw.authorized_by === "stage_card" ||
      raw.authorized_by === "auto" ||
      raw.authorized_by === "preview"
        ? raw.authorized_by
        : null;
    return {
      actId: raw.act_id,
      kind,
      title: raw.title ?? null,
      anchorRunId: raw.anchor_run_id ?? null,
      authorizedBy: auth,
    };
  }
  // 兼容：旧 journal / 旧向量无 act → 合成单幕（act-1，kind = plan_type）。
  const kind: ActKind =
    p.plan_type === "debate" || p.plan_type === "multi_agent"
      ? p.plan_type
      : "multi_agent";
  return {
    actId: "act-1",
    kind,
    title: null,
    anchorRunId: null,
    authorizedBy: null,
  };
}

function upsertAct(acts: ProjectedAct[], act: ProjectedAct): void {
  const idx = acts.findIndex((a) => a.actId === act.actId);
  if (idx >= 0) acts[idx] = act;
  else acts.push(act);
}

function runFromPlan(
  s: RunPlanPayload["runs"][number],
  actId: string,
): ProjectedRun {
  return {
    id: s.id,
    agentId: s.agent_id,
    task: s.task,
    status: "pending",
    dependsOn: s.depends_on ?? [],
    outputSummary: null,
    debrief: null,
    durationMs: null,
    error: null,
    parentRunId: s.parent_run_id ?? null,
    kind: s.kind ?? "agent",
    role: null,
    model: null,
    usage: null,
    cost: null,
    stance: s.stance ?? null,
    group: s.group ?? null,
    round: s.round ?? 0,
    continuesRunId: null,
    //「计划已调整」轻痕迹 (设计 §7.2): set by the plan_revised event; null until then.
    revised: null,
    replacesRunId: s.replaces_run_id ?? null,
    actId,
    checkpoint: null,
    // 收到的上下文 (上下文传递可视化): filled by the run_context event; empty until then.
    receivedContext: [],
    // 升级实时可见: appended by the run_escalation event; empty until a worker escalates.
    escalations: [],
    process: [],
  };
}

export function fold(events: SSEEvent[]): ProjectedTurn {
  let content = "";
  let reasoning = "";
  // 跨回合流 vs 同回合 resume：仅 message_id 变化时清空气泡正文（见 message_start）。
  let lastMessageId: string | null = null;
  // 收到的上下文 · CEO 侧 (上下文传递可视化): the captain run id (its kind=captain
  // run_started) + the opening context it was fed, routed turn-level — the CEO is the
  // bubble above the graph, not a peer node.
  let captainRunId: string | null = null;
  let captainContext: ContextBlockWire[] = [];
  const process: ProcessStep[] = [];
  let citations: ProjectedCitation[] = [];
  let evidenceLedger: ProjectedEvidenceLedgerEntry[] = [];
  let citedIds: string[] = [];
  const agents: ProjectedAgent[] = [];
  const runs: ProjectedRun[] = [];
  // 幕序列（批 A1）：旧 run_plan 无 act → 合成单幕 act-1；无协作图时恒 []。
  let acts: ProjectedAct[] = [];
  let planId: string | null = null;
  let finishReason: string | null = null;
  let cost: CostBreakdown | null = null;
  let debate: DebateResultPayload | null = null;
  let debateRounds: DebateNarrativeRound[] = [];
  let crossExamEnabled = false;
  let debateOpening: string | null = null;
  let debatePretrial: DebatePretrialProjection | null = null;
  let teamSynthesisPreview: TeamSynthesisPreviewPayload | null = null;
  let deliveryStatus: DeliveryStatusPayload | null = null;
  let turnWarning: string | null = null;
  // 团队便签墙 (§2.2 通): notes broadcast to siblings this turn, in post order (deduped by noteId).
  const teamNotes: ProjectedTeamNote[] = [];
  const userInterjections: {
    interjectionId: string;
    executionId: string;
    content: string;
    status: string;
    note: string | null;
    attachments?: {
      name: string;
      workspacePath?: string;
      binary?: boolean;
    }[];
  }[] = [];
  const userInterjectionIndex = new Map<string, number>();
  let sawError = false;
  const checkpointSteps = new Map<string, string[]>();

  const agentById = (id: string) => agents.find((a) => a.id === id);
  const runById = (id: string) => runs.find((r) => r.id === id);

  for (const ev of events) {
    const type = ev.type;
    switch (type) {
      case "content_delta": {
        const d = (ev.payload as ContentDeltaPayload).delta || "";
        content += d;
        if (d) {
          const last = process[process.length - 1];
          if (last && last.kind === "content") last.text += d;
          else process.push({ kind: "content", text: d });
        }
        break;
      }
      // 草稿丢弃信号：引擎丢弃已流式的这一版正文、发 content_reset（reason 说明为何）。该事件
      // 进 _history（重连回放会重发），故 fold 必须镜像后端 oracle 与 desktop fold：清正文标量 +
      // 弹掉 process 尾部连续 content 步（reasoning/tool 是真实过程，保留），让重写版从干净态重
      // 累积。仅 reason=finish_guard（交付前核验回炉）折出「引用/格式核验后已重写」rework chip；
      // retry / soft_gate / ask_user 等只清正文、不留痕（误报根治）。
      case "content_reset": {
        content = "";
        while (
          process.length > 0 &&
          process[process.length - 1].kind === "content"
        ) {
          process.pop();
        }
        if ((ev.payload as ContentResetPayload).reason === "finish_guard") {
          process.push({ kind: "rework" });
        }
        break;
      }
      case "reasoning_delta": {
        const d = (ev.payload as ReasoningDeltaPayload).delta || "";
        reasoning += d;
        if (d) {
          const last = process[process.length - 1];
          if (last && last.kind === "reasoning") last.text += d;
          else process.push({ kind: "reasoning", text: d });
        }
        break;
      }
      case "tool_use_start": {
        const p = ev.payload as ToolUseStartPayload;
        // A delegated worker's call (run-scoped) belongs to its run node's process,
        // not the captain's inline timeline (统一团队时间线 = the CEO's OWN steps).
        // An orchestration tool (delegate/debate) is skipped from both: its `team`
        // marker (dropped at run_plan) stands in for it on the captain bubble.
        if (p.run_id) {
          const run = runById(p.run_id);
          if (run) {
            run.process.push({
              kind: "tool",
              id: p.tool_call_id,
              tool_name: p.tool_name,
              arguments: p.arguments ?? {},
              result: null,
              status: "running",
            });
          }
        } else if (!MARKER_STANDIN_TOOLS.has(p.tool_name)) {
          process.push({
            kind: "tool",
            id: p.tool_call_id,
            tool_name: p.tool_name,
            arguments: p.arguments ?? {},
            result: null,
            status: "running",
          });
        }
        const running = runs.find((r) => r.status === "running");
        if (running) {
          const ag = agentById(running.agentId);
          if (ag) ag.toolProgress = null;
        }
        break;
      }
      case "tool_use_end": {
        const p = ev.payload as ToolUseEndPayload;
        if (p.run_id) {
          const run = runById(p.run_id);
          if (run) {
            for (let i = run.process.length - 1; i >= 0; i--) {
              const step = run.process[i];
              if (step.kind === "tool" && step.id === p.tool_call_id) {
                step.result = p.result;
                step.status = p.status;
                if (p.display != null) step.display = p.display;
                break;
              }
            }
          }
        } else if (!MARKER_STANDIN_TOOLS.has(p.tool_name)) {
          for (let i = process.length - 1; i >= 0; i--) {
            const step = process[i];
            if (step.kind === "tool" && step.id === p.tool_call_id) {
              step.result = p.result;
              step.status = p.status;
              if (p.display != null) step.display = p.display;
              break;
            }
          }
        }
        break;
      }
      case "citations": {
        citations = (ev.payload as CitationsPayload).citations ?? [];
        break;
      }
      case "evidence_ledger": {
        const p = ev.payload as EvidenceLedgerPayload;
        if (Array.isArray(p.entries)) {
          evidenceLedger = p.entries as ProjectedEvidenceLedgerEntry[];
        } else if (p.delta?.length) {
          evidenceLedger = mergeTurnLedger(
            evidenceLedger,
            p.delta as TurnEvidenceLedgerEntry[],
          );
        }
        if (Array.isArray(p.cited_ids)) {
          citedIds = p.cited_ids.map(String);
        }
        break;
      }
      case "graph_append": {
        // 跨回合同图追加锚点：落在【追加回合】process；生长帧带 host_message_id 归宿主图。
        pushGraphAppendMarker(process, ev.payload as GraphAppendPayload);
        break;
      }
      case "run_plan": {
        const p = ev.payload as RunPlanPayload;
        const act = actFromRunPlan(p);
        // 跨回合同图追加：带 host_message_id 的生长 run_plan 不插新 team 标记
        // （锚点由 graph_append 承担；宿主回合已有 team）。
        if (!p.host_message_id) {
          // 协作图时间线落点: the first plan of an execution drops a `team` marker fixing the
          // collaboration graph's slot in the CEO timeline (later same-id batches no-op).
          pushTeamMarker(process, p.execution_id);
        }
        if (planId === null || planId === p.execution_id) {
          planId = p.execution_id;
          upsertAct(acts, act);
          for (const a of p.agents)
            if (!agentById(a.id)) agents.push(agentFromPlan(a));
          for (const s of p.runs)
            if (!runById(s.id)) runs.push(runFromPlan(s, act.actId));
        } else {
          planId = p.execution_id;
          acts = [act];
          agents.length = 0;
          runs.length = 0;
          for (const a of p.agents) agents.push(agentFromPlan(a));
          for (const s of p.runs) runs.push(runFromPlan(s, act.actId));
        }
        break;
      }
      case "run_started": {
        const p = ev.payload as RunStartedPayload;
        // The CEO captain is the turn's root (kind=captain); remember its run id so its
        // run_context routes turn-level (the captain node itself comes from run_plan, or
        // is dropped on a non-delegating turn).
        if (p.kind === "captain") captainRunId = p.run_id;
        const continuesRoot = p.continues_run_id ?? null;
        let run = runById(p.run_id);
        if (!run && continuesRoot) {
          const original = runById(continuesRoot);
          if (original) {
            const originAgent = agentById(original.agentId);
            agents.push({
              id: p.agent_id,
              role: originAgent?.role ?? original.agentId,
              thinking: originAgent?.thinking ?? true,
              status: "idle",
              currentRunId: null,
              output: "",
              reasoning: "",
              toolProgress: null,
            });
            run = {
              ...runFromPlan(
                {
                  id: p.run_id,
                  agent_id: p.agent_id,
                  task: original.task,
                  depends_on: [],
                },
                original.actId || "act-1",
              ),
              parentRunId: p.parent_run_id,
              kind: p.kind,
              continuesRunId: continuesRoot,
              // 乙 wire 携 round/stance (单一轮次投影): debate 续写从 wire 读取。
              stance: p.stance ?? null,
              group: p.group ?? null,
              round: p.round ?? 0,
            };
            runs.push(run);
          }
        }
        if (run) {
          run.status = "running";
          run.parentRunId = p.parent_run_id;
          run.kind = p.kind;
          if (continuesRoot && run.continuesRunId == null) {
            run.continuesRunId = continuesRoot;
          }
          // 冷回落接手: mid-flight `_redir` carries replaces_run_id on the wire.
          if (p.replaces_run_id) run.replacesRunId = p.replaces_run_id;
        }
        const ag = agentById(p.agent_id);
        if (ag) {
          ag.status = "working";
          ag.currentRunId = p.run_id;
          ag.toolProgress = null;
        }
        break;
      }
      case "run_context": {
        // 收到的上下文 (上下文传递可视化): the structured context this run was fed, carried
        // verbatim — the SAME data the LLM saw. The CAPTAIN's (kind=captain) routes
        // TURN-LEVEL onto captainContext (the CEO is the bubble above the graph, not a
        // node — so it shows on every turn, pure chat included), APPENDING across emits so
        // its context GROWS by each post-delegation team readback (通道⑤); a WORKER's folds
        // onto its graph node. Mirrors the desktop fold + backend oracle (conformance pins equal).
        const p = ev.payload as RunContextPayload;
        if (p.run_id === captainRunId) {
          captainContext = [...captainContext, ...p.blocks];
          break;
        }
        const run = runById(p.run_id);
        if (run) run.receivedContext = p.blocks;
        break;
      }
      case "run_output_delta": {
        const p = ev.payload as RunOutputDeltaPayload;
        const ag = agentById(p.agent_id);
        if (ag) ag.output += p.delta || "";
        const run = runById(p.run_id);
        if (run) {
          const d = p.delta || "";
          if (d) {
            const last = run.process[run.process.length - 1];
            if (last && last.kind === "content") last.text += d;
            else run.process.push({ kind: "content", text: d });
          }
        }
        break;
      }
      // 草稿丢弃信号的 worker 对偶（content_reset 之于 CEO）：引擎丢弃 worker 卡片已流式的这
      // 一版草稿、发 run_output_reset（reason 说明为何）。只清该 agent 的 output（重写版从干净
      // 态重累积），reasoning 是真实过程、保留——镜像后端 oracle 与 desktop fold（conformance
      // pins them equal）。仅 reason=finish_guard 折 rework 步；narration / retry 等不留痕。
      // transport-only（不进 journal）。
      case "run_output_reset": {
        const p = ev.payload as RunOutputResetPayload;
        const ag = agentById(p.agent_id);
        if (ag) ag.output = "";
        const run = runById(p.run_id);
        if (run) {
          while (
            run.process.length > 0 &&
            run.process[run.process.length - 1].kind === "content"
          ) {
            run.process.pop();
          }
          if (p.reason === "finish_guard") {
            run.process.push({ kind: "rework" });
          }
        }
        break;
      }
      case "run_reasoning_delta": {
        const p = ev.payload as RunReasoningDeltaPayload;
        const ag = agentById(p.agent_id);
        if (ag) ag.reasoning += p.delta || "";
        const run = runById(p.run_id);
        if (run) {
          const d = p.delta || "";
          if (d) {
            const last = run.process[run.process.length - 1];
            if (last && last.kind === "reasoning") last.text += d;
            else run.process.push({ kind: "reasoning", text: d });
          }
        }
        break;
      }
      case "run_tool_progress": {
        const p = ev.payload as RunToolProgressPayload;
        const ag = agentById(p.agent_id);
        if (ag) ag.toolProgress = { toolName: p.tool_name, chars: p.chars };
        break;
      }
      case "run_completed": {
        const p = ev.payload as RunCompletedPayload;
        // Additive ``gaps`` (缺章/超时缩水) — UI badge deferred to frontend batch;
        // acknowledge so the optional wire field stays forward-compatible.
        void p.gaps;
        const run = runById(p.run_id);
        if (run) {
          run.status = "completed";
          run.outputSummary = p.output_summary;
          run.debrief = p.debrief ?? null;
          run.durationMs = p.duration_ms;
          run.role = p.role;
          run.model = p.model;
          run.usage = p.usage;
          run.cost = p.cost;
        }
        const ag = agentById(p.agent_id);
        if (ag) {
          ag.status = "completed";
          ag.currentRunId = null;
          ag.toolProgress = null;
        }
        break;
      }
      case "run_failed": {
        const p = ev.payload as RunFailedPayload;
        const run = runById(p.run_id);
        if (run) {
          run.status = "failed";
          run.error = p.error;
          run.debrief = p.debrief ?? null;
        }
        const ag = agentById(p.agent_id);
        if (ag) {
          ag.status = "error";
          ag.toolProgress = null;
        }
        break;
      }
      case "run_cancelled": {
        // 跑一半改方向 / 整轮停止: interrupt mid-flight (orthogonal to run_failed).
        const p = ev.payload as RunCancelledPayload;
        const run = runById(p.run_id);
        if (run) run.status = "cancelled";
        const ag = agentById(p.agent_id);
        if (ag) {
          ag.status = "cancelled";
          ag.currentRunId = null;
          ag.toolProgress = null;
        }
        break;
      }
      case "run_skipped": {
        // 级联跳过 / graceful abort: node never ran —「未执行」. Agent stays idle.
        const p = ev.payload as RunSkippedPayload;
        const run = runById(p.run_id);
        if (run) run.status = "skipped";
        break;
      }
      case "run_progress":
        // Derived below from run states (cumulative, multi-batch safe); wire counter
        // is a timeline marker only.
        break;
      case "plan_revised": {
        //「计划已调整」轻痕迹 (设计 §7.2): the CEO autonomously re-bound / re-steered the
        // paused plan via replan — tag each affected node (bind=据上游证据定稿待绑定步骤;
        // steer=偏离后操舵未跑步骤) so it paints a non-interrupting trace. bind wins over
        // steer if a node is both. A stray run_id (not on this graph) is ignored. Mirrors
        // the desktop fold + backend oracle (conformance pins them equal).
        const p = ev.payload as PlanRevisedPayload;
        for (const rev of p.revisions ?? []) {
          const run = runById(rev.run_id);
          if (run && !(run.revised === "bind" && rev.kind === "steer")) {
            run.revised = rev.kind;
          }
        }
        break;
      }
      case "run_escalation": {
        // 升级实时可见 (非阻塞): append to run for ⚠️ badge; process marker for timeline slot.
        const p = ev.payload as RunEscalationPayload;
        const run = runById(p.run_id);
        if (run)
          run.escalations.push({
            question: p.question,
            assumption: p.assumption,
            blocking: p.blocking,
            status: "raised",
            answer: null,
            kind: p.kind === "scope" || p.kind === "dep" ? p.kind : "normal",
          });
        pushEscalationMarker(process, p.escalation_id);
        break;
      }
      case "escalation_required": {
        // 阻塞式求决策: pending card on run + positional escalation marker (二期 D1/D2).
        const p = ev.payload as EscalationRequiredPayload;
        const run = runById(p.run_id);
        if (run)
          run.escalations.push({
            question: p.question,
            assumption: p.assumption,
            blocking: true,
            status: "pending",
            answer: null,
            kind: p.kind === "scope" || p.kind === "dep" ? p.kind : "normal",
            ...(p.awaiting === "ceo" ? { awaiting: "ceo" as const } : {}),
          });
        pushEscalationMarker(process, p.escalation_id);
        break;
      }
      case "escalation_resolved": {
        // Settlement: flip pending → resolved | assumed | timed_out.
        const p = ev.payload as EscalationResolvedPayload;
        const esc = runById(p.run_id)?.escalations.find(
          (e) => e.status === "pending",
        );
        if (esc) {
          if (p.status === "resolved") {
            esc.status = "resolved";
            esc.answer = p.answer;
          } else if (p.status === "assumed") {
            esc.status = "assumed";
            esc.answer = null;
          } else {
            esc.status = "timed_out";
            esc.answer = null;
          }
          if (p.arbitrated_by === "ceo") {
            esc.arbitrated_by = "ceo";
            if (p.via_user != null) esc.via_user = p.via_user;
          }
        }
        break;
      }
      // 辩论收场：整段结构化产物（简报 + 交锋叙事线）verbatim 折入 ProjectedTurn.debate，
      // 与团队图互补（图承载辩手执行/发言全文，本字段承载主持人裁判 + 决策简报）。
      case "debate_result":
        debate = ev.payload as DebateResultPayload;
        break;
      // 辩论逐轮增量（进行中实时叠加，非 frame）：折叠累积成 debateRounds，与 oracle / 桌面
      // fold 一致。round_started 先给焦点（verdict=null=进行中），round 补 summary/verdict/sides。
      case "debate_round_started": {
        const p = ev.payload as DebateRoundStartedPayload;
        if (p.cross_exam_enabled === true) crossExamEnabled = true;
        const rawOpening = (p.opening ?? "").trim();
        if (rawOpening && !debateOpening) debateOpening = rawOpening;
        debateRounds = upsertNarrativeRound(debateRounds, {
          round_no: p.round_no,
          focus: p.focus,
          summary: "",
          verdict: null,
          sides: [],
          clashes: [],
          cross_exam: [],
          witness_exam: [],
          findings: [],
          thread_turns: [],
        });
        break;
      }
      case "debate_round": {
        const p = ev.payload as DebateRoundPayload;
        debateRounds = upsertNarrativeRound(debateRounds, {
          round_no: p.round_no,
          focus: p.focus,
          summary: p.summary,
          verdict: p.verdict,
          sides: p.sides,
          clashes: p.clashes,
          cross_exam: p.cross_exam ?? [],
          witness_exam: p.witness_exam ?? [],
          findings: p.findings ?? [],
          thread_turns: p.thread_turns ?? [],
        });
        break;
      }
      case "debate_pretrial_started":
      case "debate_pretrial_orders":
      case "debate_pretrial_progress":
      case "debate_pretrial_completed": {
        debatePretrial = foldDebatePretrial(debatePretrial, type, ev.payload);
        break;
      }
      // 团队便签墙 (§2.2 通): a worker broadcast a one-line decision / heads-up to its
      // concurrent siblings — fold onto teamNotes (post order), deduped by noteId for replay
      // safety. Mirrors the backend oracle + desktop fold (conformance pins them equal).
      case "team_note_posted": {
        const p = ev.payload as TeamNotePostedPayload;
        if (!teamNotes.some((n) => n.noteId === p.note_id)) {
          teamNotes.push({
            noteId: p.note_id,
            runId: p.run_id,
            agentId: p.agent_id,
            role: p.role,
            kind: p.kind,
            text: p.text,
            ts: p.ts,
            status: "active",
            supersedes: p.supersedes ?? null,
            ...(p.source ? { source: p.source } : {}),
          });
        }
        // 便签会过期 → supersession (§2.2): an amendment (carries `supersedes`) marks its TARGET
        // superseded (改写) / voided (作废). Target was posted earlier so it is already in the list.
        if (p.supersedes) {
          const target = teamNotes.find((n) => n.noteId === p.supersedes);
          if (target) {
            target.status =
              p.supersede_mode === "void" ? "voided" : "superseded";
          }
        }
        break;
      }
      case "approval_required": {
        const p = ev.payload as ApprovalRequiredPayload;
        pushApprovalMarker(process, p.approval_id);
        break;
      }
      case "approval_resolved":
        break;
      case "delegation_authorization_required": {
        const p = ev.payload as DelegationAuthorizationRequiredPayload;
        pushDelegationAuthorizationMarker(process, p.authorization_id);
        break;
      }
      case "delegation_authorization_resolved":
        break;
      case "checkpoint_required": {
        const p = ev.payload as CheckpointRequiredPayload;
        // Absorb same-round CEO prose into the checkpoint card (mirrors desktop
        // foldCheckpointMarker): drop trailing content steps + clear content scalar.
        dropTrailingContentSteps(process);
        content = "";
        pushCheckpointMarker(process, p.checkpoint_id);
        break;
      }
      case "checkpoint_resolved":
        break;
      case "plan_review_required": {
        const p = ev.payload as PlanReviewRequiredPayload;
        pushPlanReviewMarker(process, p.checkpoint_id);
        const runIds = (p.steps ?? []).map((s) => s.run_id);
        checkpointSteps.set(p.checkpoint_id, runIds);
        for (const rid of runIds) {
          const run = runById(rid);
          if (run) run.checkpoint = { status: "pending", decision: null };
        }
        break;
      }
      case "plan_review_resolved": {
        const p = ev.payload as PlanReviewResolvedPayload;
        for (const rid of checkpointSteps.get(p.checkpoint_id) ?? []) {
          const run = runById(rid);
          if (run)
            run.checkpoint = { status: "resolved", decision: p.decision };
        }
        break;
      }
      case "team_preview_required": {
        const p = ev.payload as TeamPreviewRequiredPayload;
        pushTeamPreviewMarker(process, p.checkpoint_id);
        break;
      }
      case "team_preview_resolved":
        break;
      case "stage_card_required": {
        // 阶段推进卡：生命周期进 interactions[]；process 落轻量锚点（历史回看去向痕迹）。
        const p = ev.payload as { stage_card_id?: string };
        pushStageCardMarker(process, p.stage_card_id || "");
        break;
      }
      case "stage_card_resolved":
        break;
      case "question_posted": {
        // 非阻塞提问 (ask_user blocking=false): drop an `ask` marker at its chronological
        // slot; the turn does NOT pause. Mirrors the backend oracle.
        const p = ev.payload as QuestionPostedPayload;
        pushAskMarker(process, p.ask_id);
        break;
      }
      case "error":
        sawError = true;
        break;
      case "message_end": {
        const p = ev.payload as MessageEndPayload;
        finishReason = p.finish_reason;
        cost = p.cost ?? null;
        break;
      }
      case "message_start": {
        // 跨回合流：message_id 变化 = 新助手气泡 → 清空正文/过程时间线；
        // 同 execution_id 的 runs/agents 保留，使第二回合追加帧继续生长同一张协作图。
        // 同 message_id = 挂起恢复重开同一气泡 → 保留已累积正文（pause→resume）。
        const mid = String(
          (ev.payload as { message_id?: string }).message_id || "",
        );
        if (lastMessageId === null || (mid && mid !== lastMessageId)) {
          content = "";
          reasoning = "";
          process.length = 0;
          finishReason = null;
          cost = null;
        }
        if (mid) lastMessageId = mid;
        break;
      }
      // Not part of the normalized turn judge state beyond interactions[] fold (no-op) —
      // enumerated so assertNever stays exhaustive against @agentcore/contract-types.
      case "turn_saved":
      case "title_generated":
      case "followups_generated":
      case "followups_unavailable":
      case "board_op_required":
      case "board_read_required":
      case "desktop_notify_required":
      case "host_op_required":
      case "tool_progress":
      case "tool_use_progress":
      case "coordination_wait":
      case "turn_queued":
      // L3 团队浏览器直播 (D13/D14): ephemeral 直播侧信道——base64 jpeg 帧 + 粗粒度通道状态，
      // 从不落 turn journal，喂桌面工作区直播面板。手机 fold no-op（与桌面 conformanceFold 同款枚举）。
      case "browser_live_frame":
      case "browser_live_status":
      case "batch_metrics":
      case "run_escalation_gate":
      case "interaction_orphaned":
      case "workspace_op_required":
      case "handoff_snapshot_done":
      case "handoff_job_started":
      case "handoff_apply_done":
      case "execution_detached":
      case "execution_completed":
      case "sim.agent_action":
      case "sim.agent_state":
      case "sim.interaction":
      case "sim.tick_started":
      case "sim.tick_ended":
      case "sim.tick_frame":
      case "sim.world_event":
      case "sim.show.affection_shift":
      case "sim.show.departure":
      case "sim.show.episode_gate":
      case "sim.show.heart_pick":
      case "sim.show.pair_formed":
      case "sim.show.reveal":
      case "sim.show.zero_vote_alert":
        break;
      case "turn_warning": {
        turnWarning = (ev.payload as TurnWarningPayload).message;
        break;
      }
      case "team_synthesis_preview": {
        teamSynthesisPreview = ev.payload as TeamSynthesisPreviewPayload;
        break;
      }
      case "delivery_status": {
        // 交付状态：同 execution_id 保最新（后写覆盖），镜像 oracle / 桌面 fold。
        deliveryStatus = ev.payload as DeliveryStatusPayload;
        break;
      }
      case "user_interjection": {
        const p = ev.payload as {
          interjection_id?: string;
          execution_id?: string;
          content?: string;
          status?: string;
          note?: string | null;
          attachments?: Array<{
            name?: string;
            workspace_path?: string;
            binary?: boolean;
          }>;
        };
        const iid = (p.interjection_id || "").trim();
        if (iid) {
          const attachments = (p.attachments ?? [])
            .filter(
              (
                a,
              ): a is {
                name: string;
                workspace_path?: string;
                binary?: boolean;
              } => typeof a?.name === "string" && Boolean(a.name.trim()),
            )
            .map((a) => ({
              name: a.name.trim(),
              workspacePath:
                typeof a.workspace_path === "string" && a.workspace_path.trim()
                  ? a.workspace_path
                  : undefined,
              binary: Boolean(a.binary),
            }));
          const leaf = {
            interjectionId: iid,
            executionId: p.execution_id || "",
            content: p.content || "",
            status: p.status || "delivered",
            note: typeof p.note === "string" ? p.note : null,
            ...(attachments.length > 0 ? { attachments } : {}),
          };
          const idx = userInterjectionIndex.get(iid);
          if (idx === undefined) {
            userInterjectionIndex.set(iid, userInterjections.length);
            userInterjections.push(leaf);
          } else {
            userInterjections[idx] = leaf;
          }
        }
        break;
      }
      default:
        assertNever(type);
    }
  }

  const interactions = foldInteractions(events);
  let status: TurnStatus;
  if (finishReason != null) {
    status = FINISH_TO_STATUS[finishReason] ?? "completed";
  } else if (sawError) {
    status = "failed";
  } else if (hasGatePending(interactions)) {
    status = "paused";
  } else {
    status = "running";
  }

  // A cancelled OR failed turn may leave in-flight nodes with no terminal frame; freeze
  // them as cancelled (parity with the desktop finalizeFold + backend oracle). `cancelled`
  // is the graceful stop; `failed` is the defensive case — a turn that errors out (hard
  // crash / lost terminal frame) with a still-running worker would otherwise replay as a
  // forever-spinning node on reload.
  if (status === "cancelled" || status === "failed") {
    for (const r of runs) if (r.status === "running") r.status = "cancelled";
    for (const a of agents) if (a.status === "working") a.status = "cancelled";
  }

  // Turn terminal: plan-declared nodes with no terminal frame → skipped（旧 journal 无
  // run_skipped 时靠本收口兜住；completed 也要处理 pending 残留）。
  if (status === "completed" || status === "cancelled" || status === "failed") {
    for (const r of runs) if (r.status === "pending") r.status = "skipped";
  }

  return {
    status,
    finishReason,
    content,
    reasoning,
    captainContext,
    // CEO's inline timeline — single-agent AND multi-agent (统一团队时间线); the team
    // graph slots at the `delegate` step on a delegating turn.
    process,
    citations,
    evidenceLedger,
    citedIds,
    agents,
    runs,
    acts,
    progress: {
      completed: runs.filter((r) => r.status === "completed").length,
      total: runs.length,
    },
    interactions,
    cost,
    debate,
    debateRounds,
    debatePretrial,
    crossExamEnabled,
    debateOpening,
    teamSynthesisPreview,
    deliveryStatus,
    turnWarning,
    teamNotes,
    userInterjections,
  };
}

/**
 * 下一步推荐 (CEO→用户): pull a finished turn's followup suggestions straight off its raw SSE
 * events — a transport-only sibling of {@link fold}, deliberately kept OUT of the normalized
 * {@link ProjectedTurn}. Followups are DERIVED-persisted on `Message.followups` (reload via
 * MessageDetail); the live path rides `followups_generated`. Conformance fold still no-ops
 * the event (ProjectedTurn does not carry chips).
 *
 * Identity seam: chips are matched by `message_id` against this turn's `message_start`.
 * Missing `message_id` → empty (never fall back to「last batch」). A mismatched id (late
 * event appended to the wrong live turn after a fast consecutive send) is also empty.
 */
export function extractFollowups(events: SSEEvent[]): string[] {
  let turnMessageId: string | null = null;
  for (const ev of events) {
    if (ev.type === "message_start") {
      turnMessageId = (ev.payload as MessageStartPayload).message_id;
    }
  }
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type !== "followups_generated") continue;
    const p = events[i].payload as FollowupsGeneratedPayload;
    if (!p.message_id) return [];
    if (turnMessageId && p.message_id !== turnMessageId) continue;
    return p.followups;
  }
  return [];
}

/** Soft empty when followups mint failed (live-only; no chips). */
export function extractFollowupsUnavailable(events: SSEEvent[]): boolean {
  if (extractFollowups(events).length > 0) return false;
  let turnMessageId: string | null = null;
  for (const ev of events) {
    if (ev.type === "message_start") {
      turnMessageId = (ev.payload as MessageStartPayload).message_id;
    }
  }
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type !== "followups_unavailable") continue;
    const p = events[i].payload as { message_id?: string };
    if (!p.message_id) return false;
    if (turnMessageId && p.message_id !== turnMessageId) continue;
    return true;
  }
  return false;
}

/** FIFO 排队态（``turn_queued``）：传输态 sibling——不进 {@link ProjectedTurn}。
 * 有 ``message_start`` 后视为已开跑，返回 null（排队徽标收起）。 */
export function extractTurnQueued(
  events: SSEEvent[],
): { position: number; queueDepth: number } | null {
  let queued: { position: number; queueDepth: number } | null = null;
  for (const ev of events) {
    if (ev.type === "turn_queued") {
      const p = ev.payload as {
        position?: number;
        queue_depth?: number;
      };
      const position = typeof p.position === "number" ? p.position : 0;
      const queueDepth =
        typeof p.queue_depth === "number" ? p.queue_depth : position;
      if (position >= 1) queued = { position, queueDepth };
    }
    if (ev.type === "message_start") return null;
  }
  return queued;
}

/** Merge turn-ledger delta by id (append-order; later write wins). */
function mergeTurnLedger(
  existing: ProjectedEvidenceLedgerEntry[],
  delta: TurnEvidenceLedgerEntry[],
): ProjectedEvidenceLedgerEntry[] {
  if (delta.length === 0) return existing;
  const order: string[] = [];
  const byId = new Map<string, ProjectedEvidenceLedgerEntry>();
  for (const e of existing) {
    if (!byId.has(e.id)) order.push(e.id);
    byId.set(e.id, e);
  }
  for (const e of delta) {
    if (!byId.has(e.id)) order.push(e.id);
    byId.set(e.id, e as ProjectedEvidenceLedgerEntry);
  }
  return order
    .map((id) => byId.get(id))
    .filter((e): e is ProjectedEvidenceLedgerEntry => e !== undefined);
}

/**
 * `graph_append` 开幕元数据（批 A4 呈现）：execution_id → act_kind。
 * Transport-only sibling——不进 {@link ProjectedTurn.process}（后端 process 锚点亦无此字段；
 * 桌面把 act_kind 挂在 live process 扩展上，手机用旁路 map，历史/live 同源）。
 */
export function extractGraphAppendActKinds(
  events: SSEEvent[],
): Map<string, string> {
  const map = new Map<string, string>();
  for (const ev of events) {
    if (ev.type !== "graph_append") continue;
    const p = ev.payload as GraphAppendPayload;
    const executionId = p.execution_id || "";
    const kind = p.act_kind;
    if (executionId && kind) map.set(executionId, kind);
  }
  return map;
}

/** `graph_append.authorized_by` → 锚点副文案（与幕分带角标同口径）。 */
export function extractGraphAppendAuthorizedBy(
  events: SSEEvent[],
): Map<string, string> {
  const map = new Map<string, string>();
  for (const ev of events) {
    if (ev.type !== "graph_append") continue;
    const p = ev.payload as GraphAppendPayload;
    const executionId = p.execution_id || "";
    const auth = p.authorized_by;
    if (executionId && auth) map.set(executionId, auth);
  }
  return map;
}

/** 幕授权来源 → 列表/锚点短文案。 */
export function actAuthorizedByLabel(
  authorizedBy: string | null | undefined,
): string | null {
  if (authorizedBy === "stage_card") return "经推进卡授权";
  if (authorizedBy === "auto") return "自动开辩";
  if (authorizedBy === "preview") return "开工卡授权";
  return null;
}

/**
 * 场级证据台账（证据台账 M1）：从 `debate_pretrial_completed` /
 * `debate_round` 的 `evidence_ledger_delta` 累积、`debate_result.evidence_ledger`
 * 权威覆盖。Transport-only sibling of {@link fold}——刻意不进 {@link ProjectedTurn}
 *（conformance golden 经 `debate.evidence_ledger` 承载收场权威；live delta 供徽章
 * `#eN` 解析，O7）。
 */
export function extractEvidenceLedger(
  events: SSEEvent[],
): EvidenceLedgerEntry[] {
  let ledger: EvidenceLedgerEntry[] = [];
  for (const ev of events) {
    if (ev.type === "debate_pretrial_completed" || ev.type === "debate_round") {
      const delta =
        (ev.payload as DebatePretrialCompletedPayload | DebateRoundPayload)
          .evidence_ledger_delta ?? [];
      if (delta.length) ledger = mergeEvidenceLedger(ledger, delta);
    } else if (ev.type === "debate_result") {
      const full = (ev.payload as DebateResultPayload).evidence_ledger;
      if (Array.isArray(full)) ledger = full;
    }
  }
  return ledger;
}

/**
 * 工具执行阶段进度 (联网搜索前端展示优化): the LATEST coarse phase per still-running tool call,
 * pulled straight off a live turn's raw SSE events — a transport-only sibling of {@link fold}
 * (twin of {@link extractFollowups} / {@link extractAsks}), deliberately kept OUT of the
 * normalized {@link ProjectedTurn} (so the conformance golden stays phase-less, exactly like the
 * `tool_use_progress` no-op inside the fold). Keyed by `tool_call_id`; an entry is CLEARED on the
 * matching `tool_use_end` so a finished tool shows no stale phase. web_search fires querying /
 * queued / fallback while its blocking request is in flight.
 *
 * Only a LIVE turn carries these events (they are never journaled), so history replay yields an
 * empty map and tool rows fall back to their plain running/done status — the same live-only
 * semantics as the followups / asks siblings.
 */
export function extractToolPhases(events: SSEEvent[]): Map<string, ToolPhase> {
  const phases = new Map<string, ToolPhase>();
  for (const ev of events) {
    if (ev.type === "tool_use_progress") {
      const p = ev.payload as ToolUseProgressPayload;
      phases.set(p.tool_call_id, p.phase as ToolPhase);
    } else if (ev.type === "tool_use_end") {
      phases.delete((ev.payload as ToolUseEndPayload).tool_call_id);
    }
  }
  return phases;
}

/** Worker-scoped `tool_use_progress` (run_id present): the LATEST coarse EXECUTION phase per
 * still-running worker run, keyed by `run_id`. Transport-only sibling of {@link extractToolPhases}
 * — kept OUT of {@link ProjectedTurn} so the golden stays phase-less. Cleared on the matching
 * worker `tool_use_end`. */
export function extractWorkerToolPhases(
  events: SSEEvent[],
): Map<string, { phase: ToolPhase; toolName: string }> {
  const phases = new Map<string, { phase: ToolPhase; toolName: string }>();
  for (const ev of events) {
    if (ev.type === "tool_use_progress") {
      const p = ev.payload as ToolUseProgressPayload;
      if (!p.run_id) continue;
      phases.set(p.run_id, {
        phase: p.phase as ToolPhase,
        toolName: p.tool_name,
      });
    } else if (ev.type === "tool_use_end") {
      const p = ev.payload as ToolUseEndPayload;
      if (p.run_id) phases.delete(p.run_id);
    }
  }
  return phases;
}

/** 非阻塞提问 (ask_user blocking=false) 的卡片内容：question + 可选 选项/默认/风格。 The
 *  conformance fold only drops a positional `ask` MARKER (`{kind:"ask", ask_id}`) in the
 *  timeline — the question text/options are transport-only and excluded from the golden
 *  (same as the desktop oracle). This carries that content so the chat can render the card
 *  AT the marker; it is read straight off the raw events, NOT the ProjectedTurn. */
export interface NonBlockingAsk {
  id: string;
  question: string;
  context: string;
  assumptions: AskAssumption[];
  questions: AskQuestion[];
  styleOptions: AskStyleOption[];
  formatOptions: AskFormatOption[];
}

/**
 * 非阻塞提问 (CEO→用户, blocking=false): pull a turn's `question_posted` cards off its raw SSE
 * events — a transport-only sibling of {@link fold} (twin of {@link extractFollowups}),
 * keyed/ordered by `ask_id`. Mirrors the desktop `nonBlockingAsksFromEvents` projection.
 *
 * Only LIVE turns and MULTI-agent history carry these events (a single-agent turn persists
 * an empty `runs.events`, so its reload keeps just the bare `ask` marker — no card, exactly
 * like desktop). De-duped by `ask_id`, preserving first-seen order; empty when none.
 */
export function extractAsks(events: SSEEvent[]): NonBlockingAsk[] {
  const byId = new Map<string, NonBlockingAsk>();
  const order: string[] = [];
  for (const ev of events) {
    if (ev.type !== "question_posted") continue;
    const p = ev.payload as QuestionPostedPayload;
    if (byId.has(p.ask_id)) continue;
    order.push(p.ask_id);
    byId.set(p.ask_id, {
      id: p.ask_id,
      question: p.question,
      context: p.context,
      assumptions: p.assumptions ?? [],
      questions: p.questions ?? [],
      styleOptions: p.style_options ?? [],
      formatOptions: p.format_options ?? [],
    });
  }
  return order.map((id) => byId.get(id) as NonBlockingAsk);
}

/** 热审批 / 委派授权痕迹 (统一时间线二期 D3): resolved 后在其 required 时刻的标记槽
 * 显一条轻状态行；pending 期间标记在、行不显（操作面在 PauseCard）。Transport-only
 * sibling of {@link fold}, keyed by approval_id / authorization_id. */
export interface HotDecisionTrace {
  kind: "approval" | "delegation_authorization";
  /** 已裁决才渲染行（D3 resolved 门控）。 */
  resolved: boolean;
  /** deny → 「已拒绝」形态。 */
  denied: boolean;
  /** approval 的工具名（委派授权无）。 */
  toolName?: string;
}

export function extractHotDecisionTraces(
  events: SSEEvent[],
): Map<string, HotDecisionTrace> {
  const byId = new Map<string, HotDecisionTrace>();
  for (const ev of events) {
    if (ev.type === "approval_required") {
      const p = ev.payload as ApprovalRequiredPayload;
      if (!p.approval_id) continue;
      byId.set(p.approval_id, {
        kind: "approval",
        resolved: false,
        denied: false,
        toolName: p.tool_name,
      });
    } else if (ev.type === "approval_resolved") {
      const p = ev.payload as ApprovalResolvedPayload;
      const t = byId.get(p.approval_id);
      if (t) {
        t.resolved = true;
        t.denied = p.decision === "deny";
      }
    } else if (ev.type === "delegation_authorization_required") {
      const p = ev.payload as DelegationAuthorizationRequiredPayload;
      if (!p.authorization_id) continue;
      byId.set(p.authorization_id, {
        kind: "delegation_authorization",
        resolved: false,
        denied: false,
      });
    } else if (ev.type === "delegation_authorization_resolved") {
      const p = ev.payload as DelegationAuthorizationResolvedPayload;
      const t = byId.get(p.authorization_id);
      if (t) {
        t.resolved = true;
        t.denied = p.decision === "deny";
      }
    }
  }
  return byId;
}

/** 阶段推进卡时间线痕迹：resolved/orphaned 后在 required 槽显轻行。 */
export interface StageCardTrace {
  /** resolved | orphaned 才渲染；pending 操作面在 StageCard Dock。 */
  outcome: "resolved" | "orphaned" | "pending";
  /** start_debate | research_first（仅 resolved）。 */
  decision?: string;
}

export function extractStageCardTraces(
  events: SSEEvent[],
): Map<string, StageCardTrace> {
  const byId = new Map<string, StageCardTrace>();
  for (const ev of events) {
    if (ev.type === "stage_card_required") {
      const p = ev.payload as { stage_card_id?: string };
      if (!p.stage_card_id) continue;
      byId.set(p.stage_card_id, { outcome: "pending" });
    } else if (ev.type === "stage_card_resolved") {
      const p = ev.payload as {
        stage_card_id?: string;
        decision?: string;
      };
      const t = byId.get(p.stage_card_id || "");
      if (t) {
        t.outcome = "resolved";
        t.decision = p.decision;
      }
    } else if (ev.type === "interaction_orphaned") {
      const p = ev.payload as {
        interaction_id?: string;
        kind?: string;
      };
      if (p.kind !== "stage_card" || !p.interaction_id) continue;
      const t = byId.get(p.interaction_id);
      if (t) t.outcome = "orphaned";
      else byId.set(p.interaction_id, { outcome: "orphaned" });
    }
  }
  return byId;
}

/** Timeline-slot lookup for escalations (统一时间线二期): id → card body. Transport-only
 * sibling of {@link fold} — ProjectedTurn.runs[].escalations stays id-less (golden shape). */
export interface EscalationSlot {
  id: string;
  runId: string;
  esc: import("@agentcore/protocol-conformance").RunEscalation;
}

export function extractEscalationSlots(
  events: SSEEvent[],
): Map<string, EscalationSlot> {
  const byId = new Map<string, EscalationSlot>();
  for (const ev of events) {
    if (ev.type === "run_escalation") {
      const p = ev.payload as RunEscalationPayload;
      if (!p.escalation_id) continue;
      byId.set(p.escalation_id, {
        id: p.escalation_id,
        runId: p.run_id,
        esc: {
          question: p.question,
          assumption: p.assumption,
          blocking: p.blocking,
          status: "raised",
          answer: null,
          kind: p.kind === "scope" || p.kind === "dep" ? p.kind : "normal",
        },
      });
    } else if (ev.type === "escalation_required") {
      const p = ev.payload as EscalationRequiredPayload;
      if (!p.escalation_id) continue;
      byId.set(p.escalation_id, {
        id: p.escalation_id,
        runId: p.run_id,
        esc: {
          question: p.question,
          assumption: p.assumption,
          blocking: true,
          status: "pending",
          answer: null,
          kind: p.kind === "scope" || p.kind === "dep" ? p.kind : "normal",
          ...(p.awaiting === "ceo" ? { awaiting: "ceo" as const } : {}),
        },
      });
    } else if (ev.type === "escalation_resolved") {
      const p = ev.payload as EscalationResolvedPayload;
      const slot = byId.get(p.escalation_id);
      if (!slot) continue;
      if (p.status === "resolved") {
        slot.esc.status = "resolved";
        slot.esc.answer = p.answer;
      } else if (p.status === "assumed") {
        slot.esc.status = "assumed";
        slot.esc.answer = null;
      } else {
        slot.esc.status = "timed_out";
        slot.esc.answer = null;
      }
      if (p.arbitrated_by === "ceo") {
        slot.esc.arbitrated_by = "ceo";
        if (p.via_user != null) slot.esc.via_user = p.via_user;
      }
    }
  }
  return byId;
}

/** One tool call a delegated worker made, for its run-detail 工具明细 (RunDetail). Mirrors the
 *  process timeline's `tool` step shape (中文名 + args/result peek) minus the live-only `phase`
 *  — a settled/replayed run's tools are all resolved, and a running one just shows「进行中」. */
export interface RunToolCall {
  id: string;
  toolName: string;
  arguments: Record<string, unknown>;
  result: string | null;
  status: "running" | "success" | "error";
}

/**
 * 队员工具明细 (RunDetail · 工具调用): the run-scoped tool calls each delegated worker made, pulled
 * straight off a turn's raw SSE events — a transport-only sibling of {@link fold} (twin of
 * {@link extractAsks}), keyed by `run_id`, calls in fire order.
 *
 * The conformance {@link ProjectedTurn} folds a WORKER's run-scoped tool calls to NOTHING: they
 * belong to the worker's node, not the CEO's inline timeline (统一团队时间线 = the CEO's OWN steps),
 * and the golden carries no per-run tool IO — so the fold {@link fold} skips a `run_id`-tagged
 * `tool_use_*` (leaving only the coarse {@link ProjectedAgent.toolProgress}). The run-detail panel
 * reads the full call list from HERE instead, exactly like the asks side channel.
 *
 * Escalation submit ids come from {@link ProjectedTurn.interactions} (kind=escalation,
 * status=pending) — not a parallel extract map (P3).
 *
 * A `tool_use_start` opens a `running` call (null result) appended to its run; the matching
 * `tool_use_end` folds in its `result`/`status`. Orchestration tools (delegate/debate) are skipped
 * — they are the team STRUCTURE (rendered as sub-tasks / the graph), not a worker tool, mirroring
 * the fold's ORCHESTRATION_TOOLS skip. Both LIVE turns and MULTI-agent history (`runs.events`)
 * carry these events, so the panel works live AND on replay; a single-agent turn yields an empty
 * map (its calls are the captain's own, run_id-less).
 */
export function extractRunToolCalls(
  events: SSEEvent[],
): Map<string, RunToolCall[]> {
  const byRun = new Map<string, RunToolCall[]>();
  const byCallId = new Map<string, RunToolCall>();
  for (const ev of events) {
    if (ev.type === "tool_use_start") {
      const p = ev.payload as ToolUseStartPayload;
      if (!p.run_id || ORCHESTRATION_TOOLS.has(p.tool_name)) continue;
      const call: RunToolCall = {
        id: p.tool_call_id,
        toolName: p.tool_name,
        arguments: p.arguments ?? {},
        result: null,
        status: "running",
      };
      const list = byRun.get(p.run_id);
      if (list) list.push(call);
      else byRun.set(p.run_id, [call]);
      byCallId.set(p.tool_call_id, call);
    } else if (ev.type === "tool_use_end") {
      const p = ev.payload as ToolUseEndPayload;
      if (!p.run_id || ORCHESTRATION_TOOLS.has(p.tool_name)) continue;
      const call = byCallId.get(p.tool_call_id);
      if (call) {
        call.result = p.result;
        call.status = p.status;
      }
    }
  }
  return byRun;
}

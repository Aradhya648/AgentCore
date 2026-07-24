import { mergeEvidenceLedger } from "@/lib/evidenceLedger";
import type {
  CoordinationWaitPayload,
  DebateNarrativeRound,
  DebateResultPayload,
  DebateRoundPayload,
  DebateRoundStartedPayload,
  DeliveryStatusPayload,
  EvidenceLedgerEntry,
  ExecutionDetachedPayload,
  ProcessStep,
  RunPlanPayload,
  TeamSynthesisPreviewPayload,
  ToolUseProgressPayload,
} from "@/types/events";
import { create } from "zustand";
import { foldDebatePretrial, upsertDebateRound } from "./debate";
import type { DebatePretrialState } from "./debate";
import { type RunFrame, frameFromEvent } from "./frames";
import {
  ensureDelegateBatchStamps,
  mergePlanInto,
  planFromRunPlan,
} from "./plan";
import { projectExecution } from "./project";
import type {
  ExecutionJournal,
  ExecutionPlan,
  ExecutionStatus,
  UserInterjection,
} from "./types";

/** True when every projected run has left pending/running (图收口 by run 终态). */
function runsAllSettled(
  plan: ExecutionPlan,
  frames: RunFrame[],
  status: ExecutionStatus,
  debate: DebateResultPayload | null,
  debateRounds: DebateNarrativeRound[],
  crossExamEnabled: boolean,
  debateOpening: string | null,
): boolean {
  const exec = projectExecution(
    plan,
    frames,
    status,
    debate,
    debateRounds,
    crossExamEnabled,
    debateOpening,
  );
  if (exec.runs.length === 0) return false;
  return exec.runs.every(
    (r) => r.status !== "pending" && r.status !== "running",
  );
}

/**
 * The execution state of a single assistant message's turn — plan, frame
 * stream, playhead and cross-view focus. Keyed by assistant message id so every
 * past multi-agent turn in a conversation keeps its own graph: the live turn
 * streams frames into its message's slot, and a reloaded turn hydrates its slot
 * once from the persisted journal.
 */
export interface ExecutionRuntime {
  plan: ExecutionPlan | null;
  frames: RunFrame[];
  /** Number of frames to project. `null` = follow the live tail. */
  playhead: number | null;
  status: ExecutionStatus;
  /** 辩论收场产物（`debate_result` —— 回合级单事件，非 plan/非 frame）：到达即存此，
   * {@link projectExecution} 透传到 {@link Execution.debate}。null = 非辩论/未收场。 */
  debate: DebateResultPayload | null;
  /** 辩论逐轮叙事（`debate_round_started` / `debate_round` —— 回合级单事件，非 frame）：
   * 折叠累积于此，{@link projectExecution} 透传到 {@link Execution.debateRounds}。`[]` =
   * 非辩论/无逐轮事件。P2 起事件 DURABLE：重载由 hydrateFromJournal 以同一 fold 重建。 */
  debateRounds: DebateNarrativeRound[];
  /** 本场是否开启质询（`debate_round_started.cross_exam_enabled`，sticky OR）。缺字段 → false。 */
  crossExamEnabled: boolean;
  /** 主持人开场白（`debate_round_started.opening`，sticky 首个非空）。缺字段 → null。 */
  debateOpening: string | null;
  /** 庭前取证（`debate_pretrial_*`）：开赛后首轮前；null = 无 / 老 journal。 */
  debatePretrial: DebatePretrialState | null;
  /** 场级证据台账（`debate_round.evidence_ledger_delta` 累积；收场由 `debate.evidence_ledger`
   * 权威覆盖）。驱动辩论徽章 `#eN` 溯源；不进 ProjectedTurn。 */
  evidenceLedger: EvidenceLedgerEntry[];
  /** Worker-scoped `tool_use_progress` (run_id present), keyed by run id. Transport-only —
   * merged onto agents at projection time; never journaled or replayed. */
  workerToolPhases: Record<string, { phase: string; toolName: string }>;
  /** Per-run ProcessStep[] from journal reload (`runs.run_processes`). Overlay replaces
   * splice-derived process so reopen matches live interleaving. null while live. */
  runProcesses: Record<string, ProcessStep[]> | null;
  /** CEO 协调模式 Phase 1：`team_synthesis_preview` 最新快照（同 key 保最新）。P2 起
   * DURABLE：重载由 hydrateFromJournal 取 journal 中最后一条重建。驱动 StatusStrip
   * 「团队进展」预览行。 */
  teamSynthesisPreview: TeamSynthesisPreviewPayload | null;
  /** CEO 协调等待（`coordination_wait`）：captain 空等团队事件。EPHEMERAL——仅 live
   * stream；waiting=false / 回合结束清除。驱动 StatusStrip「等待团队成员完成」。 */
  coordinationWait: CoordinationWaitPayload | null;
  /** Client-only: wall-clock ms when the current wait segment began (heartbeats keep it). */
  coordinationWaitStartedAt: number | null;
  /** 执行转后台（`execution_detached`）：附着回合已收口、团队继续跑。EPHEMERAL——仅 live；
   * 驱动 StatusStrip 静态「团队后台运行中 · n/m」。`execution_completed` / 终态清除。 */
  executionDetached: ExecutionDetachedPayload | null;
  /** 交付状态（`delivery_status`，同 execution_id 保最新）：delegate 批次收尾的结构化交付
   * 对账（已交付/缺口/待用户操作）。DURABLE：重载由 hydrateFromJournal 取最后一条重建，
   * 驱动答复下方的交付状态卡。null = 本回合无对账（纯 prose 成功批次无声）。 */
  deliveryStatus: DeliveryStatusPayload | null;
  /** 协调中用户插话（`user_interjection`，同 interjectionId 保最新）。DURABLE。 */
  userInterjections: UserInterjection[];
}

/**
 * Every mutator targets one assistant message's {@link ExecutionRuntime} by id.
 * SSE dispatch resolves the live turn's assistant message id and routes frames
 * there; view interactions (focus / playhead) pass the message id of the graph
 * subtree they belong to ({@link useExecutionScope}).
 */
interface ExecutionState {
  byId: Record<string, ExecutionRuntime>;

  startExecution: (plan: ExecutionPlan, messageId: string) => void;
  /**
   * Ingest a `run_plan` batch. The first batch of a turn starts a fresh
   * execution; a later batch with the *same* execution id (the adaptive D1′
   * case where the CEO delegates again) is merged in — new agents/runs are
   * appended and the frame stream is kept — so every batch stays on the graph
   * and timeline. A new turn produces a new assistant message (new slot), so
   * cross-turn batches never merge.
   */
  ingestPlan: (plan: ExecutionPlan, messageId: string) => void;
  clearExecution: (messageId: string) => void;
  recordFrame: (frame: RunFrame, messageId: string) => void;
  /** Append a rAF-coalesced batch of frames in ONE update (流式性能): the SSE ingest
   * buffers a frame's worth of `run_*_delta` and flushes them here so a token storm
   * triggers ≤60 store writes/projections per second instead of one per token. */
  recordFrames: (frames: RunFrame[], messageId: string) => void;
  /** Store a turn's debate 收场产物 (`debate_result`) on its slot; a no-plan slot
   * ignores it (stray fact). Sibling of {@link recordFrame} — one accrues the frame
   * stream, the other the debate brief/narrative (a回合级 one-shot, not a frame). */
  recordDebateResult: (debate: DebateResultPayload, messageId: string) => void;
  /** Fold one 逐轮叙事 update (`debate_round_started` → focus only; `debate_round` →
   * full) into the slot's {@link ExecutionRuntime.debateRounds} via {@link
   * upsertDebateRound}; a no-plan slot ignores it. Drives the进行中 per-round overlay
   * before {@link recordDebateResult}'s 收场 product lands. */
  recordDebateRound: (round: DebateNarrativeRound, messageId: string) => void;
  /** Merge one `debate_round.evidence_ledger_delta` into the slot's live evidence ledger. */
  recordEvidenceLedgerDelta: (
    delta: EvidenceLedgerEntry[],
    messageId: string,
  ) => void;
  /** Sticky-OR 本场质询开关（`debate_round_started.cross_exam_enabled`）。 */
  recordCrossExamEnabled: (enabled: boolean, messageId: string) => void;
  /** Sticky 首个非空主持人开场白（`debate_round_started.opening`）；后续空串不覆盖。 */
  recordDebateOpening: (opening: string, messageId: string) => void;
  /** 折叠庭前取证事件（权威 = completed）。 */
  recordDebatePretrial: (
    type:
      | "debate_pretrial_started"
      | "debate_pretrial_orders"
      | "debate_pretrial_progress"
      | "debate_pretrial_completed",
    payload: unknown,
    messageId: string,
  ) => void;
  /** Stamp a delegated worker's running-tool EXECUTION phase (`tool_use_progress` with
   * `run_id`). Transport-only — not a frame. */
  setWorkerToolPhase: (
    payload: ToolUseProgressPayload,
    messageId: string,
  ) => void;
  /** Clear a worker's live EXECUTION phase when its tool finishes (`tool_use_end`). */
  clearWorkerToolPhase: (runId: string, messageId: string) => void;
  /** Stamp the latest multi-worker team progress preview (`team_synthesis_preview`).
   * Live stamp (同 key 保最新); journal is DURABLE — hydrateFromJournal rebuilds it. */
  setTeamSynthesisPreview: (
    preview: TeamSynthesisPreviewPayload,
    messageId: string,
  ) => void;
  /** Stamp / clear CEO coordination wait (`coordination_wait`). Transport-only. */
  setCoordinationWait: (
    wait: CoordinationWaitPayload | null,
    messageId: string,
  ) => void;
  /** Stamp / clear background-running chrome (`execution_detached`). Transport-only. */
  setExecutionDetached: (
    detached: ExecutionDetachedPayload | null,
    messageId: string,
  ) => void;
  /** Stamp the latest delivery reconciliation (`delivery_status`, 同 execution_id 保最新).
   * Live stamp; journal is DURABLE — hydrateFromJournal rebuilds it. */
  setDeliveryStatus: (status: DeliveryStatusPayload, messageId: string) => void;
  /** Upsert a mid-flight user interjection (`user_interjection`, same id keeps latest). */
  upsertUserInterjection: (item: UserInterjection, messageId: string) => void;
  setStatus: (status: ExecutionStatus, messageId: string) => void;
  setPlayhead: (index: number | null, messageId: string) => void;
  goLive: (messageId: string) => void;
  /**
   * Fold a persisted execution journal (`messages.runs`) into a message's slot,
   * reproducing the team graph a past multi-agent turn had — replayed through
   * the same fold as the live stream. When the slot already holds a plan,
   * applies only if the journal is strictly newer (more runs, else agents,
   * else frames); equal or older journals are left untouched so a re-render
   * or stale history fetch never rolls live state back.
   */
  hydrateFromJournal: (messageId: string, journal: ExecutionJournal) => void;
  /**
   * One-time migrate when `message_start` stamps `serverMessageId`: move the
   * execution slot from the client bubble id to the server turn id so pause and
   * resume share one key. Not a resume remount.
   */
  alignTurnKey: (fromId: string, toId: string) => void;
}

const EMPTY_EXEC: ExecutionRuntime = {
  plan: null,
  frames: [],
  playhead: null,
  status: "planning",
  debate: null,
  debateRounds: [],
  crossExamEnabled: false,
  debateOpening: null,
  debatePretrial: null,
  evidenceLedger: [],
  workerToolPhases: {},
  runProcesses: null,
  teamSynthesisPreview: null,
  coordinationWait: null,
  coordinationWaitStartedAt: null,
  executionDetached: null,
  deliveryStatus: null,
  userInterjections: [],
};

/**
 * True when a journal-built plan/frames are strictly ahead of the in-memory
 * slot. Same execution id; lexicographic (runs → agents → frames). Equal or
 * behind keeps memory so hydrate never rolls a live/SSE-ahead slot back.
 */
function journalIsNewerThan(
  cur: ExecutionRuntime,
  journalPlan: ExecutionPlan,
  journalFrames: RunFrame[],
): boolean {
  const curPlan = cur.plan;
  if (!curPlan) return true;
  if (curPlan.id !== journalPlan.id) return false;
  if (journalPlan.runs.length !== curPlan.runs.length) {
    return journalPlan.runs.length > curPlan.runs.length;
  }
  if (journalPlan.agents.length !== curPlan.agents.length) {
    return journalPlan.agents.length > curPlan.agents.length;
  }
  return journalFrames.length > cur.frames.length;
}

/** Map a persisted turn's `finish_reason` to the terminal execution status the
 * fold needs (a journal is only stored for finished turns). */
function statusFromFinish(finishReason: string): ExecutionStatus {
  if (finishReason === "error") return "failed";
  if (finishReason === "cancelled" || finishReason === "interrupted")
    return "cancelled";
  // 挂起即收口 (②): a turn finalized AT a durable checkpoint carries finish_reason=paused;
  // its graph stayed paused (the resume card drives it), so a hydrate must keep it paused
  // rather than collapse it to "completed" (mirrors the conformance fold's FINISH_TO_STATUS).
  if (finishReason === "paused") return "paused";
  return "completed";
}

/**
 * The execution runtime of an assistant message, never undefined (empty
 * default). Use this for imperative reads (`getState`, tests); components
 * subscribe via {@link useProjectedExecution} / {@link useActiveExecField}
 * (scoped to the in-context message) so a conversation switch re-renders.
 */
export function execRuntime(
  state: ExecutionState,
  messageId: string | null | undefined,
): ExecutionRuntime {
  return (messageId ? state.byId[messageId] : undefined) ?? EMPTY_EXEC;
}

/**
 * True when the projected graph still has a run in pending/running — the CEO's
 * turn ended (message_end) but its team keeps running detached-hosted in the
 * background (coordination.turn_detached). The live handler holds the graph at
 * `running` instead of collapsing it to `completed`; the run-终态 reconcile in
 * {@link ExecutionState.recordFrame}/{@link ExecutionState.recordFrames} settles
 * it when the last worker's terminal frame lands (delivered via re-attach replay /
 * cross-turn append). No plan or no runs → false (nothing in flight to wait on, so
 * message_end 照常收口). Sibling of the private `runsAllSettled` reconcile check —
 * NOT its exact negation (both are false on a 0-run graph). */
export function hasUnsettledRuns(runtime: ExecutionRuntime): boolean {
  if (!runtime.plan) return false;
  const exec = projectExecution(
    runtime.plan,
    runtime.frames,
    runtime.status,
    runtime.debate,
    runtime.debateRounds,
    runtime.crossExamEnabled,
    runtime.debateOpening,
  );
  return exec.runs.some(
    (r) => r.status === "pending" || r.status === "running",
  );
}

export const useExecutionStore = create<ExecutionState>((set, get) => {
  /** Patch one message's runtime slice, lazily created from empty. */
  const patchExec = (
    messageId: string,
    update: (cur: ExecutionRuntime) => Partial<ExecutionRuntime> | null,
  ) =>
    set((state) => {
      const cur = state.byId[messageId] ?? EMPTY_EXEC;
      const patch = update(cur);
      if (patch === null) return {};
      return { byId: { ...state.byId, [messageId]: { ...cur, ...patch } } };
    });

  return {
    byId: {},

    startExecution: (plan, messageId) =>
      patchExec(messageId, () => ({
        plan: ensureDelegateBatchStamps(plan),
        frames: [],
        playhead: null,
        status: "running",
        debate: null,
        debateRounds: [],
        crossExamEnabled: false,
        debateOpening: null,
        debatePretrial: null,
        evidenceLedger: [],
        workerToolPhases: {},
        runProcesses: null,
        teamSynthesisPreview: null,
        coordinationWait: null,
        coordinationWaitStartedAt: null,
        executionDetached: null,
        deliveryStatus: null,
        userInterjections: [],
      })),

    ingestPlan: (plan, messageId) => {
      const cur = execRuntime(get(), messageId).plan;
      // Different turn / first batch → fresh start (resets frames).
      if (!cur || cur.id !== plan.id) {
        get().startExecution(plan, messageId);
        return;
      }
      // Same execution → an incremental delegate batch: merge in unseen
      // agents/runs while keeping the existing frame stream and playhead.
      patchExec(messageId, () => ({
        plan: mergePlanInto(cur, plan),
        status: "running",
      }));
    },

    clearExecution: (messageId) =>
      patchExec(messageId, () => ({ ...EMPTY_EXEC })),

    // Frames only carry meaning inside an execution; ignore stray run/tool facts
    // from the single-agent path (no plan declared).
    recordFrame: (frame, messageId) => {
      patchExec(messageId, (cur) =>
        cur.plan ? { frames: [...cur.frames, frame] } : null,
      );
      // 跨回合同图追加：宿主卡不靠追加回合 message_end 收口，按 run 终态 reconcile。
      const rt = execRuntime(get(), messageId);
      if (
        rt.plan &&
        rt.status === "running" &&
        runsAllSettled(
          rt.plan,
          rt.frames,
          rt.status,
          rt.debate,
          rt.debateRounds,
          rt.crossExamEnabled,
          rt.debateOpening,
        )
      ) {
        get().setStatus("completed", messageId);
      }
    },

    recordFrames: (frames, messageId) => {
      patchExec(messageId, (cur) =>
        cur.plan && frames.length
          ? { frames: [...cur.frames, ...frames] }
          : null,
      );
      if (frames.length === 0) return;
      const rt = execRuntime(get(), messageId);
      if (
        rt.plan &&
        rt.status === "running" &&
        runsAllSettled(
          rt.plan,
          rt.frames,
          rt.status,
          rt.debate,
          rt.debateRounds,
          rt.crossExamEnabled,
          rt.debateOpening,
        )
      ) {
        get().setStatus("completed", messageId);
      }
    },

    recordDebateResult: (debate, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan
          ? {
              debate,
              // 收场全量权威；缺字段（老 journal）保留 live 累积。
              ...(Array.isArray(debate.evidence_ledger)
                ? { evidenceLedger: debate.evidence_ledger }
                : {}),
            }
          : null,
      ),

    recordDebateRound: (round, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan
          ? { debateRounds: upsertDebateRound(cur.debateRounds, round) }
          : null,
      ),

    recordEvidenceLedgerDelta: (delta, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan && delta.length
          ? {
              evidenceLedger: mergeEvidenceLedger(cur.evidenceLedger, delta),
            }
          : null,
      ),

    /** Sticky-OR the场级质询开关（来自 debate_round_started.cross_exam_enabled）。 */
    recordCrossExamEnabled: (enabled, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan && enabled && !cur.crossExamEnabled
          ? { crossExamEnabled: true }
          : null,
      ),

    /** Sticky 首个非空主持人开场白（来自 debate_round_started.opening）；后续空串不覆盖。 */
    recordDebateOpening: (opening, messageId) =>
      patchExec(messageId, (cur) => {
        const trimmed = opening.trim();
        if (!cur.plan || !trimmed || cur.debateOpening) return null;
        return { debateOpening: trimmed };
      }),

    recordDebatePretrial: (type, payload, messageId) =>
      patchExec(messageId, (cur) => {
        if (!cur.plan) return null;
        const next = foldDebatePretrial(cur.debatePretrial, type, payload);
        return next === cur.debatePretrial ? null : { debatePretrial: next };
      }),

    setWorkerToolPhase: (payload, messageId) => {
      if (!payload.run_id) return;
      patchExec(messageId, (cur) => ({
        workerToolPhases: {
          ...cur.workerToolPhases,
          [payload.run_id as string]: {
            phase: payload.phase,
            toolName: payload.tool_name,
          },
        },
      }));
    },

    clearWorkerToolPhase: (runId, messageId) =>
      patchExec(messageId, (cur) => {
        if (!cur.workerToolPhases[runId]) return null;
        const { [runId]: _, ...rest } = cur.workerToolPhases;
        return { workerToolPhases: rest };
      }),

    setTeamSynthesisPreview: (preview, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan ? { teamSynthesisPreview: preview } : null,
      ),

    setCoordinationWait: (wait, messageId) =>
      patchExec(messageId, (cur) => {
        if (!cur.plan) return null;
        if (wait == null || wait.waiting === false) {
          if (
            cur.coordinationWait == null &&
            cur.coordinationWaitStartedAt == null
          ) {
            return null;
          }
          return { coordinationWait: null, coordinationWaitStartedAt: null };
        }
        return {
          coordinationWait: wait,
          // Heartbeats refresh completed/total; keep the segment clock.
          coordinationWaitStartedAt:
            cur.coordinationWaitStartedAt ?? Date.now(),
        };
      }),

    setExecutionDetached: (detached, messageId) =>
      patchExec(messageId, (cur) => {
        if (!cur.plan) return null;
        if (detached == null) {
          return cur.executionDetached == null
            ? null
            : { executionDetached: null };
        }
        // D3: stamp 后台运行中 and clear live tool chrome so nodes do not freeze on
        // 「正在生成 Write file · N 字」after the arming turn detaches.
        return {
          executionDetached: detached,
          workerToolPhases: {},
        };
      }),

    setDeliveryStatus: (status, messageId) =>
      patchExec(messageId, (cur) =>
        cur.plan ? { deliveryStatus: status } : null,
      ),

    upsertUserInterjection: (item, messageId) =>
      patchExec(messageId, (cur) => {
        if (!cur.plan) return null;
        const list = [...cur.userInterjections];
        const idx = list.findIndex(
          (x) => x.interjectionId === item.interjectionId,
        );
        if (idx < 0) list.push(item);
        else list[idx] = item;
        return { userInterjections: list };
      }),

    setStatus: (status, messageId) =>
      patchExec(messageId, (cur) => {
        // Terminal / paused turns clear live wait + background chrome (EPHEMERAL).
        if (
          status === "completed" ||
          status === "failed" ||
          status === "cancelled" ||
          status === "paused"
        ) {
          return {
            status,
            coordinationWait: null,
            coordinationWaitStartedAt: null,
            executionDetached: null,
          };
        }
        return cur.status === status ? null : { status };
      }),

    setPlayhead: (index, messageId) =>
      patchExec(messageId, () => ({ playhead: index })),

    goLive: (messageId) => patchExec(messageId, () => ({ playhead: null })),

    hydrateFromJournal: (messageId, journal) =>
      set((state) => {
        let plan: ExecutionPlan | null = null;
        const frames: RunFrame[] = [];
        let debate: DebateResultPayload | null = null;
        let debateRounds: DebateNarrativeRound[] = [];
        let crossExamEnabled = false;
        let debateOpening: string | null = null;
        let debatePretrial: DebatePretrialState | null = null;
        let evidenceLedger: EvidenceLedgerEntry[] = [];
        let teamSynthesisPreview: TeamSynthesisPreviewPayload | null = null;
        let deliveryStatus: DeliveryStatusPayload | null = null;
        const userInterjections: UserInterjection[] = [];
        const interjectionIndex = new Map<string, number>();
        for (const event of journal.events) {
          if (event.type === "run_plan") {
            const next = planFromRunPlan(event.payload as RunPlanPayload);
            plan = plan
              ? mergePlanInto(plan, next)
              : ensureDelegateBatchStamps(next);
          } else if (event.type === "debate_result") {
            // 回合级单事件（非 frame）：直接捕获，回放与直播经同一 slot 渲染辩论视图。
            debate = event.payload as DebateResultPayload;
            if (Array.isArray(debate.evidence_ledger)) {
              evidenceLedger = debate.evidence_ledger;
            }
          } else if (event.type === "user_interjection") {
            const p = event.payload as {
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
            if (!iid) continue;
            const attachments = (p.attachments ?? [])
              .filter(
                (
                  a,
                ): a is {
                  name: string;
                  workspace_path?: string;
                  binary?: boolean;
                } => typeof a.name === "string" && Boolean(a.name.trim()),
              )
              .map((a) => ({
                name: a.name.trim(),
                workspacePath:
                  typeof a.workspace_path === "string" &&
                  a.workspace_path.trim()
                    ? a.workspace_path
                    : undefined,
                binary: Boolean(a.binary),
              }));
            const leaf: UserInterjection = {
              interjectionId: iid,
              executionId: p.execution_id || "",
              content: p.content || "",
              status: p.status || "delivered",
              note: typeof p.note === "string" ? p.note : null,
              ...(attachments.length > 0 ? { attachments } : {}),
            };
            const idx = interjectionIndex.get(iid);
            if (idx === undefined) {
              interjectionIndex.set(iid, userInterjections.length);
              userInterjections.push(leaf);
            } else {
              userInterjections[idx] = leaf;
            }
          } else if (
            event.type === "debate_pretrial_started" ||
            event.type === "debate_pretrial_orders" ||
            event.type === "debate_pretrial_progress" ||
            event.type === "debate_pretrial_completed"
          ) {
            debatePretrial = foldDebatePretrial(
              debatePretrial,
              event.type,
              event.payload,
            );
          } else if (event.type === "debate_round_started") {
            // P2 DURABLE：刷新后从 journal 重建辩论进行态（与 live recordDebateRound 同 fold）。
            const p = event.payload as DebateRoundStartedPayload;
            if (p.cross_exam_enabled === true) crossExamEnabled = true;
            const rawOpening = (p.opening ?? "").trim();
            if (rawOpening && !debateOpening) debateOpening = rawOpening;
            debateRounds = upsertDebateRound(debateRounds, {
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
          } else if (event.type === "debate_round") {
            const p = event.payload as DebateRoundPayload;
            debateRounds = upsertDebateRound(debateRounds, {
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
            if (p.evidence_ledger_delta?.length) {
              evidenceLedger = mergeEvidenceLedger(
                evidenceLedger,
                p.evidence_ledger_delta,
              );
            }
          } else if (event.type === "team_synthesis_preview") {
            // P2 DURABLE：同 key 保最新（后写覆盖）；刷新后 StatusStrip 可重建。
            teamSynthesisPreview = event.payload as TeamSynthesisPreviewPayload;
          } else if (event.type === "delivery_status") {
            // DURABLE：同 execution_id 保最新（后写覆盖）；刷新后交付状态卡可重建。
            deliveryStatus = event.payload as DeliveryStatusPayload;
          } else {
            const frame = frameFromEvent(event);
            if (frame) frames.push(frame);
          }
        }
        // No run_plan in the journal → nothing to draw (single-agent / stray).
        if (!plan) return {};
        const cur = state.byId[messageId] ?? EMPTY_EXEC;
        // Newer-wins: catch up after missed graph_append; never roll live back.
        if (!journalIsNewerThan(cur, plan, frames)) return {};
        return {
          byId: {
            ...state.byId,
            [messageId]: {
              plan,
              frames,
              playhead: null,
              status: statusFromFinish(journal.finishReason),
              debate,
              debateRounds,
              crossExamEnabled,
              debateOpening,
              debatePretrial,
              evidenceLedger,
              workerToolPhases: {},
              runProcesses: journal.runProcesses ?? null,
              teamSynthesisPreview,
              coordinationWait: null,
              coordinationWaitStartedAt: null,
              executionDetached: null,
              deliveryStatus,
              userInterjections,
            },
          },
        };
      }),

    alignTurnKey: (fromId, toId) =>
      set((state) => {
        if (!fromId || !toId || fromId === toId) return {};
        const from = state.byId[fromId];
        if (!from) return {};
        const to = state.byId[toId];
        // Prefer the destination if it already has a plan; only move when empty.
        if (to?.plan) {
          const { [fromId]: _, ...rest } = state.byId;
          return { byId: rest };
        }
        const { [fromId]: _, ...rest } = state.byId;
        return { byId: { ...rest, [toId]: from } };
      }),
  };
});

// CEO 气泡「消息道」标量 fold — content / reasoning / process / citations。
// 生产 store（conversation.ts）与协议巡检（conformanceFold.ts）共用，与
// processTimeline.ts 一起保证 live / reload / golden 三路径同源。

import {
  INTERACTION_BY_KIND,
  type InteractionKind,
  type TimelineMarkerDef,
  defFromRequiredEvent,
  wireFor,
} from "@/stores/interactions/registry";
import type {
  Citation,
  ProcessStep,
  ResetReason,
  ToolUseEndPayload,
  ToolUseProgressPayload,
  ToolUseStartPayload,
} from "@/types/events";
import {
  appendApprovalStep,
  appendAskStep,
  appendCheckpointStep,
  appendContentStep,
  appendDelegationAuthorizationStep,
  appendEscalationStep,
  appendGraphAppendStep,
  appendPlanReviewStep,
  appendReasoningStep,
  appendReworkStep,
  appendStageCardStep,
  appendTeamPreviewStep,
  appendTeamStep,
  appendToolStep,
  dropTrailingContentSteps,
  promoteScalarContentIntoProcess,
  resolveToolStep,
  resolveToolStepPhase,
} from "./processTimeline";

export interface MessageLaneState {
  content: string;
  reasoning: string;
  process: ProcessStep[];
  citations: Citation[];
}

export function messageLaneFromMessage(msg: {
  content: string;
  reasoning?: string;
  process?: ProcessStep[];
  citations?: Citation[];
}): MessageLaneState {
  return {
    content: msg.content,
    reasoning: msg.reasoning ?? "",
    process: msg.process ?? [],
    citations: msg.citations ?? [],
  };
}

export function foldContentDelta(
  state: MessageLaneState,
  delta: string,
): MessageLaneState {
  const d = delta || "";
  if (!d) return state;
  return {
    ...state,
    content: state.content + d,
    process: appendContentStep(state.process, d),
  };
}

/** 草稿丢弃（`content_reset`）：清正文标量 + 弹掉尾部 content 步。仅
 * `reason === "finish_guard"`（交付前核验回炉）折出「引用/格式核验后已重写」rework chip；
 * 其余 reason（retry / soft_gate / ask_user / …）只清正文、不留痕——LLM 网络重试、
 * 软门控打回等基础设施信号不是核验重写（误报根治，镜像后端 oracle）。 */
export function foldContentReset(
  state: MessageLaneState,
  reason: ResetReason,
): MessageLaneState {
  const cleared = dropTrailingContentSteps(state.process);
  return {
    ...state,
    content: "",
    process: reason === "finish_guard" ? appendReworkStep(cleared) : cleared,
  };
}

export function foldReasoningDelta(
  state: MessageLaneState,
  delta: string,
): MessageLaneState {
  const d = delta || "";
  if (!d) return state;
  return {
    ...state,
    reasoning: state.reasoning + d,
    process: appendReasoningStep(state.process, d),
  };
}

export function foldToolUseStart(
  state: MessageLaneState,
  payload: ToolUseStartPayload,
): MessageLaneState {
  const process = appendToolStep(state.process, payload);
  return process === state.process ? state : { ...state, process };
}

export function foldToolUseEnd(
  state: MessageLaneState,
  payload: ToolUseEndPayload,
): MessageLaneState {
  const process = resolveToolStep(state.process, payload);
  if (!process || process === state.process) return state;
  return { ...state, process };
}

/** 工具执行阶段进度 (联网搜索前端展示优化): stamp a running tool step's coarse `phase` from a
 * `tool_use_progress` event. LIVE-ONLY — this event never rides a journal / conformance vector,
 * so `conformanceFold` no-ops it and the golden stays phase-less; only the production stream
 * calls this. No-op (same state) when no running step matches. */
export function foldToolUsePhase(
  state: MessageLaneState,
  payload: ToolUseProgressPayload,
): MessageLaneState {
  const process = resolveToolStepPhase(state.process, payload);
  if (!process || process === state.process) return state;
  return { ...state, process };
}

export function foldCitations(
  state: MessageLaneState,
  citations: Citation[],
): MessageLaneState {
  return { ...state, citations };
}

/** Fold a `run_plan` into the timeline as a `team` marker (协作图时间线落点) — the FIRST
 * plan of an execution fixes the collaboration graph's slot; later same-id batches no-op.
 * Promotes scalar CEO prose into a content step first so the graph slots below the lead-in. */
export function foldTeamMarker(
  state: MessageLaneState,
  executionId: string,
): MessageLaneState {
  const promoted = promoteScalarContentIntoProcess(
    state.process,
    state.content,
  );
  const process = appendTeamStep(promoted, executionId);
  if (process === state.process && promoted === state.process) return state;
  return { ...state, process };
}

/** Fold a `graph_append` event into the appending turn's timeline as an anchor chip. */
export function foldGraphAppendMarker(
  state: MessageLaneState,
  executionId: string,
  hostMessageId: string,
  addedCount: number,
  actId?: string | null,
  actKind?: string | null,
  authorizedBy?: string | null,
): MessageLaneState {
  const process = appendGraphAppendStep(
    state.process,
    executionId,
    hostMessageId,
    addedCount,
    actId,
    actKind,
    authorizedBy,
  );
  return process === state.process ? state : { ...state, process };
}

/** Fold any registered interaction timeline marker (registry-driven). */
export function foldInteractionTimelineMarker(
  state: MessageLaneState,
  marker: TimelineMarkerDef,
  id: string,
): MessageLaneState {
  if (marker.absorbTrailingContent) {
    const clearedProcess = dropTrailingContentSteps(state.process);
    const process = appendMarkerStep(clearedProcess, marker, id);
    if (
      process === state.process &&
      clearedProcess === state.process &&
      !state.content
    ) {
      return state;
    }
    return { ...state, content: "", process };
  }
  const process = appendMarkerStep(state.process, marker, id);
  return process === state.process ? state : { ...state, process };
}

function appendMarkerStep(
  process: ProcessStep[] | undefined,
  marker: TimelineMarkerDef,
  id: string,
): ProcessStep[] {
  switch (marker.processKind) {
    case "checkpoint":
      return appendCheckpointStep(process, id);
    case "ask":
      return appendAskStep(process, id);
    case "plan_review":
      return appendPlanReviewStep(process, id);
    case "team_preview":
      return appendTeamPreviewStep(process, id);
    case "escalation":
      return appendEscalationStep(process, id);
    case "approval":
      return appendApprovalStep(process, id);
    case "delegation_authorization":
      return appendDelegationAuthorizationStep(process, id);
    case "stage_card":
      return appendStageCardStep(process, id);
  }
}

/** Registry invariant: these fixed-kind fold helpers only exist for kinds that
 * declare a timeline marker — fail fast if the registry row ever loses it. */
function requiredTimeline(kind: InteractionKind): TimelineMarkerDef {
  const def = INTERACTION_BY_KIND[kind].timeline;
  if (!def) {
    throw new Error(`interaction kind "${kind}" has no timeline marker def`);
  }
  return def;
}

/** Fold a `checkpoint_required` into the timeline as a positional `checkpoint` marker.
 * Also absorbs same-round CEO prose into the card (mirrors backend ``content_reset`` on
 * a successful blocking ``ask_user``) so streamed text never duplicates the card. */
export function foldCheckpointMarker(
  state: MessageLaneState,
  checkpointId: string,
): MessageLaneState {
  return foldInteractionTimelineMarker(
    state,
    requiredTimeline("ask_user"),
    checkpointId,
  );
}

/** Fold a `question_posted` into the timeline as a positional `ask` marker. */
export function foldAskMarker(
  state: MessageLaneState,
  askId: string,
): MessageLaneState {
  return foldInteractionTimelineMarker(
    state,
    requiredTimeline("question_posted"),
    askId,
  );
}

/** Fold a `plan_review_required` into the timeline as a positional `plan_review` marker. */
export function foldPlanReviewMarker(
  state: MessageLaneState,
  checkpointId: string,
): MessageLaneState {
  return foldInteractionTimelineMarker(
    state,
    requiredTimeline("plan_review"),
    checkpointId,
  );
}

/** Fold a `team_preview_required` into the timeline as a positional `team_preview` marker. */
export function foldTeamPreviewMarker(
  state: MessageLaneState,
  checkpointId: string,
): MessageLaneState {
  return foldInteractionTimelineMarker(
    state,
    requiredTimeline("team_preview"),
    checkpointId,
  );
}

/** Process steps that mirror journal content/reasoning/tool lanes (not markers). */
function isSettledProcessStep(step: ProcessStep): boolean {
  return (
    step.kind === "content" ||
    step.kind === "reasoning" ||
    step.kind === "tool" ||
    step.kind === "rework"
  );
}

/** Markers whose product order sits before `team` (insertBeforeTeam). */
function isBeforeTeamMarker(step: ProcessStep): boolean {
  return (
    step.kind === "team_preview" || step.kind === "delegation_authorization"
  );
}

/**
 * Fold journal events before `endExclusive` into the settled (non-marker) prefix
 * length that should precede a `team` / `graph_append` slot.
 */
function foldSettledPrefix(
  events: ReadonlyArray<{ type: string; payload?: unknown }>,
  endExclusive: number,
): { count: number; sawSettledEvent: boolean } {
  let steps: ProcessStep[] = [];
  let sawSettledEvent = false;
  for (let i = 0; i < endExclusive; i++) {
    const ev = events[i];
    const payload = (ev.payload ?? {}) as Record<string, unknown>;
    switch (ev.type) {
      case "content_delta": {
        const delta = typeof payload.delta === "string" ? payload.delta : "";
        if (!delta) break;
        sawSettledEvent = true;
        steps = appendContentStep(steps, delta);
        break;
      }
      case "reasoning_delta": {
        const delta = typeof payload.delta === "string" ? payload.delta : "";
        if (!delta) break;
        sawSettledEvent = true;
        steps = appendReasoningStep(steps, delta);
        break;
      }
      case "content_reset": {
        sawSettledEvent = true;
        const cleared = dropTrailingContentSteps(steps);
        steps =
          payload.reason === "finish_guard"
            ? appendReworkStep(cleared)
            : cleared;
        break;
      }
      case "tool_use_start": {
        const next = appendToolStep(
          steps,
          payload as unknown as ToolUseStartPayload,
        );
        if (next !== steps) sawSettledEvent = true;
        steps = next;
        break;
      }
      case "tool_use_end": {
        const next = resolveToolStep(
          steps,
          payload as unknown as ToolUseEndPayload,
        );
        if (next) steps = next;
        break;
      }
      default:
        break;
    }
  }
  return { count: steps.length, sawSettledEvent };
}

/**
 * Journal-relative insert index for a missing `team` / `graph_append` marker.
 *
 * Counts settled steps implied by events before the marker, then maps that onto
 * the persisted process (skipping any already-present markers in between). When
 * the journal slice has no settled events but process already carries content
 * (minimal test / truncated events), falls back to append — same as legacy.
 *
 * `advancePastBeforeTeam`: after the settled prefix, skip `team_preview` /
 * `delegation_authorization` so product order stays 开工卡 → 协作图.
 */
function journalMarkerInsertIndex(
  process: ProcessStep[],
  events: ReadonlyArray<{ type: string; payload?: unknown }>,
  endExclusive: number,
  advancePastBeforeTeam: boolean,
): number {
  const { count, sawSettledEvent } = foldSettledPrefix(events, endExclusive);
  // No content_delta/tool slice before the marker, but process already has settled
  // steps (progressive ``process_*`` journals omit deltas from ``runs.events``):
  // - ``team`` (advancePastBeforeTeam): pin at start — post-plan 进展/终稿 must stay
  //   below the graph (legacy missing ``process_team`` hydrate).
  // - ``graph_append``: keep append — intro content often precedes the anchor.
  if (!sawSettledEvent && process.some(isSettledProcessStep)) {
    return advancePastBeforeTeam ? 0 : process.length;
  }
  let insertAt: number;
  if (count <= 0) {
    insertAt = 0;
  } else {
    let seen = 0;
    insertAt = process.length;
    for (let i = 0; i < process.length; i++) {
      if (!isSettledProcessStep(process[i])) continue;
      seen++;
      if (seen === count) {
        insertAt = i + 1;
        break;
      }
    }
  }
  if (advancePastBeforeTeam) {
    while (insertAt < process.length && isBeforeTeamMarker(process[insertAt])) {
      insertAt++;
    }
  }
  return insertAt;
}

/** Reload 补标记（时间线一期）: backfill every positional marker the journal implies
 * into a persisted `process[]` — `run_plan` → `team`，`*_required` → registry marker
 * (insertBeforeTeam 语义由 appendTeamPreviewStep 内建)。保证不变量「有交互卡必有时间线
 * 标记」在重载后成立（底部堆叠回退已废除，缺标记的卡会整段消失）。
 *
 * 纯补标记：绝不吞正文 —— absorbTrailingContent 只属于 live 时刻（事件到来时尾部
 * content 是同回合被吞的草稿）；重载的 process 是终态，resolved 后 CEO 的收尾正文
 * 必须保留。全部 append* 自带 dedup no-op，后端已写标记时原样返回。
 *
 * `team` / `graph_append` 按 journal 相对时序插入（禁止一律尾部 append），避免队后
 * 进展/终稿 content 被挤到图上方。 */
export function ensureTimelineMarkersFromJournal(
  process: ProcessStep[] | undefined,
  events: ReadonlyArray<{ type: string; payload?: unknown }>,
): ProcessStep[] {
  let steps = process ?? [];
  for (let i = 0; i < events.length; i++) {
    const ev = events[i];
    const payload = (ev.payload ?? {}) as Record<string, unknown>;
    if (ev.type === "graph_append") {
      const executionId = payload.execution_id;
      const hostMessageId = payload.host_message_id;
      const addedCount = Number(payload.added_count ?? 0);
      const actId = typeof payload.act_id === "string" ? payload.act_id : null;
      const actKind =
        typeof payload.act_kind === "string" ? payload.act_kind : null;
      const authorizedBy =
        typeof payload.authorized_by === "string"
          ? payload.authorized_by
          : null;
      if (
        typeof executionId === "string" &&
        executionId &&
        typeof hostMessageId === "string" &&
        hostMessageId
      ) {
        const at = journalMarkerInsertIndex(steps, events, i, false);
        steps = appendGraphAppendStep(
          steps,
          executionId,
          hostMessageId,
          addedCount,
          actId,
          actKind,
          authorizedBy,
          at,
        );
      }
      continue;
    }
    if (ev.type === "run_plan") {
      // 跨回合同图追加：生长 run_plan 带 host_message_id，不在追加回合插 team。
      if (payload.host_message_id) continue;
      const executionId = payload.execution_id;
      if (typeof executionId === "string" && executionId) {
        const at = journalMarkerInsertIndex(steps, events, i, true);
        steps = appendTeamStep(steps, executionId, at);
      }
      continue;
    }
    // Raised 非阻塞升级：不走 interaction registry required 路径，仍须补标记（D1/D6）。
    if (ev.type === "run_escalation") {
      const eid = payload.escalation_id;
      if (typeof eid === "string" && eid) {
        steps = appendEscalationStep(steps, eid);
      }
      continue;
    }
    const def = defFromRequiredEvent(ev.type);
    if (!def?.timeline) continue;
    const id = payload[wireFor(def.kind).idField];
    if (typeof id !== "string" || !id) continue;
    steps = appendMarkerStep(steps, def.timeline, id);
  }
  return steps;
}

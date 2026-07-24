import { toCeoReview } from "@/lib/ceoReview";
import { parseCheckpointIntent } from "@/lib/checkpointIntent";
import type {
  CheckpointDisplay,
  NonBlockingAskDisplay,
  PlanReviewDisplay,
  TeamPreviewDisplay,
} from "@/stores/conversation/types";
import type {
  AskAssumption,
  AskQuestion,
  AskStyleOption,
  PlanReviewPending,
  PlanReviewStep,
} from "@/types/events";
import type { InteractionKind } from "@/types/interactionExt";
import { mapEntryResolution } from "./mapResolution";
import { useInteractionStore } from "./store";
import type { InteractionEntry } from "./types";

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function arr<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

/** View-model for a pending approval card (replaces legacy PendingApproval). */
export interface ApprovalView {
  approvalId: string;
  conversationId: string;
  toolCallId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  resolving: boolean;
}

/** View-model for a pending delegation-authorization card. */
export interface DelegationAuthView {
  authorizationId: string;
  conversationId: string;
  executionId: string;
  workers: Array<{ role: string; task: string }>;
  tools: string[];
  resolving: boolean;
}

export function entryToCheckpoint(e: InteractionEntry): CheckpointDisplay {
  const p = e.payload;
  const settlement = mapEntryResolution(e);
  return {
    id: e.id,
    question: str(p.question),
    context: str(p.context),
    assumptions: arr<AskAssumption>(p.assumptions),
    questions: arr<AskQuestion>(p.questions),
    styleOptions: arr<AskStyleOption>(p.style_options ?? p.styleOptions),
    intent: parseCheckpointIntent(p.intent),
    ...settlement,
    selected:
      settlement.status === "resolved"
        ? arr<string>(e.resolution?.selected)
        : [],
  };
}

export function entryToNonBlockingAsk(
  e: InteractionEntry,
): NonBlockingAskDisplay {
  const p = e.payload;
  return {
    id: e.id,
    question: str(p.question),
    context: str(p.context),
    assumptions: arr<AskAssumption>(p.assumptions),
    questions: arr<AskQuestion>(p.questions),
    styleOptions: arr<AskStyleOption>(p.style_options ?? p.styleOptions),
  };
}

export function entryToPlanReview(e: InteractionEntry): PlanReviewDisplay {
  const p = e.payload;
  return {
    id: e.id,
    steps: arr<PlanReviewStep>(p.steps),
    pending: arr<PlanReviewPending>(p.pending),
    ...mapEntryResolution(e),
    // 主 Agent 把关摘要：live SSE 与 journal 冷加载同走本映射（absent → undefined）。
    ceoReview: toCeoReview(p.ceo_review),
  };
}

export function entryToTeamPreview(e: InteractionEntry): TeamPreviewDisplay {
  const p = e.payload;
  const primitiveRaw = str(p.primitive, "delegate");
  return {
    id: e.id,
    primitive: primitiveRaw === "debate" ? "debate" : "delegate",
    workers: arr<{
      run_id: string;
      role: string;
      task?: string;
      depends_on?: string[];
      debate?: boolean;
    }>(p.workers).map((w) => ({
      run_id: w.run_id,
      role: w.role,
      task: w.task ?? "",
      depends_on: w.depends_on ?? [],
      debate: Boolean(w.debate),
    })),
    tools: arr<string>(p.tools),
    motion: str(p.motion),
    form: str(p.form),
    sides: arr<{
      key: string;
      name: string;
      stance: string;
      is_subject?: boolean;
    }>(p.sides).map((s) => ({
      key: s.key,
      name: s.name,
      stance: s.stance,
      ...(s.is_subject ? { is_subject: true } : {}),
    })),
    maxRounds: typeof p.max_rounds === "number" ? p.max_rounds : 0,
    thorough: p.thorough !== false,
    offerResearchFirst: Boolean(p.offer_research_first),
    researchFirstRecommended: Boolean(p.research_first_recommended),
    ...mapEntryResolution(e),
  };
}

export function entryToApproval(e: InteractionEntry): ApprovalView {
  const p = e.payload;
  return {
    approvalId: e.id,
    conversationId: e.conversationId,
    toolCallId: str(p.tool_call_id, e.id),
    toolName: str(p.tool_name),
    arguments: (p.arguments ?? {}) as Record<string, unknown>,
    resolving: e.status === "submitting",
  };
}

export function entryToDelegationAuth(e: InteractionEntry): DelegationAuthView {
  const p = e.payload;
  return {
    authorizationId: e.id,
    conversationId: e.conversationId,
    executionId: str(p.execution_id),
    workers: arr<{ role: string; task: string }>(p.workers),
    tools: arr<string>(p.tools),
    resolving: e.status === "submitting",
  };
}

function matchesMessage(
  e: InteractionEntry,
  conversationId: string,
  messageId: string,
): boolean {
  if (e.conversationId !== conversationId) return false;
  if (!e.messageId || !messageId) return true;
  return e.messageId === messageId;
}

export function listMessageEntries(
  conversationId: string,
  messageId: string,
  kinds?: InteractionKind[],
): InteractionEntry[] {
  const out: InteractionEntry[] = [];
  for (const e of useInteractionStore.getState().byId.values()) {
    if (!matchesMessage(e, conversationId, messageId)) continue;
    if (kinds && !kinds.includes(e.kind)) continue;
    out.push(e);
  }
  return out;
}

export function messageCheckpoints(
  conversationId: string,
  messageId: string,
): CheckpointDisplay[] {
  return listMessageEntries(conversationId, messageId, ["ask_user"]).map(
    entryToCheckpoint,
  );
}

export function messageNonBlockingAsks(
  conversationId: string,
  messageId: string,
): NonBlockingAskDisplay[] {
  return listMessageEntries(conversationId, messageId, ["question_posted"]).map(
    entryToNonBlockingAsk,
  );
}

export function messagePlanReviews(
  conversationId: string,
  messageId: string,
): PlanReviewDisplay[] {
  return listMessageEntries(conversationId, messageId, ["plan_review"]).map(
    entryToPlanReview,
  );
}

export function messageTeamPreviews(
  conversationId: string,
  messageId: string,
): TeamPreviewDisplay[] {
  return listMessageEntries(conversationId, messageId, ["team_preview"]).map(
    entryToTeamPreview,
  );
}

/** Whether a tool is covered by an active grant_delegation for this conversation. */
export function isToolGranted(
  conversationId: string,
  toolName: string,
): boolean {
  for (const e of useInteractionStore.getState().byId.values()) {
    if (e.conversationId !== conversationId) continue;
    if (e.kind !== "delegation_authorization") continue;
    if (e.status !== "resolved") continue;
    const decision = e.resolution?.decision;
    if (decision !== "grant_delegation") continue;
    const tools = arr<string>(e.payload.tools);
    if (tools.includes(toolName)) return true;
  }
  return false;
}

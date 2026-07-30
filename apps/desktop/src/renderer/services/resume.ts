import { hasLocalEngine } from "@/lib/capabilities";
import { api } from "@/services/api";
import { getRuntime } from "@/stores/conversation";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import {
  entryToCheckpoint,
  entryToPlanReview,
  entryToTeamPreview,
  useInteractionStore,
} from "@/stores/interactions";
import {
  type PausedTurnEntry,
  type ResumeOrigin,
  usePausedTurnStore,
} from "@/stores/pausedTurns";
import type { components } from "@/types/api.generated";
import type { SidecarUnsyncedTurnSummary } from "@shared/sidecar-contract";

type PausedTurnSummary = components["schemas"]["PausedTurnSummary"];
type TurnRecoveryResponse = components["schemas"]["TurnRecoveryResponse"];
type PendingInteractionSummary =
  components["schemas"]["PendingInteractionSummary"];

/**
 * Conversation recovery snapshot on reopen.
 * Desktop splits sidecar vs cloud facts; hydrate selects branch from facts,
 * never from `resolveSidecarRoot` (routing intent / React Query cache).
 */
export interface ConversationRecovery {
  sidecarLive: boolean;
  cloudLive: boolean;
  pausedCount: number;
  /** Sidecar-only: outbox ready / dead-open summaries for D5 projection. */
  unsynced: SidecarUnsyncedTurnSummary[];
  /** Sidecar-only: live turn key when `sidecarLive`. */
  turnId?: string;
}

/** Local hydrate path when main-process facts say so (D6 二次修订). */
export function shouldHydrateLocalRecovery(r: ConversationRecovery): boolean {
  return r.sidecarLive || r.unsynced.length > 0 || r.pausedCount > 0;
}

/** Local turn still looks open (recovery `live_running` can lag the message window). */
function localTurnActive(conversationId: string): boolean {
  const rt = getRuntime(conversationId);
  if (rt.isGenerating) return true;
  const last = [...rt.messages].reverse().find((m) => m.role === "assistant");
  if (!last) return false;
  return (
    last.isStreaming === true ||
    last.status === "running" ||
    last.finishReason === "paused"
  );
}

function hydratePendingInteractions(
  conversationId: string,
  items: PendingInteractionSummary[],
  liveRunning: boolean,
): void {
  useInteractionStore.getState().hydratePending(
    conversationId,
    items.map((i) => ({
      kind: i.kind,
      id: i.id,
      messageId: i.message_id,
      payload: i.payload ?? {},
    })),
    {
      liveRunning: liveRunning || localTurnActive(conversationId),
    },
  );
}

function asPendingInteractions(
  res: TurnRecoveryResponse,
): PendingInteractionSummary[] {
  const items = res.pending_interactions ?? [];
  return items.filter(
    (i): i is PendingInteractionSummary =>
      !!i &&
      typeof i.id === "string" &&
      typeof i.kind === "string" &&
      typeof i.message_id === "string",
  );
}

/**
 * Merge paused frames by message_id (sidecar wins on collision), tagging each
 * frame with its durable origin so resume routing stays correct for mixed
 * cloud+sidecar sessions (never a single conversation-wide origin).
 */
function mergePausedWithOrigin(
  sidecar: PausedTurnSummary[],
  cloud: PausedTurnSummary[],
): PausedTurnEntry[] {
  const byId = new Map<string, PausedTurnEntry>();
  for (const p of cloud) {
    if (p?.message_id) byId.set(p.message_id, { summary: p, origin: "server" });
  }
  for (const p of sidecar) {
    if (p?.message_id)
      byId.set(p.message_id, { summary: p, origin: "sidecar" });
  }
  return [...byId.values()];
}

async function loadCloudRecovery(conversationId: string): Promise<{
  cloudLive: boolean;
  paused: PausedTurnSummary[];
  pending: PendingInteractionSummary[];
}> {
  const res = await api.get<TurnRecoveryResponse>(
    `/v1/conversations/${conversationId}/recovery`,
  );
  return {
    cloudLive: Boolean(res.live_running),
    paused: (res.paused ?? []) as PausedTurnSummary[],
    pending: asPendingInteractions(res),
  };
}

/**
 * Load a conversation's recovery state into the store on reopen (best-effort).
 *
 * Desktop (`hasLocalEngine`): unconditionally query local recovery IPC **and**
 * cloud GET /recovery in parallel; failures do not drag each other.
 * Web: cloud-only (unchanged).
 */
export async function loadRecovery(
  conversationId: string,
): Promise<ConversationRecovery> {
  if (!hasLocalEngine()) {
    try {
      const cloud = await loadCloudRecovery(conversationId);
      usePausedTurnStore.getState().setForConversation(
        conversationId,
        cloud.paused.map((summary) => ({
          summary,
          origin: "server" as const,
        })),
      );
      hydratePendingInteractions(
        conversationId,
        cloud.pending,
        cloud.cloudLive,
      );
      return {
        sidecarLive: false,
        cloudLive: cloud.cloudLive,
        pausedCount: cloud.paused.length,
        unsynced: [],
      };
    } catch {
      return {
        sidecarLive: false,
        cloudLive: false,
        pausedCount: 0,
        unsynced: [],
      };
    }
  }

  let sidecarLive = false;
  let turnId: string | undefined;
  let unsynced: SidecarUnsyncedTurnSummary[] = [];
  let sidecarPaused: PausedTurnSummary[] = [];
  let cloudLive = false;
  let cloudPaused: PausedTurnSummary[] = [];
  let cloudPending: PendingInteractionSummary[] | null = null;

  const localP = window.sidecarApi
    .recovery({ conversationId })
    .then((recovery) => {
      sidecarLive = recovery.liveRunning;
      turnId = recovery.turnId;
      unsynced = recovery.unsynced ?? [];
      sidecarPaused = (recovery.paused ?? []) as unknown as PausedTurnSummary[];
    })
    .catch(() => {
      /* local failure must not block cloud */
    });

  const cloudP = loadCloudRecovery(conversationId)
    .then((cloud) => {
      cloudLive = cloud.cloudLive;
      cloudPaused = cloud.paused;
      cloudPending = cloud.pending;
    })
    .catch(() => {
      /* cloud failure must not block local */
    });

  await Promise.all([localP, cloudP]);

  // Apply after both facts land so live = cloud ∨ sidecar (early empty must
  // not wipe while either engine still has a live turn).
  if (cloudPending !== null) {
    hydratePendingInteractions(
      conversationId,
      cloudPending,
      cloudLive || sidecarLive,
    );
  }

  const merged = mergePausedWithOrigin(sidecarPaused, cloudPaused);
  usePausedTurnStore.getState().setForConversation(conversationId, merged);

  // Hot cards survive when a live turn will be attached (D6); only clear
  // when there is nothing to reattach — stale prompts would otherwise linger.
  if (!sidecarLive) {
    clearInteractionPrompts(conversationId);
  }

  return {
    sidecarLive,
    cloudLive,
    pausedCount: merged.length,
    unsynced,
    turnId,
  };
}

export function isClientOnlyResumeKey(
  conversationId: string,
  messageId: string,
): boolean {
  const assistant = getRuntime(conversationId).messages.find(
    (m) => m.role === "assistant" && m.id === messageId,
  );
  return assistant !== undefined && !assistant.serverMessageId;
}

/**
 * Resolve a resume POST key to the stamped server message id when possible.
 * If a pending card still hangs on the client bubble id, rekey it in place.
 */
export function resolveResumeMessageId(
  conversationId: string,
  messageId: string,
): string {
  const assistant = getRuntime(conversationId).messages.find(
    (m) =>
      m.role === "assistant" &&
      (m.id === messageId || m.serverMessageId === messageId),
  );
  const serverId = assistant?.serverMessageId;
  if (!serverId || serverId === messageId) return serverId ?? messageId;
  usePausedTurnStore.getState().rekeyMessageId(messageId, serverId);
  return serverId;
}

/**
 * Surface one durable resume card from InteractionStore pending cold kinds.
 * Resume key is the stamped `serverMessageId` only — without it, skip painting
 * so the UI never shows a clickable card that would 404 / trip the client-only
 * resume guard (aligns with pre-fallback live surface behavior).
 */
export function surfaceResumeFromAssistant(
  conversationId: string,
  assistant: { id: string; serverMessageId?: string },
  origin: ResumeOrigin,
  user?: { content?: string; id?: string },
): void {
  const resumeKey = assistant.serverMessageId;
  if (!resumeKey) return;
  const base = {
    messageId: resumeKey,
    conversationId,
    userMessage: user?.content ?? "",
    userMessageId: user?.id ?? "",
    origin,
  };

  const ix = useInteractionStore.getState();
  const pending = ix
    .listPending(conversationId, ["ask_user", "plan_review", "team_preview"])
    .filter(
      (e) =>
        !e.messageId ||
        e.messageId === assistant.id ||
        e.messageId === resumeKey,
    );

  const ask = pending.find((e) => e.kind === "ask_user");
  if (ask) {
    const cp = entryToCheckpoint(ask);
    usePausedTurnStore.getState().addLiveResume({
      ...base,
      checkpointId: cp.id,
      kind: "ask_user",
      steps: [],
      pending: [],
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: cp.question,
      context: cp.context,
      assumptions: cp.assumptions,
      questions: cp.questions,
      styleOptions: cp.styleOptions,
      formatOptions: cp.formatOptions,
      intent: cp.intent,
    });
    return;
  }
  const prEntry = pending.find((e) => e.kind === "plan_review");
  if (prEntry) {
    const pr = entryToPlanReview(prEntry);
    usePausedTurnStore.getState().addLiveResume({
      ...base,
      checkpointId: pr.id,
      kind: "plan_review",
      steps: pr.steps,
      pending: pr.pending,
      ceoReview: pr.ceoReview,
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: "",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      intent: "decision",
    });
    return;
  }
  const tpEntry = pending.find((e) => e.kind === "team_preview");
  if (tpEntry) {
    const tp = entryToTeamPreview(tpEntry);
    usePausedTurnStore.getState().addLiveResume({
      ...base,
      checkpointId: tp.id,
      kind: "team_preview",
      steps: [],
      pending: [],
      workers: tp.workers,
      tools: tp.tools ?? [],
      primitive: tp.primitive,
      motion: tp.motion,
      form: tp.form,
      sides: tp.sides,
      maxRounds: tp.maxRounds,
      thorough: tp.thorough,
      offerResearchFirst: tp.offerResearchFirst,
      researchFirstRecommended: tp.researchFirstRecommended,
      ...(tp.moderatorModel ? { moderatorModel: tp.moderatorModel } : {}),
      ...(tp.moderatorOrigin ? { moderatorOrigin: tp.moderatorOrigin } : {}),
      ...(tp.moderatorProviderId
        ? { moderatorProviderId: tp.moderatorProviderId }
        : {}),
      ...(tp.sameModelDebate ? { sameModelDebate: true } : {}),
      question: "",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      // team_preview is the kickoff card — not a mid-turn decision ask.
      intent: "kickoff",
    });
  }
}

export function surfaceResumeFromLiveTurn(
  conversationId: string,
  origin: ResumeOrigin,
): void {
  const messages = getRuntime(conversationId).messages;
  const turn = [...messages].reverse().find((m) => m.role === "assistant");
  if (!turn) return;
  const user = [...messages].reverse().find((m) => m.role === "user");
  surfaceResumeFromAssistant(
    conversationId,
    { id: turn.id, serverMessageId: turn.serverMessageId },
    origin,
    { content: user?.content, id: user?.id },
  );
}

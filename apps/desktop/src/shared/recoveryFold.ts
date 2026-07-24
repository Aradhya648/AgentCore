/**
 * Local recovery fold helpers (回合恢复状态机收口 · D2).
 *
 * Derives ``interrupted_after_decision`` from outbox journal facts — not from
 * ``unsynced.length`` or paused-frame presence. Shared by main-process recovery
 * IPC and renderer hydrate tests.
 */

export type GateKind = "ask_user" | "plan_review" | "team_preview";

export interface JournalEntry {
  kind?: string;
  type?: string;
  payload?: Record<string, unknown>;
  ts?: string | null;
}

export interface InterruptedAfterDecision {
  messageId: string;
  userMessageId: string;
  conversationId: string;
  settledKind: GateKind;
  checkpointId: string;
}

const GATE_REQUIRED: Record<string, GateKind> = {
  checkpoint_required: "ask_user",
  plan_review_required: "plan_review",
  team_preview_required: "team_preview",
};

const GATE_RESOLVED: Record<string, GateKind> = {
  checkpoint_resolved: "ask_user",
  plan_review_resolved: "plan_review",
  team_preview_resolved: "team_preview",
};

const TERMINAL_FINISH = new Set([
  "end_turn",
  "stop",
  "error",
  "length",
  "max_rounds",
]);

function eventKind(entry: JournalEntry): string {
  return String(entry.kind || entry.type || "");
}

function checkpointIdOf(payload: Record<string, unknown> | undefined): string {
  return String(payload?.checkpoint_id || "");
}

/** True when fold still has a cold-path gate awaiting settlement. */
export function hasColdGatePending(entries: JournalEntry[]): boolean {
  const pending = new Map<string, GateKind>();
  for (const entry of entries) {
    const kind = eventKind(entry);
    const payload = entry.payload || {};
    const required = GATE_REQUIRED[kind];
    if (required) {
      const id = checkpointIdOf(payload);
      if (id) pending.set(`${required}:${id}`, required);
      continue;
    }
    const resolved = GATE_RESOLVED[kind];
    if (resolved) {
      const id = checkpointIdOf(payload);
      if (id) pending.delete(`${resolved}:${id}`);
      continue;
    }
    if (kind === "interaction_orphaned") {
      const orphanKind = String(payload.kind || "");
      const orphanId = String(payload.interaction_id || "");
      if (orphanKind && orphanId) pending.delete(`${orphanKind}:${orphanId}`);
    }
  }
  return pending.size > 0;
}

/** Latest settled cold-path gate, if any. */
export function latestSettledGate(
  entries: JournalEntry[],
): { kind: GateKind; checkpointId: string } | null {
  let found: { kind: GateKind; checkpointId: string } | null = null;
  for (const entry of entries) {
    const resolved = GATE_RESOLVED[eventKind(entry)];
    if (!resolved) continue;
    const id = checkpointIdOf(entry.payload);
    if (id) found = { kind: resolved, checkpointId: id };
  }
  return found;
}

export function journalEntriesFromOutboxMap(
  journal: Record<string, unknown> | undefined | null,
): JournalEntry[] {
  if (!journal || typeof journal !== "object") return [];
  const keys = Object.keys(journal).sort((a, b) => {
    const ai = Number.parseInt(a, 10);
    const bi = Number.parseInt(b, 10);
    if (Number.isFinite(ai) && Number.isFinite(bi)) return ai - bi;
    return a.localeCompare(b);
  });
  const out: JournalEntry[] = [];
  for (const k of keys) {
    const v = journal[k];
    if (v && typeof v === "object" && !Array.isArray(v)) {
      out.push(v as JournalEntry);
    }
  }
  return out;
}

/**
 * Derive interrupted_after_decision for one outbox record.
 *
 * Conditions: fold has no cold pending, a settlement exists, turn is not
 * terminally finished, and the turn is not currently live.
 */
export function deriveInterruptedAfterDecision(input: {
  conversationId: string;
  userMessageId: string;
  messageId: string | null | undefined;
  finishReason: string | null | undefined;
  journal: Record<string, unknown> | undefined | null;
  liveMessageId?: string | null;
}): InterruptedAfterDecision | null {
  const messageId = (input.messageId || "").trim();
  if (!messageId) return null;
  if (input.liveMessageId && input.liveMessageId === messageId) return null;
  const finish = (input.finishReason || "").trim();
  if (finish && TERMINAL_FINISH.has(finish)) return null;

  const entries = journalEntriesFromOutboxMap(input.journal);
  if (hasColdGatePending(entries)) return null;
  const settled = latestSettledGate(entries);
  if (!settled) return null;

  return {
    messageId,
    userMessageId: input.userMessageId,
    conversationId: input.conversationId,
    settledKind: settled.kind,
    checkpointId: settled.checkpointId,
  };
}

/**
 * True when salvage/writeback must keep the outbox row open for frameless continue.
 *
 * Conservative (aligned with Python ``OutboxStore.salvage``): any settlement on a
 * non-terminal turn → retain, even if a later cold gate is pending. Projection
 * (``deriveInterruptedAfterDecision``) still suppresses the interrupt card when
 * a new pending exists; retain only protects local journal + resume_frame.
 */
export function shouldRetainOpenForContinue(input: {
  finishReason: string | null | undefined;
  journal: Record<string, unknown> | undefined | null;
}): boolean {
  const finish = (input.finishReason || "").trim();
  if (finish && TERMINAL_FINISH.has(finish)) return false;
  const entries = journalEntriesFromOutboxMap(input.journal);
  return latestSettledGate(entries) !== null;
}

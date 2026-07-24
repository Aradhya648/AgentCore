/**
 * Project unsynced sidecar outbox summaries into the conversation slice (D5).
 *
 * Adapts each summary into BackendMessage shape → `toMessage` → `addMessage`.
 * Skips ids already present (cloud window wins). Marks ready rows synced_pending.
 */
import { type BackendMessage, toMessage } from "@/services/messages";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import type { ProcessStep, SSEEvent, UsageBreakdown } from "@/types/events";
import type { SidecarUnsyncedTurnSummary } from "@shared/sidecar-contract";

function createdAtIso(updatedAt: number): string {
  // Outbox `updated_at` is Unix seconds (Python time.time()).
  const ms = updatedAt > 1e12 ? updatedAt : updatedAt * 1000;
  return new Date(ms || Date.now()).toISOString();
}

function summaryToBackendMessages(
  conversationId: string,
  u: SidecarUnsyncedTurnSummary,
): BackendMessage[] {
  const created = createdAtIso(u.updated_at);
  const status =
    u.phase === "ready" ? ("complete" as const) : ("incomplete" as const);
  const hasUsage =
    u.input_tokens ||
    u.output_tokens ||
    u.reasoning_tokens ||
    u.cache_hit_tokens ||
    u.cache_miss_tokens;
  const usage: UsageBreakdown | null = hasUsage
    ? ({
        input: u.input_tokens,
        output: u.output_tokens,
        reasoning: u.reasoning_tokens,
        cache_hit: u.cache_hit_tokens,
        cache_miss: u.cache_miss_tokens,
      } as UsageBreakdown)
    : null;

  const user: BackendMessage = {
    id: u.user_message_id,
    conversation_id: conversationId,
    role: "user",
    content: u.user_message,
    reasoning_content: null,
    trace_id: u.trace_id || null,
    created_at: created,
  };

  const assistantId = u.message_id || `assistant-${u.user_message_id}`;
  const events = (u.runs?.events ?? []) as unknown as SSEEvent[];
  const process = (u.runs?.process ?? null) as ProcessStep[] | null;
  const runProcesses = (u.runs?.run_processes ?? null) as Record<
    string,
    ProcessStep[]
  > | null;
  const assistant: BackendMessage = {
    id: assistantId,
    conversation_id: conversationId,
    role: "assistant",
    content: u.content,
    reasoning_content: u.reasoning_content,
    trace_id: u.trace_id || null,
    citations: u.citations?.length
      ? u.citations.map((c) => ({
          url: c.url,
          title: c.title,
          snippet: c.snippet,
          site: c.site,
        }))
      : undefined,
    runs: u.runs
      ? {
          events,
          finish_reason: u.runs.finish_reason ?? u.finish_reason ?? null,
          process,
          run_processes: runProcesses,
        }
      : u.finish_reason
        ? { events: [], finish_reason: u.finish_reason }
        : null,
    usage,
    status,
    created_at: created,
  };

  return [user, assistant];
}

/**
 * Append unsynced outbox turns (sorted by updated_at ascending by recovery).
 * Idempotent on message id.
 */
export function projectUnsyncedTurns(
  conversationId: string,
  unsynced: SidecarUnsyncedTurnSummary[],
): void {
  if (!unsynced.length) return;
  const store = useConversationStore.getState();
  const existing = new Set(
    getRuntime(conversationId).messages.map((m) => m.id),
  );

  for (const u of unsynced) {
    const rows = summaryToBackendMessages(conversationId, u);
    for (const row of rows) {
      if (existing.has(row.id)) continue;
      const msg = toMessage(row);
      // Open ghost (sidecar died mid-turn): surface as interrupted, not streaming.
      if (
        row.role === "assistant" &&
        u.phase === "open" &&
        msg.status === "incomplete"
      ) {
        msg.isStreaming = false;
        msg.finishReason = msg.finishReason ?? "interrupted";
      }
      store.addMessage(msg, conversationId);
      existing.add(row.id);
    }
    if (u.phase === "ready") {
      store.setTurnSyncStatus(
        u.user_message_id,
        "synced_pending",
        conversationId,
      );
    }
  }
}

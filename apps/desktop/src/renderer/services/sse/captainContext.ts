import type { ContextBlockWire } from "@/types/events";

/** Per-conversation captain (CEO) run id, captured from its `run_started` (kind=captain).
 * Lets the captain's `run_context` route TURN-LEVEL onto the message bubble (上下文传递可视化
 * 通道①) instead of a graph node — the captain is the bubble above the graph, present even in
 * pure chat where no execution slot exists. Overwritten each turn (run ids are per-turn UUIDs),
 * so a worker's run_context never matches. */
const captainRunByConv = new Map<string, string>();

/** Per-conversation captain context accumulator (上下文传递可视化 通道①+⑤). The captain emits
 * `run_context` more than once a turn — the opening (system/history/request) then once per
 * delegate batch (team_result readback) — so its received context GROWS. We ACCUMULATE here and
 * push the full list to the store (a plain REPLACE), which keeps a reconnect/replay idempotent:
 * `message_start` resets this (the attach replay re-sends it first), so re-folding the same
 * events rebuilds the identical list instead of doubling it. */
const captainCtxByConv = new Map<string, ContextBlockWire[]>();

export function resetCaptainContext(conversationId: string): void {
  captainCtxByConv.delete(conversationId);
}

export function setCaptainRunId(conversationId: string, runId: string): void {
  captainRunByConv.set(conversationId, runId);
}

export function isCaptainRun(conversationId: string, runId: string): boolean {
  return captainRunByConv.get(conversationId) === runId;
}

/** Append blocks to the captain accumulator and return the grown list. */
export function growCaptainContext(
  conversationId: string,
  blocks: ContextBlockWire[],
): ContextBlockWire[] {
  const grown = [...(captainCtxByConv.get(conversationId) ?? []), ...blocks];
  captainCtxByConv.set(conversationId, grown);
  return grown;
}

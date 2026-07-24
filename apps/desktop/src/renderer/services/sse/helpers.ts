import {
  assistantProjectionId,
  getRuntime,
  lastAssistantProjectionId,
} from "@/stores/conversation";
import type { ProcessStep } from "@/types/events";

/** Optional routing hint from an SSE payload (跨回合同图追加). */
export type ExecRouteHint = {
  host_message_id?: string;
  execution_id?: string;
};

/** Active divert: growth frames for this conversation land on the host slot. */
const growthHostByConversation = new Map<string, string>();

/** Resolve a server/client message id to the execution slot key (`serverMessageId ?? id`). */
export function resolveExecSlotId(
  conversationId: string,
  messageRef: string,
): string {
  const ref = messageRef.trim();
  if (!ref) return ref;
  const messages = getRuntime(conversationId).messages;
  const hit = messages.find((m) => m.id === ref || m.serverMessageId === ref);
  return hit ? assistantProjectionId(hit) : ref;
}

/** Find the host assistant bubble for an execution (message.executionId or process markers). */
export function findHostSlotForExecution(
  conversationId: string,
  executionId: string,
): string | null {
  const eid = executionId.trim();
  if (!eid) return null;
  const messages = getRuntime(conversationId).messages;
  for (const m of messages) {
    if (m.role !== "assistant") continue;
    if (m.executionId === eid) return assistantProjectionId(m);
    const team = m.process?.find(
      (s): s is Extract<ProcessStep, { kind: "team" }> =>
        s.kind === "team" && s.execution_id === eid,
    );
    if (team) return assistantProjectionId(m);
  }
  return null;
}

/** Begin diverting growth frames to the host graph (set on `graph_append` / append `run_plan`). */
export function noteGraphAppendRedirect(
  conversationId: string,
  hostMessageId: string,
): void {
  const slot = resolveExecSlotId(conversationId, hostMessageId);
  if (slot) growthHostByConversation.set(conversationId, slot);
}

/** Clear divert after the appending turn ends (message_end / error). */
export function clearGraphAppendRedirect(conversationId: string): void {
  growthHostByConversation.delete(conversationId);
}

/** Test helper. */
export function clearAllGraphAppendRedirects(): void {
  growthHostByConversation.clear();
}

/**
 * Resolve the execution slot for **growth** facts (run_plan / run_* / worker tools…).
 *
 * Priority: explicit `host_message_id` → `execution_id` host lookup → active divert
 * → latest assistant.
 */
export function execMessageId(
  conversationId: string,
  hint?: ExecRouteHint | null,
): string | null {
  const hostHint =
    typeof hint?.host_message_id === "string"
      ? hint.host_message_id.trim()
      : "";
  if (hostHint) return resolveExecSlotId(conversationId, hostHint);

  const eid =
    typeof hint?.execution_id === "string" ? hint.execution_id.trim() : "";
  if (eid) {
    const mapped = findHostSlotForExecution(conversationId, eid);
    if (mapped) return mapped;
  }

  const sticky = growthHostByConversation.get(conversationId);
  if (sticky) return sticky;

  return lastAssistantProjectionId(getRuntime(conversationId).messages);
}

/** CEO-lane slot (latest assistant) — never diverted to a host graph. */
export function ceoMessageId(conversationId: string): string | null {
  return lastAssistantProjectionId(getRuntime(conversationId).messages);
}

/** Pull routing fields from an opaque SSE payload. */
export function routeHintFromPayload(payload: unknown): ExecRouteHint | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  // `host_turn_id` is the execution_detached / execution_completed host key.
  const host =
    typeof p.host_message_id === "string"
      ? p.host_message_id
      : typeof p.host_turn_id === "string"
        ? p.host_turn_id
        : undefined;
  const execution =
    typeof p.execution_id === "string" ? p.execution_id : undefined;
  if (!host && !execution) return null;
  return { host_message_id: host, execution_id: execution };
}

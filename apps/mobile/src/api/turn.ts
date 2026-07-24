// Turn-lifecycle JSON endpoints for the mobile client (执行与请求解耦 C1 / 结构化挂起 2b).
//
// Plain-JSON companions to the SSE channels in stream.ts:
//   - stopConversation → explicitly cancel an in-flight detached run
//   - getRecovery      → one-shot reopen snapshot (is a detached run still live to 续看 +
//                        which turns are durably paused awaiting resume)
// The resume itself is SSE (stream.ts::resumeStream). REST DTOs track OpenAPI.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type SuspensionKind = Schemas["SuspensionKind"];
export type PausedTurnSummary = Schemas["PausedTurnSummary"];
export type PendingInteractionSummary = Schemas["PendingInteractionSummary"];

type StopTurnResponse = Schemas["StopTurnResponse"];
type TurnRecoveryResponse = Schemas["TurnRecoveryResponse"];

/**
 * Explicitly stop the conversation's in-flight turn (执行与请求解耦 C1 · slice 1a).
 *
 * Idempotent: returns whether a live run was actually signalled. HTTP / network
 * failures propagate so the UI can surface a visible retry (不再静默吞掉).
 */
export async function stopConversation(
  conversationId: string,
): Promise<boolean> {
  const res = await apiFetch(`/v1/conversations/${conversationId}/stop`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`停止失败 (${res.status})`);
  }
  const data = (await res.json()) as StopTurnResponse;
  return Boolean(data.stopped);
}

/** A conversation's reopen recovery snapshot — see {@link getRecovery}. */
export interface TurnRecovery {
  /** A detached in-flight run is still live to 续看 (实时重连续看 C1 · slice 1b): the
   *  caller may attach (GET .../stream) to replay + tail it. */
  liveRunning: boolean;
  /** Turns that durably paused at a plan_review / ask_user checkpoint then lost their
   *  stream (结构化挂起 2b), oldest-first. When non-empty the resume card is the single
   *  actionable surface, so the caller must NOT also attach. */
  paused: PausedTurnSummary[];
  /** Hot-path interactions still awaiting settlement (journal fold · P1/P3). */
  pendingInteractions: PendingInteractionSummary[];
}

/**
 * One-shot recovery snapshot for a conversation reopen (recovery 统一, 对称 §18.2).
 *
 * Folds the two former reopen probes — is a detached run still live (1b)? are there
 * durably paused turns (2b)? — into ONE owner-gated read, so reopen picks a single
 * actionable surface without racing GET /paused against the GET /stream attach. A turn
 * parked at a checkpoint is BOTH live (its run parked, holding the workspace lock) and
 * durably paused (its frame persisted before the suspend await); surfacing both stacked a
 * live PauseCard on top of the durable ResumeCard for one pause. The caller attaches only
 * when `liveRunning` and `paused` is empty; otherwise the resume card is the sole surface.
 */
export async function getRecovery(
  conversationId: string,
): Promise<TurnRecovery> {
  const res = await apiFetch(`/v1/conversations/${conversationId}/recovery`);
  if (!res.ok) throw new Error(`加载恢复态失败 (${res.status})`);
  const data = (await res.json()) as TurnRecoveryResponse;
  return {
    liveRunning: Boolean(data.live_running),
    paused: data.paused ?? [],
    pendingInteractions: data.pending_interactions ?? [],
  };
}

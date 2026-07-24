import {
  isInteractionOrphanedError,
  submitInteraction,
} from "@/services/interactionSubmit";
import { useInteractionStore } from "@/stores/interactions";

export type EscalationUserDecision =
  | { kind: "answer"; answer: string }
  | { kind: "use_assumption" };

/**
 * POST the user's call on a worker's blocking escalate via the unified submit path.
 * 410 → orphaned 灰态; other failures reopen for retry.
 */
export async function decideEscalation(
  conversationId: string,
  escalationId: string,
  decision: EscalationUserDecision,
): Promise<"ok" | "orphaned" | "busy"> {
  try {
    return await submitInteraction({
      id: escalationId,
      kind: "escalation",
      conversationId,
      hotBody: {
        kind: "escalation",
        answer: decision.kind === "answer" ? decision.answer : "",
        use_assumption: decision.kind === "use_assumption",
      },
    });
  } catch (err) {
    if (isInteractionOrphanedError(err)) {
      useInteractionStore.getState().markOrphaned(escalationId);
      return "orphaned";
    }
    throw err;
  }
}

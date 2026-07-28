import {
  isInteractionOrphanedError,
  submitInteraction,
} from "@/services/interactionSubmit";
import { useInteractionStore } from "@/stores/interactions";

export type EscalationUserDecision =
  | { kind: "answer"; answer: string }
  | { kind: "use_assumption" }
  | { kind: "transfer_ownership" }
  | { kind: "keep_ownership" };

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
    const transfer = decision.kind === "transfer_ownership";
    const keep = decision.kind === "keep_ownership";
    return await submitInteraction({
      id: escalationId,
      kind: "escalation",
      conversationId,
      hotBody: {
        kind: "escalation",
        answer:
          decision.kind === "answer"
            ? decision.answer
            : transfer
              ? "移交写权给升级方"
              : keep
                ? "保持原主写权"
                : "",
        use_assumption: decision.kind === "use_assumption",
        transfer_ownership: transfer,
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

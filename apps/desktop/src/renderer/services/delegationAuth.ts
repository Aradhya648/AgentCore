import { notifyError } from "@/lib/toast";
import {
  isInteractionOrphanedError,
  submitInteraction,
  submitInteractionFeedback,
} from "@/services/interactionSubmit";
import {
  type DelegationAuthView,
  useInteractionStore,
} from "@/stores/interactions";
import type { DelegationAuthorizationDecision } from "@/types/events";

export type { DelegationAuthorizationDecision };

export type ResolveDelegationAuthorizationBody = {
  kind: "delegation_authorization";
  decision: DelegationAuthorizationDecision;
};

export async function resolveDelegationAuthorization(
  conversationId: string,
  authorizationId: string,
  decision: DelegationAuthorizationDecision,
): Promise<void> {
  await submitInteraction({
    id: authorizationId,
    kind: "delegation_authorization",
    conversationId,
    hotBody: { kind: "delegation_authorization", decision },
  });
}

export async function decideDelegationAuthorization(
  authorization: DelegationAuthView,
  decision: DelegationAuthorizationDecision,
): Promise<void> {
  const ix = useInteractionStore.getState();
  if (!ix.get(authorization.authorizationId)) {
    ix.upsertRequired({
      kind: "delegation_authorization",
      conversationId: authorization.conversationId,
      messageId: "",
      payload: {
        authorization_id: authorization.authorizationId,
        conversation_id: authorization.conversationId,
        execution_id: authorization.executionId,
        workers: authorization.workers,
        tools: authorization.tools,
      },
    });
  }
  try {
    const result = await submitInteraction({
      id: authorization.authorizationId,
      kind: "delegation_authorization",
      conversationId: authorization.conversationId,
      hotBody: { kind: "delegation_authorization", decision },
    });
    if (result !== "ok") {
      notifyError(submitInteractionFeedback(result));
    }
  } catch (err) {
    if (isInteractionOrphanedError(err)) {
      useInteractionStore
        .getState()
        .markOrphaned(authorization.authorizationId);
      return;
    }
    throw err;
  }
}

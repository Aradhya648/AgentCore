import { apiFetch } from "@/api/client";
// Settle a paused interaction over the LIVE SSE stream (交互式暂停放行).
//
// POST to the unified resolve endpoint wakes the awaiter on the open stream.
// REST body types track OpenAPI (cloud-only on mobile — no sidecar branch).
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

/** Settle a paused interaction — discriminated on `kind` (OpenAPI union).
 *
 * 挂起即收口 (②): `ask_user` / `plan_review` / `team_preview` settle via cold resume.
 * Hot path: approval / escalation / delegation_authorization / debate_round.
 */
export type ResolveInteractionBody =
  | Schemas["ResolveApprovalInteraction"]
  | Schemas["ResolveEscalationInteraction"]
  | Schemas["ResolveDelegationAuthorizationInteraction"];

/**
 * POST a paused interaction's answer; the live SSE stream resumes.
 * 404 is swallowed (stale interaction — stream terminal event settles UI).
 */
export async function resolveInteraction(
  conversationId: string,
  interactionId: string,
  body: ResolveInteractionBody,
): Promise<void> {
  const res = await apiFetch(
    `/v1/conversations/${conversationId}/interactions/${interactionId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(`放行失败 (${res.status})`);
  }
}

/**
 * 阻塞式求决策 (§4.5): the two calls a user can make on a worker's blocking escalation —
 * answer it, or 按假设继续 (degrade to the worker's stated assumption, == a timeout). UNLIKE
 * plan_review there is no 停止: ending the whole turn is the CEO `ask_user` job, not one
 * worker's escalation. Mirrors the desktop `decideEscalation` (services/escalation.ts).
 */
export type EscalationUserDecision =
  | { kind: "answer"; answer: string }
  | { kind: "use_assumption" };

/**
 * POST the user's call on a worker's blocking escalate to the SAME unified resolve endpoint
 * (keyed by `escalation_id`). The suspending tool's awaiter — never this route — emits
 * `escalation_resolved` on the live stream, which folds the run's pending escalation to
 * resolved/timeout and unmounts the card. A 404 (already closed) is swallowed by
 * {@link resolveInteraction}; any other failure propagates so the card can re-enable.
 */
export function decideEscalation(
  conversationId: string,
  escalationId: string,
  decision: EscalationUserDecision,
): Promise<void> {
  return resolveInteraction(conversationId, escalationId, {
    kind: "escalation",
    answer: decision.kind === "answer" ? decision.answer : "",
    use_assumption: decision.kind === "use_assumption",
  });
}

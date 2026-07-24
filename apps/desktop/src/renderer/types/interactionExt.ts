/**
 * Desktop interaction-store kinds beyond the hot-path recovery summary.
 * Kind union + wire table: backend InteractionKind / INTERACTION_KIND_SPECS →
 * `@agentcore/contract-types` (`pnpm gen:types`). Store kinds = user-facing
 * subset (excludes bridge-only `client_tool`).
 */

export type {
  UserInteractionKind as InteractionKind,
  InteractionKind as BridgeInteractionKind,
} from "@agentcore/contract-types";

export type InteractionStatus =
  | "pending"
  | "submitting"
  | "resolved"
  | "orphaned";

/** New SSE fact: a pending interaction is no longer answerable. */
export interface InteractionOrphanedPayload {
  interaction_id: string;
  kind: import("@agentcore/contract-types").UserInteractionKind;
}

export const INTERACTION_ORPHANED_EVENT = "interaction_orphaned" as const;

export function isInteractionOrphanedEvent(type: string): boolean {
  return type === INTERACTION_ORPHANED_EVENT;
}

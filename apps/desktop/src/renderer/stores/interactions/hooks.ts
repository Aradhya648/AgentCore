import type {
  CheckpointDisplay,
  NonBlockingAskDisplay,
  PlanReviewDisplay,
  TeamPreviewDisplay,
} from "@/stores/conversation/types";
import { useMemo } from "react";
import {
  type ApprovalView,
  type DelegationAuthView,
  entryToApproval,
  entryToCheckpoint,
  entryToDelegationAuth,
  entryToNonBlockingAsk,
  entryToPlanReview,
  entryToTeamPreview,
} from "./adapters";
import { useInteractionStore } from "./store";
import type { InteractionEntry } from "./types";

function matchesMessage(
  e: InteractionEntry,
  conversationId: string,
  messageId: string,
): boolean {
  if (e.conversationId !== conversationId) return false;
  if (!e.messageId || !messageId) return true;
  return e.messageId === messageId;
}

/** Cold-path + compose cards anchored to one assistant message (inline timeline). */
export function useMessageInteractionCards(
  conversationId: string | null,
  messageId: string,
): {
  checkpoints: CheckpointDisplay[];
  nonBlockingAsks: NonBlockingAskDisplay[];
  planReviews: PlanReviewDisplay[];
  teamPreviews: TeamPreviewDisplay[];
} {
  const byId = useInteractionStore((s) => s.byId);
  return useMemo(() => {
    const checkpoints: CheckpointDisplay[] = [];
    const nonBlockingAsks: NonBlockingAskDisplay[] = [];
    const planReviews: PlanReviewDisplay[] = [];
    const teamPreviews: TeamPreviewDisplay[] = [];
    if (!conversationId) {
      return { checkpoints, nonBlockingAsks, planReviews, teamPreviews };
    }
    for (const e of byId.values()) {
      if (!matchesMessage(e, conversationId, messageId)) continue;
      if (e.kind === "ask_user") checkpoints.push(entryToCheckpoint(e));
      else if (e.kind === "question_posted")
        nonBlockingAsks.push(entryToNonBlockingAsk(e));
      else if (e.kind === "plan_review") planReviews.push(entryToPlanReview(e));
      else if (e.kind === "team_preview")
        teamPreviews.push(entryToTeamPreview(e));
    }
    return { checkpoints, nonBlockingAsks, planReviews, teamPreviews };
  }, [byId, conversationId, messageId]);
}

/** Pending (+ submitting) approval cards for the active conversation. */
export function usePendingApprovals(
  conversationId: string | null,
): ApprovalView[] {
  const byId = useInteractionStore((s) => s.byId);
  return useMemo(() => {
    if (!conversationId) return [];
    const out: ApprovalView[] = [];
    for (const e of byId.values()) {
      if (e.conversationId !== conversationId) continue;
      if (e.kind !== "approval") continue;
      if (e.status !== "pending" && e.status !== "submitting") continue;
      out.push(entryToApproval(e));
    }
    return out;
  }, [byId, conversationId]);
}

/** Orphaned approval entries for 已失效灰态. */
export function useOrphanedApprovals(conversationId: string | null) {
  const byId = useInteractionStore((s) => s.byId);
  return useMemo(() => {
    if (!conversationId) return [];
    const out: InteractionEntry[] = [];
    for (const e of byId.values()) {
      if (
        e.conversationId === conversationId &&
        e.kind === "approval" &&
        e.status === "orphaned"
      ) {
        out.push(e);
      }
    }
    return out;
  }, [byId, conversationId]);
}

export function usePendingDelegations(
  conversationId: string | null,
): DelegationAuthView[] {
  const byId = useInteractionStore((s) => s.byId);
  return useMemo(() => {
    if (!conversationId) return [];
    const out: DelegationAuthView[] = [];
    for (const e of byId.values()) {
      if (e.conversationId !== conversationId) continue;
      if (e.kind !== "delegation_authorization") continue;
      if (e.status !== "pending" && e.status !== "submitting") continue;
      out.push(entryToDelegationAuth(e));
    }
    return out;
  }, [byId, conversationId]);
}

export function useOrphanedDelegations(conversationId: string | null) {
  const byId = useInteractionStore((s) => s.byId);
  return useMemo(() => {
    if (!conversationId) return [];
    const out: InteractionEntry[] = [];
    for (const e of byId.values()) {
      if (
        e.conversationId === conversationId &&
        e.kind === "delegation_authorization" &&
        e.status === "orphaned"
      ) {
        out.push(e);
      }
    }
    return out;
  }, [byId, conversationId]);
}

/**
 * UI bindings for {@link INTERACTION_REGISTRY} — card components + cold-resume
 * renderers. Kept separate from the data registry to avoid React cycles in
 * store / fold modules.
 */

import { CheckpointCard } from "@/components/chat/CheckpointCard";
import { EscalationCard } from "@/components/chat/EscalationCard";
import {
  ApprovalTrace,
  DelegationAuthorizationTrace,
  StageCardTrace,
} from "@/components/chat/HotDecisionTrace";
import { NonBlockingAskCard } from "@/components/chat/NonBlockingAskCard";
import { OrphanedInteractionCard } from "@/components/chat/OrphanedInteractionCard";
import { PlanReviewCard } from "@/components/chat/PlanReviewCard";
import { TeamPreviewCard } from "@/components/chat/TeamPreviewCard";
import type {
  CheckpointDisplay,
  NonBlockingAskDisplay,
  PlanReviewDisplay,
  TeamPreviewDisplay,
} from "@/stores/conversation";
import { type RunEscalation, useMessageExecution } from "@/stores/execution";
import { useInteractionStore } from "@/stores/interactions";
import type { ReactNode } from "react";
import type { TimelineProcessKind } from "./registry";

export type TimelineCardBags = {
  checkpoints: CheckpointDisplay[];
  nonBlockingAsks: NonBlockingAskDisplay[];
  planReviews: PlanReviewDisplay[];
  teamPreviews: TeamPreviewDisplay[];
};

type TimelineNodeId = {
  checkpoint_id?: string;
  ask_id?: string;
  escalation_id?: string;
  approval_id?: string;
  authorization_id?: string;
  stage_card_id?: string;
};

export type TimelineRenderCtx = {
  messageId: string;
  conversationId: string | null;
  interactive: boolean;
};

/**
 * Render the inline decision card / 痕迹 for a timeline process marker, or null
 * when the matching display model is not yet hydrated (or pending 热审批痕迹).
 */
export function renderTimelineInteractionCard(
  processKind: TimelineProcessKind,
  node: TimelineNodeId,
  bags: TimelineCardBags,
  ctx?: TimelineRenderCtx,
): ReactNode {
  switch (processKind) {
    case "checkpoint": {
      const cp = bags.checkpoints.find((c) => c.id === node.checkpoint_id);
      return cp ? <CheckpointCard key={cp.id} checkpoint={cp} /> : null;
    }
    case "ask": {
      const ask = bags.nonBlockingAsks.find((a) => a.id === node.ask_id);
      return ask ? <NonBlockingAskCard key={ask.id} ask={ask} /> : null;
    }
    case "plan_review": {
      const pr = bags.planReviews.find((p) => p.id === node.checkpoint_id);
      return pr ? <PlanReviewCard key={pr.id} review={pr} /> : null;
    }
    case "team_preview": {
      const tp = bags.teamPreviews.find((p) => p.id === node.checkpoint_id);
      return tp ? (
        <TeamPreviewCard key={tp.id} preview={tp} messageId={ctx?.messageId} />
      ) : null;
    }
    case "escalation": {
      if (!ctx?.messageId || !node.escalation_id) return null;
      return (
        <EscalationTimelineSlot
          key={node.escalation_id}
          escalationId={node.escalation_id}
          messageId={ctx.messageId}
          conversationId={ctx.conversationId}
          interactive={ctx.interactive}
        />
      );
    }
    case "approval": {
      if (!node.approval_id) return null;
      return (
        <ApprovalTrace key={node.approval_id} approvalId={node.approval_id} />
      );
    }
    case "delegation_authorization": {
      if (!node.authorization_id) return null;
      return (
        <DelegationAuthorizationTrace
          key={node.authorization_id}
          authorizationId={node.authorization_id}
        />
      );
    }
    case "stage_card": {
      if (!node.stage_card_id) return null;
      return (
        <StageCardTrace
          key={node.stage_card_id}
          stageCardId={node.stage_card_id}
        />
      );
    }
  }
}

/** One escalation at its own timeline marker (统一时间线二期 D2). */
function EscalationTimelineSlot({
  escalationId,
  messageId,
  conversationId,
  interactive,
}: {
  escalationId: string;
  messageId: string;
  conversationId: string | null;
  interactive: boolean;
}) {
  const execution = useMessageExecution(messageId);
  const orphaned = useInteractionStore((s) => {
    const e = s.byId.get(escalationId);
    return e?.kind === "escalation" && e.status === "orphaned" ? e : null;
  });

  if (orphaned) {
    return (
      <OrphanedInteractionCard
        title="升级确认已失效"
        detail="该升级请求已不可答复（服务已重启或回合已结束）。"
      />
    );
  }

  if (!execution) return null;

  let found: { esc: RunEscalation; role: string } | null = null;
  for (const run of execution.runs) {
    const esc = run.escalations.find((e) => e.id === escalationId);
    if (esc) {
      const role =
        execution.agents.find((a) => a.id === run.agentId)?.role ?? run.agentId;
      found = { esc, role };
      break;
    }
  }
  if (!found) return null;

  return (
    <EscalationCard
      escalation={found.esc}
      role={found.role}
      conversationId={conversationId}
      interactive={interactive}
    />
  );
}

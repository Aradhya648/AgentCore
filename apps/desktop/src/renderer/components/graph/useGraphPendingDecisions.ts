/**
 * 图头行动条数据 hook（批 R3）：把一个回合的待拍板（node 级升级/检查点 + execution
 * 级审批/授权）聚合成 {@link GraphPendingDecision}[]。三宿主（内联/画布/全屏）共用。
 */

import type { Execution } from "@/stores/execution";
import { useInteractionStore } from "@/stores/interactions";
import { useMemo } from "react";
import {
  type GraphPendingDecision,
  type PendingInteractionRef,
  collectGraphPendingDecisions,
} from "./pendingDecisions";

export function useGraphPendingDecisions(
  execution: Execution | null | undefined,
  conversationId: string | null,
  messageId: string | null,
): GraphPendingDecision[] {
  const byId = useInteractionStore((s) => s.byId);
  const interactions = useMemo<PendingInteractionRef[]>(() => {
    const out: PendingInteractionRef[] = [];
    if (!conversationId) return out;
    for (const e of byId.values()) {
      if (e.conversationId !== conversationId) continue;
      // 宽松按回合匹配：交互缺 messageId（会话级）时也纳入（与 matchesMessage 一致）。
      if (messageId && e.messageId && e.messageId !== messageId) continue;
      if (e.status !== "pending" && e.status !== "submitting") continue;
      if (e.kind === "approval" || e.kind === "delegation_authorization") {
        out.push({ kind: e.kind, id: e.id });
      }
    }
    return out;
  }, [byId, conversationId, messageId]);

  return useMemo(
    () => collectGraphPendingDecisions(execution, interactions),
    [execution, interactions],
  );
}

export type { GraphPendingDecision };

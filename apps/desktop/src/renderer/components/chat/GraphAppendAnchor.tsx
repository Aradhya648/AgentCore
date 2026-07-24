import { actAuthorizedByLabel } from "@/components/graph/actAuthLabels";
import {
  assistantProjectionId,
  useActiveMessages,
  useConversationStore,
} from "@/stores/conversation";
import { useDisclosureStore } from "@/stores/disclosure";
import type { ActKind } from "@/stores/execution";
import { ArrowUp } from "lucide-react";

/** 开新幕（辩论）锚点文案；同幕补派维持「追加 N 名成员」。 */
export function graphAppendAnchorLabel(
  addedCount: number,
  actKind?: ActKind | string | null,
): string {
  const n = Math.max(0, addedCount | 0);
  if (actKind === "debate") {
    return `↑ 开辩论幕·${n} 人进场`;
  }
  return `↑ 已往上方协作图追加 ${n} 名成员`;
}

/**
 * 跨回合同图追加锚点条——追加回合只挂这条「↑ 已往上方协作图追加 N 名成员」，
 * 点击平滑滚回宿主协作图卡片并展开。开辩论幕时文案区分；authorizedBy 作副文案。
 */
export function GraphAppendAnchor({
  hostMessageId,
  addedCount,
  actKind,
  authorizedBy,
}: {
  hostMessageId: string;
  addedCount: number;
  actKind?: ActKind | string | null;
  authorizedBy?: string | null;
}) {
  const messages = useActiveMessages();
  const focusMessage = useConversationStore((s) => s.focusMessage);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const label = graphAppendAnchorLabel(addedCount, actKind);
  const authLabel = actAuthorizedByLabel(authorizedBy);

  return (
    <button
      type="button"
      data-testid="graph-append-anchor"
      onClick={() => {
        const host = messages.find(
          (m) => m.id === hostMessageId || m.serverMessageId === hostMessageId,
        );
        const focusId = host?.id ?? hostMessageId;
        const slotId = host ? assistantProjectionId(host) : hostMessageId;
        if (conversationId) {
          // 展开宿主内联协作图（默认展开时清掉「已收起」偏离值）。
          useDisclosureStore
            .getState()
            .setKey(`${conversationId}::${slotId}:inline-graph`, true, true);
        }
        focusMessage(focusId);
      }}
      className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-border bg-muted/40 px-2.5 py-1.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <ArrowUp size={14} className="shrink-0" aria-hidden />
      <span className="truncate">
        {label}
        {authLabel ? (
          <span className="text-xs opacity-80"> · {authLabel}</span>
        ) : null}
      </span>
    </button>
  );
}

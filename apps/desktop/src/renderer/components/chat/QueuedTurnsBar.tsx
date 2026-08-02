import { notifyError } from "@/lib/toast";
import { cancelQueuedTurn } from "@/services/turns/cancelQueuedTurn";
import { type QueuedTurnEntry, useQueuedTurns } from "@/stores/queuedTurns";
import { Loader2, X } from "lucide-react";
import { useState } from "react";

/**
 * 排队可见条：drain 前展示 FIFO 项，可按项取消（Stop ≠ 取消排队）。
 * 挂在 composer 上方，滚动离开气泡时仍可见。
 */
export function QueuedTurnsBar({
  conversationId,
}: {
  conversationId: string | null;
}) {
  const items = useQueuedTurns(conversationId);
  if (!conversationId || items.length === 0) return null;

  return (
    <div
      className="flex flex-col gap-1 px-1 pb-1"
      data-testid="queued-turns-bar"
      aria-live="polite"
    >
      {items.map((item) => (
        <QueuedTurnRow key={item.queueId} item={item} />
      ))}
    </div>
  );
}

function QueuedTurnRow({ item }: { item: QueuedTurnEntry }) {
  const [busy, setBusy] = useState(false);
  const preview =
    item.content.length > 48 ? `${item.content.slice(0, 48)}…` : item.content;

  const onCancel = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await cancelQueuedTurn(item.conversationId, item.queueId);
      // 成功 / 404 已在 cancelQueuedTurn 内本地清 store + 乐观气泡。
    } catch (err) {
      notifyError(err, "取消排队失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground"
      data-testid="queued-turn-row"
      data-queue-id={item.queueId}
    >
      <Loader2 size={12} className="shrink-0 animate-spin" aria-hidden />
      <span className="min-w-0 flex-1 truncate">
        排队中
        {item.queueDepth > 1
          ? `（第 ${item.position}/${item.queueDepth}）`
          : ""}
        ：{preview}
      </span>
      <button
        type="button"
        className="shrink-0 rounded-lg p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        aria-label="取消排队"
        title="取消排队"
        disabled={busy}
        onClick={() => void onCancel()}
      >
        <X size={12} />
      </button>
    </div>
  );
}

/**
 * 排队可见条：drain 前展示 FIFO 项，可按项取消（Stop ≠ 取消排队）。
 * 挂在 composer 上方，滚动离开气泡时仍可见。
 */
import { cancelQueuedTurn } from "@/api/turn";
import {
  type QueuedTurnEntry,
  removeQueuedTurn,
  useQueuedTurns,
} from "@/lib/queuedTurns";
import { Loader2, X } from "lucide-react";
import { useState } from "react";

export function QueuedTurnsBar({
  conversationId,
  onCancelled,
  onCancelFailed,
}: {
  conversationId: string | null;
  /** 取消成功 / 404 后：清气泡 + abort 该 mid-flight（由页面收口）。 */
  onCancelled: (entry: QueuedTurnEntry, outcome: "cancelled" | "gone") => void;
  onCancelFailed?: (message: string) => void;
}) {
  const items = useQueuedTurns(conversationId);
  if (!conversationId || items.length === 0) return null;

  return (
    <div
      className="queued-turns-bar"
      data-testid="queued-turns-bar"
      aria-live="polite"
    >
      {items.map((item) => (
        <QueuedTurnRow
          key={item.queueId}
          item={item}
          onCancelled={onCancelled}
          onCancelFailed={onCancelFailed}
        />
      ))}
    </div>
  );
}

function QueuedTurnRow({
  item,
  onCancelled,
  onCancelFailed,
}: {
  item: QueuedTurnEntry;
  onCancelled: (entry: QueuedTurnEntry, outcome: "cancelled" | "gone") => void;
  onCancelFailed?: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const preview =
    item.content.length > 48 ? `${item.content.slice(0, 48)}…` : item.content;

  const onCancel = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const outcome = await cancelQueuedTurn(item.conversationId, item.queueId);
      // 成功 / 404：本地清轻态（勿只靠 SSE）；abort 须在 API 成功后（见 onCancelled）。
      removeQueuedTurn(item.conversationId, item.queueId);
      onCancelled(item, outcome);
    } catch (err) {
      // 失败：不 abort、不摘 chip——避免「chip 在、连接已断」。
      onCancelFailed?.(err instanceof Error ? err.message : "取消排队失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="queued-turn-row"
      data-testid="queued-turn-row"
      data-queue-id={item.queueId}
    >
      <Loader2 size={12} className="queued-turn-spinner" aria-hidden />
      <span className="queued-turn-preview">
        排队中
        {item.queueDepth > 1
          ? `（第 ${item.position}/${item.queueDepth}）`
          : ""}
        {item.degradedFrom === "steer" ? " · 插话暂不可用" : ""}：{preview}
      </span>
      <button
        type="button"
        className="queue-cancel-btn"
        aria-label="取消排队"
        title="取消排队"
        disabled={busy}
        data-testid="queued-turn-cancel"
        onClick={() => void onCancel()}
      >
        <X size={12} />
      </button>
    </div>
  );
}

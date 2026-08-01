import {
  INTERJECTION_TONE_CLASS,
  interjectionStatusLabel,
  interjectionStatusTone,
} from "@/components/chat/interjectionStatus";
import type { UserInterjection } from "@/stores/execution";
import { useExecutionStore } from "@/stores/execution";

const EMPTY: readonly UserInterjection[] = [];

/**
 * S2：协调插话主时间线呈现——普通用户气泡 + 轻量状态标记。
 * 数据来自 execution.userInterjections（live SSE / journal hydrate），不伪造 Message 行。
 */
export function InterjectionTimeline({ messageId }: { messageId: string }) {
  const items = useExecutionStore(
    (s) => s.byId[messageId]?.userInterjections ?? EMPTY,
  );
  if (items.length === 0) return null;
  return (
    <div className="mt-4 space-y-4" data-testid="interjection-timeline">
      {items.map((item) => (
        <InterjectionUserBubble key={item.interjectionId} item={item} />
      ))}
    </div>
  );
}

function InterjectionUserBubble({ item }: { item: UserInterjection }) {
  const tone = interjectionStatusTone(item.status);
  const atts = item.attachments ?? [];
  return (
    <div
      className="flex flex-col items-end gap-1.5"
      data-testid={`interjection-bubble-${item.interjectionId}`}
    >
      {atts.length > 0 && (
        <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">
          {atts.map((a) => (
            <span
              key={`${item.interjectionId}:${a.name}`}
              className="max-w-full truncate rounded-lg border border-border/70 bg-muted/60 px-2 py-1 text-xs text-muted-foreground"
              title={a.workspacePath ?? a.name}
            >
              {a.name}
            </span>
          ))}
        </div>
      )}
      <div className="max-w-[80%] rounded-xl rounded-br-none bg-muted px-4 py-3 text-sm text-foreground">
        <p className="whitespace-pre-wrap break-words">{item.content}</p>
      </div>
      <span
        className={`inline-flex max-w-[80%] rounded-full border px-1.5 py-0.5 text-xs ${INTERJECTION_TONE_CLASS[tone]}`}
        data-testid={`interjection-status-${item.interjectionId}`}
      >
        {interjectionStatusLabel(item.status)}
      </span>
      {item.note ? (
        <p className="max-w-[80%] text-xs text-muted-foreground text-right">
          {item.note}
        </p>
      ) : null}
    </div>
  );
}

import {
  interjectionStatusLabel,
  interjectionStatusTone,
} from "@/lib/interjectionStatus";

export type InterjectionItem = {
  interjectionId: string;
  content: string;
  status: string;
  note?: string | null;
  attachments?: Array<{ name: string; workspacePath?: string }>;
};

/**
 * S2：协调插话主时间线——普通用户气泡 + 轻量状态（fold → userInterjections）。
 */
export function InterjectionBubbles({
  items,
}: {
  items: readonly InterjectionItem[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="interjection-timeline" data-testid="interjection-timeline">
      {items.map((item) => {
        const tone = interjectionStatusTone(item.status);
        const atts = item.attachments ?? [];
        return (
          <div
            key={item.interjectionId}
            className="interjection-turn"
            data-testid={`interjection-bubble-${item.interjectionId}`}
          >
            {atts.length > 0 ? (
              <div className="attach-chips">
                {atts.map((a) => (
                  <span
                    key={`${item.interjectionId}:${a.name}`}
                    className="attach-chip"
                    title={a.workspacePath ?? a.name}
                  >
                    {a.name}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="bubble user">{item.content}</div>
            <div
              className={`interjection-status tone-${tone}`}
              data-testid={`interjection-status-${item.interjectionId}`}
            >
              {interjectionStatusLabel(item.status)}
            </div>
            {item.note ? (
              <div className="interjection-note">{item.note}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

import {
  INTERJECTION_TONE_CLASS,
  interjectionStatusLabel,
  interjectionStatusTone,
} from "@/components/chat/interjectionStatus";
import type { UserInterjection } from "@/stores/execution";

/**
 * 团队块内插话追溯（S2：主叙事在主时间线 InterjectionTimeline；此处可折叠追溯）。
 * 四态文案与主时间线对齐；legacy delivered ≡ received。
 */
export function UserInterjectionsPanel({
  items,
}: {
  items: readonly UserInterjection[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5 border-t border-border/60 pt-2">
      <p className="text-xs text-muted-foreground">插话追溯</p>
      {items.map((item) => {
        const tone = interjectionStatusTone(item.status);
        const atts = item.attachments ?? [];
        return (
          <div
            key={item.interjectionId}
            className="rounded-lg border border-border/70 bg-muted/20 px-2.5 py-1.5"
          >
            <div className="flex items-start gap-2">
              <span
                className={`mt-0.5 shrink-0 rounded-full border px-1.5 py-0.5 text-xs ${INTERJECTION_TONE_CLASS[tone]}`}
              >
                {interjectionStatusLabel(item.status)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-muted-foreground whitespace-pre-wrap break-words line-clamp-2">
                  {item.content}
                </p>
                {atts.length > 0 ? (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {atts.map((a) => (
                      <span
                        key={`${item.interjectionId}:${a.name}`}
                        className="max-w-full truncate rounded-lg border border-border/70 bg-background/80 px-1.5 py-0.5 text-xs text-muted-foreground"
                        title={a.workspacePath ?? a.name}
                      >
                        {a.name}
                      </span>
                    ))}
                  </div>
                ) : null}
                {item.note ? (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {item.note}
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

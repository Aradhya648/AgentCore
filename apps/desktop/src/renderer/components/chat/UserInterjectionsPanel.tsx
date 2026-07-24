import type { UserInterjection } from "@/stores/execution";

/**
 * Lightweight mid-flight interjection rows inside the team block timeline.
 * Badge: 「已传达给团队」(delivered) vs 「已排队」(queued).
 * Attachment chips surface names only (path stays on the wire for agents).
 */
export function UserInterjectionsPanel({
  items,
}: {
  items: readonly UserInterjection[];
}) {
  if (items.length === 0) return null;
  return (
    <div className="mt-2 space-y-1.5 border-t border-border/60 pt-2">
      {items.map((item) => {
        const queued = item.status === "queued";
        const atts = item.attachments ?? [];
        return (
          <div
            key={item.interjectionId}
            className="rounded-lg border border-border/70 bg-muted/30 px-2.5 py-1.5"
          >
            <div className="flex items-start gap-2">
              <span
                className={`mt-0.5 shrink-0 rounded-full border px-1.5 py-0.5 text-xs ${
                  queued
                    ? "border-border bg-muted text-muted-foreground"
                    : "border-success/40 bg-success/10 text-success"
                }`}
              >
                {queued ? "已排队" : "已传达给团队"}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-foreground whitespace-pre-wrap break-words">
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

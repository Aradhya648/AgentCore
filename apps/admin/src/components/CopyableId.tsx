import { cn } from "@/lib/utils";
import { toast } from "sonner";

/** Click-to-copy mono id chip — used for conversation_id / trace_id in admin surfaces. */
export function CopyableId({
  value,
  label,
  display,
  className,
  titleHint,
}: {
  value: string;
  /** Toast label, e.g. "conversation_id" / "trace_id". */
  label: string;
  /** Optional truncated display; full `value` is always copied. */
  display?: string;
  className?: string;
  titleHint?: string;
}) {
  return (
    <button
      type="button"
      title={titleHint ?? `${value}（点击复制）`}
      onClick={(e) => {
        e.stopPropagation();
        void navigator.clipboard.writeText(value).then(
          () => toast.success(`${label} 已复制`),
          () => toast.error("复制失败"),
        );
      }}
      className={cn(
        "max-w-full truncate rounded bg-muted px-1.5 py-0.5 font-mono text-muted-foreground text-xs outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {display ?? value}
    </button>
  );
}

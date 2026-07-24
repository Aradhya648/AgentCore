/** Centered date pill between IM message groups (今天 / 昨天 / …). */
export function ChatDateDivider({ label }: { label: string }) {
  return (
    <div className="flex justify-center py-2">
      <span className="rounded-full bg-muted px-3 py-0.5 text-xs text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

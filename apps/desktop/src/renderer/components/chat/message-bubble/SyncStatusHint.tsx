import { SimpleTooltip } from "@/components/ui/tooltip";
import type { Message } from "@/stores/conversation";
import { Check, CloudOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** Delay before showing「待同步」so fast sync stays silent. */
export const PENDING_REVEAL_MS = 5000;

/**
 * Local-only outbox sync caption on optimistic bubbles (as-built: 前端 UX §一B).
 * Never serialized to SSE / REST / conformance.
 *
 * Silent success / explicit lag: suppress「待同步」for the first ~5s of
 * `synced_pending`; only flash「已同步」if pending was actually shown.
 */
export function SyncStatusHint({
  syncStatus,
  align = "start",
}: {
  syncStatus: Message["syncStatus"];
  align?: "start" | "end";
}) {
  const [pendingRevealed, setPendingRevealed] = useState(false);
  const pendingWasVisibleRef = useRef(false);

  useEffect(() => {
    if (syncStatus === "synced_pending") {
      setPendingRevealed(false);
      pendingWasVisibleRef.current = false;
      const id = window.setTimeout(() => {
        pendingWasVisibleRef.current = true;
        setPendingRevealed(true);
      }, PENDING_REVEAL_MS);
      return () => window.clearTimeout(id);
    }

    if (syncStatus !== "synced") {
      // Cleared / absent — reset for the next episode.
      setPendingRevealed(false);
      pendingWasVisibleRef.current = false;
    } else {
      setPendingRevealed(false);
    }
  }, [syncStatus]);

  if (!syncStatus) return null;

  const pending = syncStatus === "synced_pending";
  if (pending && !pendingRevealed) return null;
  if (!pending && !pendingWasVisibleRef.current) return null;

  const label = pending ? "待同步" : "已同步";
  const tip = pending ? "本机已保存，正在同步到云端" : "已同步到云端";

  return (
    <SimpleTooltip label={tip}>
      <span
        className={`inline-flex items-center gap-1 text-xs ${
          pending ? "text-muted-foreground" : "text-success"
        } ${align === "end" ? "justify-end" : ""}`}
        data-testid={`sync-status-${syncStatus}`}
        aria-label={label}
      >
        {pending ? <CloudOff size={12} /> : <Check size={12} />}
        {label}
      </span>
    </SimpleTooltip>
  );
}

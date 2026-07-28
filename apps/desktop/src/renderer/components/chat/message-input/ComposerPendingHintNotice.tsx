/**
 * Persistent weak hint above the composer while a decision card is waiting.
 * Send is not blocked here — confirm-on-send lives in useComposerSend.
 */
import { COMPOSER_PENDING_HINT } from "@/lib/composerPendingHint";

export function ComposerPendingHintNotice({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div
      aria-live="polite"
      data-testid="composer-pending-hint"
      className="flex items-center gap-1.5 px-4 pt-2 text-xs text-muted-foreground"
    >
      {COMPOSER_PENDING_HINT}
    </div>
  );
}

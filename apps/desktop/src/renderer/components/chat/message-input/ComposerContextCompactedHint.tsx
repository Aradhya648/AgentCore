/**
 * Session-field badge: earlier turns were folded into a rolling summary.
 * Flag-only — never shows summary text; not a MemoryUpdateCard.
 */
import { COMPOSER_CONTEXT_COMPACTED_HINT } from "@/lib/composerContextCompactedHint";

export function ComposerContextCompactedHint({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div
      aria-live="polite"
      data-testid="composer-context-compacted-hint"
      className="flex items-center gap-1.5 px-4 pt-2 text-xs text-muted-foreground"
    >
      {COMPOSER_CONTEXT_COMPACTED_HINT}
    </div>
  );
}

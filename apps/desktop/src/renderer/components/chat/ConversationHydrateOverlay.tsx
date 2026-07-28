import { Button } from "@/components/ui";
import { Loader2 } from "lucide-react";

export type ConversationHydratePhase = "loading" | "ready" | "error";

/**
 * Full-pane honest shell for persisted-conversation hydrate (诚实壳层 A).
 * Covers chat/canvas so a cold load never looks like an empty draft you can send into,
 * and a failed fetch without offline cache never looks like a blank conversation.
 */
export function ConversationHydrateOverlay({
  phase,
  onRetry,
}: {
  phase: ConversationHydratePhase;
  onRetry?: () => void;
}) {
  if (phase === "ready") return null;

  if (phase === "loading") {
    return (
      <output
        className="absolute inset-0 z-30 flex flex-col bg-background"
        aria-live="polite"
        aria-label="正在加载对话"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-6 pt-14">
          <div className="h-4 w-2/5 animate-pulse rounded bg-muted" />
          <div className="h-16 w-full animate-pulse rounded-lg bg-muted" />
          <div className="ml-auto h-12 w-3/5 animate-pulse rounded-lg bg-muted" />
          <div className="h-20 w-4/5 animate-pulse rounded-lg bg-muted" />
        </div>
        <div className="flex items-center justify-center gap-2 pb-8 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          正在加载对话…
        </div>
      </output>
    );
  }

  return (
    <div
      className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-background px-6"
      role="alert"
    >
      <p className="text-sm text-muted-foreground">对话加载失败</p>
      <Button variant="primary" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

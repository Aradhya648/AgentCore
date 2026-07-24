import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import { useStreamAwareDisclosure } from "@/stores/disclosure";
import { ChevronDown, ChevronRight } from "lucide-react";

/** Three pulsing dots — the shared「正在思考」liveliness cue (图2 的 ● ● ●). */
export function ThinkingDots() {
  return (
    <span className="inline-flex gap-1" aria-hidden>
      <span
        className="size-1.5 animate-pulse rounded-full bg-muted-foreground/70"
        style={{ animationDelay: "0ms" }}
      />
      <span
        className="size-1.5 animate-pulse rounded-full bg-muted-foreground/70"
        style={{ animationDelay: "150ms" }}
      />
      <span
        className="size-1.5 animate-pulse rounded-full bg-muted-foreground/70"
        style={{ animationDelay: "300ms" }}
      />
    </span>
  );
}

/**
 * Borderless disclosure header shared by {@link ThinkingPanel} and
 * {@link ProcessTimeline} (对齐 Cursor 的轻量内联思考样式).
 */
export function ThinkingHeader({
  isStreaming,
  expanded,
  streamingLabel,
  doneLabel,
  onToggle,
}: {
  isStreaming: boolean;
  expanded: boolean;
  streamingLabel: string;
  doneLabel: string;
  onToggle: () => void;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onToggle}
      className="h-auto w-full justify-start gap-2 px-0 py-0 text-sm font-normal text-muted-foreground hover:text-foreground"
    >
      {isStreaming ? (
        <>
          <ThinkingDots />
          <span>{streamingLabel}</span>
        </>
      ) : (
        <>
          <span>{doneLabel}</span>
          {expanded ? (
            <ChevronDown size={14} className="shrink-0" />
          ) : (
            <ChevronRight size={14} className="shrink-0" />
          )}
        </>
      )}
    </Button>
  );
}

/**
 * Collapsible panel showing the model's thinking (reasoning_content).
 * Used by multi-agent turns — the single-agent turn uses ProcessTimeline instead.
 */
export function ThinkingPanel({
  reasoning,
  isStreaming,
  persistKey,
}: {
  reasoning: string;
  isStreaming: boolean;
  /** 持久化键（`${messageId}:reasoning`）：给了才把「思考过程开合」跨卸载/刷新记住；缺省走会话态。 */
  persistKey?: string | null;
}) {
  // 「直播中自动展开、收场后按保存值」（Q3）——不再收场强制收起并遗忘。
  const [expanded, toggle] = useStreamAwareDisclosure(
    persistKey ?? null,
    isStreaming,
  );

  return (
    <div className="mb-2">
      <ThinkingHeader
        isStreaming={isStreaming}
        expanded={expanded}
        streamingLabel="Thinking…"
        doneLabel="Thought"
        onToggle={toggle}
      />
      {expanded && (
        <div className="mt-1.5 pl-3">
          <Markdown content={reasoning} isStreaming={isStreaming} muted />
        </div>
      )}
    </div>
  );
}

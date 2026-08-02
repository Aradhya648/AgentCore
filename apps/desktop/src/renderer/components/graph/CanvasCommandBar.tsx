import { FollowupChips } from "@/components/chat/FollowupChips";
import { QueuedTurnsBar } from "@/components/chat/QueuedTurnsBar";
import { TurnComposer } from "@/components/chat/message-input/TurnComposer";
import { IconButton } from "@/components/ui";
import { cn } from "@/lib/utils";
import { draftKeyFor, useComposerDraftStore } from "@/stores/composer";
import {
  useActiveGenerating,
  useActiveMessages,
  useConversationStore,
} from "@/stores/conversation";
import { ChevronDown, PenLine } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Floating command bar for the conversation-level team canvas
 * ({@link import("./ConversationCanvas").ConversationCanvas}；前端UX设计.md
 * §6.1 · §6.2): the unified {@link TurnComposer} — the SAME full composer as the
 * chat view's MessageInput (附件 / @ 文件引用 / 停止生成 / 后台云端 / 字数 / 回填),
 * in canvas chrome. Default = collapsed floating trigger so the canvas reads as a
 * pure board; expand to compose. Empty conversations (no turns) open expanded so
 * the first order can be typed immediately.
 *
 * Draft awareness (collapsed): the trigger mirrors the shared per-conversation
 * composer draft ({@link useComposerDraftStore}) — non-empty drafts show a first-line
 * preview + highlight, so 回填 from run-detail / debate / FollowupChips is visible
 * even while the bar is tucked away. Switching 聊天 ⇄ 画布 keeps the same draft.
 *
 * Host-specific bits: the boss-facing placeholder, the 自动跟随 waiting hint, and
 * `onDispatch` — ConversationCanvas follows the new round in place when a
 * foreground turn is dispatched; this bar then collapses back to the trigger.
 * Full-screen turn detail
 * ({@link import("../../pages/TurnDetailPage").TurnDetailPage}) is a pure
 * deep-read / replay surface and does not host this bar.
 *
 * 后台云端 toggle (`allowBackground`): offered ONLY where the resulting 后台云端任务
 * card is afterward visible (the overview's 指挥台 feed).
 *
 * 下一步推荐 chips sit above the composer when expanded (same gate as ChatView).
 */
export function CanvasCommandBar({
  onDispatch,
  waiting,
  allowBackground = false,
  emptyConversation = false,
}: {
  onDispatch: () => void;
  waiting: boolean;
  allowBackground?: boolean;
  /** No turns yet — start expanded so the first order can be typed in place. */
  emptyConversation?: boolean;
}) {
  const messages = useActiveMessages();
  const isGenerating = useActiveGenerating();
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const draftKey = draftKeyFor(conversationId);
  const draftValue = useComposerDraftStore(
    (s) => s.drafts[draftKey]?.value ?? "",
  );
  const hasDraft = draftValue.trim().length > 0;
  const draftPreview = hasDraft
    ? (draftValue.trim().split(/\r?\n/, 1)[0] ?? "")
    : "";

  const last = messages[messages.length - 1];
  const followups =
    !isGenerating && last?.role === "assistant" && !last.isStreaming
      ? (last.followups ?? [])
      : [];

  const [expanded, setExpanded] = useState(emptyConversation);
  const panelRef = useRef<HTMLDivElement>(null);

  // Remount / conversation / empty-state change → reset open policy.
  // biome-ignore lint/correctness/useExhaustiveDependencies: conversationId is an intentional re-run key — reset the open policy when switching conversations.
  useEffect(() => {
    setExpanded(emptyConversation);
  }, [conversationId, emptyConversation]);

  const collapse = useCallback(() => setExpanded(false), []);
  const expand = useCallback(() => setExpanded(true), []);

  const handleDispatch = useCallback(() => {
    onDispatch();
    setExpanded(false);
  }, [onDispatch]);

  // Esc collapses (capture so canvas keyboard-nav Escape doesn't win first).
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setExpanded(false);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [expanded]);

  // Click outside the floating panel collapses.
  useEffect(() => {
    if (!expanded) return;
    const onPointer = (e: PointerEvent) => {
      const el = panelRef.current;
      if (!el) return;
      if (e.target instanceof Node && el.contains(e.target)) return;
      setExpanded(false);
    };
    // Defer so the expand click itself doesn't immediately collapse.
    const id = window.setTimeout(() => {
      window.addEventListener("pointerdown", onPointer);
    }, 0);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("pointerdown", onPointer);
    };
  }, [expanded]);

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center px-4 pb-3">
      <div ref={panelRef} className="pointer-events-auto w-full max-w-3xl">
        {waiting && (
          <div className="mb-1 text-center text-xs text-muted-foreground">
            新回合执行中，画布将自动跟随…
          </div>
        )}

        {expanded ? (
          <div className="rounded-xl border border-border bg-background/95 p-3 shadow-lg backdrop-blur">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">下达指令</span>
              <IconButton
                size="sm"
                onClick={collapse}
                aria-label="收起指令栏"
                className="text-muted-foreground hover:text-foreground"
              >
                <ChevronDown size={16} />
              </IconButton>
            </div>
            <FollowupChips followups={followups} />
            <QueuedTurnsBar conversationId={conversationId} />
            <TurnComposer
              placeholder="向 CEO 下达下一步指令…"
              allowBackground={allowBackground}
              onDispatch={handleDispatch}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={expand}
            aria-label={hasDraft ? "展开指令栏（有待发送草稿）" : "展开指令栏"}
            className={cn(
              "flex w-full items-center gap-2 rounded-xl border px-3 py-2.5 text-left shadow-md backdrop-blur transition-colors",
              hasDraft
                ? "border-primary/50 bg-primary/5 text-foreground ring-1 ring-primary/30"
                : "border-border bg-card/95 text-muted-foreground hover:border-border hover:text-foreground",
            )}
          >
            <PenLine
              size={16}
              className={cn(
                "shrink-0",
                hasDraft ? "text-primary" : "text-muted-foreground",
              )}
            />
            <span className="min-w-0 flex-1 truncate text-sm">
              {hasDraft ? draftPreview : "向 CEO 下达下一步指令…"}
            </span>
            {hasDraft && (
              <span className="shrink-0 text-xs text-primary">待发送</span>
            )}
          </button>
        )}
      </div>
    </div>
  );
}

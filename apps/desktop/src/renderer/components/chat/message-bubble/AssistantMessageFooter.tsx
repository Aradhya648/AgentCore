import { ReceivedContextDialog } from "@/components/chat/ReceivedContext";
import { IconButton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FINISH_REASON_META } from "@/components/ui/finish-reason-chip";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { copyText } from "@/lib/clipboard";
import { formatCollabSummary } from "@/lib/collabSummary";
import { formatCompact } from "@/lib/format";
import { formatMessageExport } from "@/lib/messageExport";
import { formatSupportDiagnosticText } from "@/lib/supportDiagnostics";
import { notifyError, notifySuccess } from "@/lib/toast";
import { setMessageFeedback } from "@/services/messages";
import type { UsageBreakdown } from "@/services/usage";
import { useBookmarkStore } from "@/stores/bookmarks";
import type { Message } from "@/stores/conversation";
import {
  assistantProjectionId,
  useConversationStore,
} from "@/stores/conversation";
import { turnDetailPath, useUIStore } from "@/stores/ui";
import type { ContextBlockWire } from "@/types/events";
import {
  Bookmark,
  Check,
  Copy,
  Fingerprint,
  Layers,
  Link2,
  Maximize2,
  MoreHorizontal,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DeleteMessageAction, MessageTime } from "./MessageActions";
import { useCopyAction } from "./useCopyAction";

function cacheRatePercent(usage: UsageBreakdown): number | null {
  if (usage.input <= 0) return null;
  return Math.round((usage.cache_hit / usage.input) * 100);
}

/** Direction glyph separated from the number so `↑41.1k` is not read as `141.1k`. */
function UsageDir({ dir }: { dir: "in" | "out" }) {
  return (
    <span
      aria-hidden
      className="mr-0.5 inline-block font-sans not-italic text-muted-foreground/55"
    >
      {dir === "in" ? "↑" : "↓"}
    </span>
  );
}

/** Compact token / round / cost summary — right-aligned in the footer. */
function MessageUsageSummary({
  usage,
  rounds,
  costText,
}: {
  usage: UsageBreakdown | undefined;
  rounds: number | undefined;
  costText: string | null;
}) {
  if (!usage && (rounds == null || rounds <= 1) && !costText) return null;

  const rate = usage ? cacheRatePercent(usage) : null;
  const tooltip = usage
    ? `输入 ${formatCompact(usage.input)}（缓存命中 ${formatCompact(usage.cache_hit)} · 未命中 ${formatCompact(usage.cache_miss)}）· 输出 ${formatCompact(usage.output)}（思考 ${formatCompact(usage.reasoning)}）`
    : undefined;

  const body = (
    <span className="inline-flex cursor-default items-center gap-1.5 text-xs tabular-nums text-muted-foreground/70">
      {usage && (
        <span className="inline-flex items-center gap-1">
          <span className="inline-flex items-baseline">
            <UsageDir dir="in" />
            <span>
              {formatCompact(usage.input)}
              {rate != null && rate > 0 ? `(缓${rate}%)` : ""}
            </span>
          </span>
          <span className="inline-flex items-baseline">
            <UsageDir dir="out" />
            <span>
              {formatCompact(usage.output)}
              {usage.reasoning > 0
                ? `(思${formatCompact(usage.reasoning)})`
                : ""}
            </span>
          </span>
        </span>
      )}
      {rounds != null && rounds > 1 && (
        <>
          {usage ? <span aria-hidden>·</span> : null}
          <span>{rounds} 轮</span>
        </>
      )}
      {costText && (
        <>
          {usage || (rounds != null && rounds > 1) ? (
            <span aria-hidden>·</span>
          ) : null}
          <span>{costText}</span>
        </>
      )}
    </span>
  );

  if (tooltip) {
    return <SimpleTooltip label={tooltip}>{body}</SimpleTooltip>;
  }
  return body;
}

function UsageDetailPanel({ usage }: { usage: UsageBreakdown }) {
  const rate = cacheRatePercent(usage);
  return (
    <div className="space-y-1 px-3 py-1.5 text-xs text-muted-foreground">
      <div className="flex justify-between gap-3 tabular-nums">
        <span>输入</span>
        <span className="text-foreground">{formatCompact(usage.input)}</span>
      </div>
      <div className="flex justify-between gap-3 tabular-nums">
        <span>缓存命中</span>
        <span className="text-foreground">
          {formatCompact(usage.cache_hit)}
          {rate != null ? ` · ${rate}%` : ""}
        </span>
      </div>
      <div className="flex justify-between gap-3 tabular-nums">
        <span>缓存未命中</span>
        <span className="text-foreground">
          {formatCompact(usage.cache_miss)}
        </span>
      </div>
      <div className="flex justify-between gap-3 tabular-nums">
        <span>输出</span>
        <span className="text-foreground">{formatCompact(usage.output)}</span>
      </div>
      {usage.reasoning > 0 && (
        <div className="flex justify-between gap-3 tabular-nums">
          <span>思考</span>
          <span className="text-foreground">
            {formatCompact(usage.reasoning)}
          </span>
        </div>
      )}
    </div>
  );
}

async function copyDiagnostic(
  label: string,
  value: string,
  description?: string,
) {
  if (await copyText(value)) notifySuccess(`已复制 ${label}`, { description });
}

/** 消息永久链接 (对话基础功能补齐): a hash anchor that reopens the conversation and
 * lands on this exact turn (scroll). Portable to the web build as a real
 * shareable URL; in desktop it round-trips through the same #/conversations/:id?msg=
 * route ConversationPage honors on load. */
function messagePermalink(conversationId: string, messageId: string): string {
  const base = window.location.href.split("#")[0];
  return `${base}#/conversations/${conversationId}?msg=${messageId}`;
}

function MessageMoreMenu({
  message,
  captainContext,
  finishReason,
}: {
  message: Message;
  captainContext: ContextBlockWire[];
  finishReason: string | undefined;
}) {
  const [contextOpen, setContextOpen] = useState(false);
  const diagnosticMode = useUIStore((s) => s.diagnosticMode);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const navigate = useNavigate();

  // DEV or 诊断模式：合并项沿用原 trace 项的宽松可见性（不再要求 diagnosticMode）。
  const showDiagnostics = import.meta.env.DEV || diagnosticMode;
  const serverMessageId = assistantProjectionId(message);
  const diagnosticText = formatSupportDiagnosticText({
    conversationId,
    messageId: serverMessageId,
    traceId: message.traceId,
    executionId: message.executionId,
  });
  const finishLabel = finishReason
    ? FINISH_REASON_META[finishReason]?.label
    : null;

  const hasMenu =
    !!conversationId ||
    captainContext.length > 0 ||
    !!message.executionId ||
    !!message.usage ||
    (showDiagnostics && !!diagnosticText) ||
    !!finishLabel;

  const openInCanvas = () => {
    if (!conversationId || !message.executionId) return;
    navigate(turnDetailPath(conversationId, serverMessageId));
  };

  if (!hasMenu) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <IconButton size="sm" aria-label="更多">
            <MoreHorizontal size={14} />
          </IconButton>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-48">
          {conversationId && (
            <DropdownMenuItem
              onSelect={() =>
                void copyDiagnostic(
                  "消息链接",
                  messagePermalink(conversationId, serverMessageId),
                )
              }
            >
              <Link2 size={14} className="shrink-0 text-muted-foreground" />
              复制消息链接
            </DropdownMenuItem>
          )}
          {captainContext.length > 0 && (
            <DropdownMenuItem onSelect={() => setContextOpen(true)}>
              <Layers size={14} className="shrink-0 text-muted-foreground" />
              收到的上下文 · {captainContext.length} 段
            </DropdownMenuItem>
          )}
          {message.executionId && conversationId && (
            <DropdownMenuItem onSelect={openInCanvas}>
              <Maximize2 size={14} className="shrink-0 text-muted-foreground" />
              在画布查看此回合
            </DropdownMenuItem>
          )}
          {message.usage && (
            <>
              {(!!conversationId ||
                captainContext.length > 0 ||
                message.executionId) && <DropdownMenuSeparator />}
              <DropdownMenuLabel>用量详情</DropdownMenuLabel>
              <UsageDetailPanel usage={message.usage} />
              {message.rounds != null && message.rounds > 1 && (
                <div className="flex justify-between gap-3 px-3 pb-1.5 text-xs text-muted-foreground">
                  <span>ReAct 轮次</span>
                  <span className="tabular-nums text-foreground">
                    {message.rounds} 轮
                  </span>
                </div>
              )}
            </>
          )}
          {finishLabel && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>收尾原因</DropdownMenuLabel>
              <p className="px-3 pb-1.5 text-xs text-muted-foreground">
                {finishLabel}
              </p>
            </>
          )}
          {showDiagnostics && diagnosticText && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => void copyDiagnostic("排查包", diagnosticText)}
              >
                <Fingerprint
                  size={14}
                  className="shrink-0 text-muted-foreground"
                />
                复制排查包
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <ReceivedContextDialog
        blocks={captainContext}
        open={contextOpen}
        onOpenChange={setContextOpen}
      />
    </>
  );
}

/** 回复反馈 (点赞/点踩, 对话基础功能补齐): thumbs up/down on an assistant reply. The active
 * side highlights in the brand color; clicking it again clears the rating (toggle off).
 * Optimistic — the service flips the bubble immediately and reverts on a failed persist. */
function FeedbackButtons({ message }: { message: Message }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const feedback = message.feedback ?? null;
  const rate = (side: "up" | "down") => {
    if (!conversationId) return;
    const next = feedback === side ? null : side;
    void setMessageFeedback(conversationId, message.id, next).catch((err) =>
      notifyError(err, "反馈失败"),
    );
  };
  return (
    <>
      <SimpleTooltip label="有帮助">
        <IconButton
          size="sm"
          aria-label="有帮助"
          aria-pressed={feedback === "up"}
          className={feedback === "up" ? "text-primary" : undefined}
          onClick={() => rate("up")}
        >
          <ThumbsUp size={14} />
        </IconButton>
      </SimpleTooltip>
      <SimpleTooltip label="没帮助">
        <IconButton
          size="sm"
          aria-label="没帮助"
          aria-pressed={feedback === "down"}
          className={feedback === "down" ? "text-primary" : undefined}
          onClick={() => rate("down")}
        >
          <ThumbsDown size={14} />
        </IconButton>
      </SimpleTooltip>
    </>
  );
}

/** 消息收藏 (方向 4): star an assistant reply → 侧栏「已收藏」. Cross-device (server-
 * stored); optimistic via the bookmark store, filled when saved. */
function BookmarkButton({ message }: { message: Message }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const bookmarked = useBookmarkStore((s) => s.ids.has(message.id));
  const toggle = useBookmarkStore((s) => s.toggle);
  return (
    <SimpleTooltip label={bookmarked ? "取消收藏" : "收藏"}>
      <IconButton
        size="sm"
        aria-label={bookmarked ? "取消收藏" : "收藏"}
        aria-pressed={bookmarked}
        className={bookmarked ? "text-primary" : undefined}
        onClick={() => {
          if (conversationId) void toggle(conversationId, message.id);
        }}
      >
        <Bookmark
          size={14}
          className={bookmarked ? "fill-current" : undefined}
        />
      </IconButton>
    </SimpleTooltip>
  );
}

/** Assistant bubble footer — actions left, usage summary + time right, low-freq in「更多」. */
export function AssistantMessageFooter({
  message,
  captainContext,
  costText,
  finishReason,
  onRegenerate,
}: {
  message: Message;
  captainContext: ContextBlockWire[];
  costText: string | null;
  finishReason: string | undefined;
  onRegenerate: () => void;
}) {
  const hasProcess = (message.process?.length ?? 0) > 0;
  const { copied, onCopy } = useCopyAction(() =>
    formatMessageExport(message.content, message.process, "deliverable"),
  );
  const { copied: copiedProcess, onCopy: onCopyProcess } = useCopyAction(() =>
    formatMessageExport(message.content, message.process, "with_process"),
  );
  const collabSummary = useMemo(
    () => formatCollabSummary(message.collab),
    [message.collab],
  );

  return (
    <div className="mt-1 flex items-center justify-between gap-2 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      <div className="flex min-w-0 items-center gap-0.5">
        {hasProcess ? (
          <DropdownMenu>
            <SimpleTooltip label={copied || copiedProcess ? "已复制" : "复制"}>
              <DropdownMenuTrigger asChild>
                <IconButton size="sm" aria-label="复制">
                  {copied || copiedProcess ? (
                    <Check size={14} />
                  ) : (
                    <Copy size={14} />
                  )}
                </IconButton>
              </DropdownMenuTrigger>
            </SimpleTooltip>
            <DropdownMenuContent align="start" className="min-w-40">
              <DropdownMenuItem onSelect={() => void onCopy()}>
                仅交付
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void onCopyProcess()}>
                含过程
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <SimpleTooltip label={copied ? "已复制" : "复制"}>
            <IconButton
              size="sm"
              aria-label="复制"
              onClick={() => void onCopy()}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </IconButton>
          </SimpleTooltip>
        )}
        <FeedbackButtons message={message} />
        <BookmarkButton message={message} />
        <SimpleTooltip label="重新生成">
          <IconButton size="sm" aria-label="重新生成" onClick={onRegenerate}>
            <RefreshCw size={14} />
          </IconButton>
        </SimpleTooltip>
        <DeleteMessageAction messageId={message.id} compact />
        <MessageMoreMenu
          message={message}
          captainContext={captainContext}
          finishReason={finishReason}
        />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {collabSummary && (
          <span className="text-xs text-muted-foreground/70">
            {collabSummary}
          </span>
        )}
        <MessageUsageSummary
          usage={message.usage}
          rounds={message.rounds}
          costText={costText}
        />
        <MessageTime iso={message.createdAt} />
      </div>
    </div>
  );
}

import { Button } from "@/components/ui";
import { notifyError } from "@/lib/toast";
import { runRegenerate } from "@/services/turns";
import { cancelQueuedTurn } from "@/services/turns/cancelQueuedTurn";
import {
  useActiveGenerating,
  useConversationStore,
} from "@/stores/conversation";
import { useQueuedTurnsStore } from "@/stores/queuedTurns";
import { Check, Copy, Loader2, Pencil, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AttachmentChip } from "./AttachmentChip";
import {
  DeleteMessageAction,
  MessageAction,
  MessageTime,
} from "./MessageActions";
import { SyncStatusHint } from "./SyncStatusHint";
import type { MessageBubbleProps } from "./types";
import { useCopyAction } from "./useCopyAction";

export function UserMessage({ message }: MessageBubbleProps) {
  const isGenerating = useActiveGenerating();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [cancelBusy, setCancelBusy] = useState(false);
  const editRef = useRef<HTMLTextAreaElement>(null);
  const { copied, onCopy } = useCopyAction(() => message.content);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const attachments = message.attachments ?? [];
  const queued = useQueuedTurnsStore((s) => {
    if (!conversationId) return null;
    return (
      (s.byConversation[conversationId] ?? []).find(
        (e) => e.messageId === message.id,
      ) ?? null
    );
  });

  const queueLabel = useMemo(() => {
    if (!queued) return null;
    return queued.queueDepth > 1
      ? `排队中（第 ${queued.position}/${queued.queueDepth}）`
      : "排队中";
  }, [queued]);

  const startEdit = () => {
    setDraft(message.content);
    setEditing(true);
  };

  useEffect(() => {
    if (editing) {
      const el = editRef.current;
      if (el) {
        el.focus();
        el.selectionStart = el.selectionEnd = el.value.length;
        el.style.height = "0";
        el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
      }
    }
  }, [editing]);

  const submitEdit = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    setEditing(false);
    if (trimmed === message.content) return;
    useConversationStore
      .getState()
      .updateMessage(message.id, { content: trimmed });
    void runRegenerate(message.id, trimmed);
  };

  const onCancelQueue = async () => {
    if (!queued || cancelBusy) return;
    setCancelBusy(true);
    try {
      await cancelQueuedTurn(queued.conversationId, queued.queueId);
    } catch (err) {
      notifyError(err, "取消排队失败");
    } finally {
      setCancelBusy(false);
    }
  };

  if (editing) {
    return (
      <div className="flex flex-col items-end gap-2">
        <div className="w-full max-w-[80%] rounded-xl rounded-br-none border border-border bg-card p-2">
          <textarea
            ref={editRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              e.target.style.height = "0";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 240)}px`;
            }}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Escape") {
                e.preventDefault();
                setEditing(false);
              } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                submitEdit();
              }
            }}
            className="w-full resize-none bg-transparent px-2 py-1 text-sm text-foreground focus:outline-none"
            rows={1}
          />
          <div className="flex items-center justify-end gap-1.5 pt-1">
            <Button
              variant="neutral"
              icon={<X size={13} />}
              onClick={() => setEditing(false)}
            >
              取消
            </Button>
            <Button
              icon={<Check size={13} />}
              onClick={submitEdit}
              disabled={!draft.trim()}
            >
              发送
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex flex-col items-end gap-1.5">
      {attachments.length > 0 && (
        <div className="flex max-w-[80%] flex-wrap justify-end gap-1.5">
          {attachments.map((a) => (
            <AttachmentChip
              key={a.id}
              att={a}
              conversationId={conversationId}
            />
          ))}
        </div>
      )}
      <div
        className={`max-w-[80%] rounded-xl rounded-br-none px-4 py-3 text-sm text-foreground ${
          queued ? "border border-dashed border-border bg-muted/50" : "bg-muted"
        }`}
        data-queued={queued ? "true" : undefined}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
        {queueLabel && (
          <div
            className="mt-2 flex items-center gap-2 text-xs text-muted-foreground"
            data-testid="user-message-queue-state"
          >
            <Loader2 size={12} className="shrink-0 animate-spin" aria-hidden />
            <span className="min-w-0 flex-1">{queueLabel}</span>
            <button
              type="button"
              className="shrink-0 rounded-lg px-1.5 py-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              aria-label="取消排队"
              disabled={cancelBusy}
              onClick={() => void onCancelQueue()}
            >
              取消
            </button>
          </div>
        )}
      </div>
      {message.syncStatus && (
        <div className="flex justify-end">
          <SyncStatusHint syncStatus={message.syncStatus} align="end" />
        </div>
      )}
      {!isGenerating && !queued && (
        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <MessageAction
            icon={copied ? <Check size={13} /> : <Copy size={13} />}
            label={copied ? "已复制" : "复制"}
            onClick={onCopy}
          />
          <MessageAction
            icon={<Pencil size={13} />}
            label="编辑"
            onClick={startEdit}
          />
          <DeleteMessageAction messageId={message.id} />
          <MessageTime iso={message.createdAt} />
        </div>
      )}
    </div>
  );
}

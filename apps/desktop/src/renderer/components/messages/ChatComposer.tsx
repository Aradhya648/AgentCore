import { IconButton } from "@/components/ui";
import { isImageAttachment } from "@/services/messaging";
import { useMessagingStore } from "@/stores/messaging";
import {
  AlertTriangle,
  FileText,
  Loader2,
  Paperclip,
  Send,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  chatId: string;
}

/** A file staged for sending, with an object URL preview for images. */
interface Pending {
  id: string;
  file: File;
  previewUrl?: string;
}

const MAX_ATTACHMENTS = 9;
const MAX_FILE_BYTES = 25 * 1024 * 1024; // mirrors workspace_upload_max_bytes

/**
 * IM message composer: an auto-growing textarea + attachments (图/文件). Enter
 * sends, Shift+Enter inserts a newline. Files can be added via the paperclip, by
 * pasting an image, or by dragging files onto the composer; each shows a pending
 * chip/thumbnail until sent.
 *
 * Sending is optimistic in the store (it uploads files first, then appends a
 * local twin and swaps it for the stored message). This owns the draft + staged
 * files and surfaces both local validation errors and the store's send error.
 */
export function ChatComposer({ chatId }: Props) {
  const [value, setValue] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sendError = useMessagingStore((s) => s.sendError);
  const clearSendError = useMessagingStore((s) => s.clearSendError);

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: value is an intentional re-run key — re-measure on every input change.
  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  // Revoke any image preview object URLs when the staged set changes / unmounts.
  useEffect(() => {
    return () => {
      for (const p of pending) {
        if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
      }
    };
  }, [pending]);

  // Switching chats starts a fresh draft and drops any stale errors / staged files.
  // biome-ignore lint/correctness/useExhaustiveDependencies: chatId is an intentional re-run key — reset the composer whenever the active chat changes.
  useEffect(() => {
    setValue("");
    setPending([]);
    setLocalError(null);
    clearSendError();
  }, [chatId, clearSendError]);

  const addFiles = useCallback((incoming: File[]) => {
    if (incoming.length === 0) return;
    setLocalError(null);
    setPending((prev) => {
      const next = [...prev];
      for (const file of incoming) {
        if (next.length >= MAX_ATTACHMENTS) {
          setLocalError(`最多只能添加 ${MAX_ATTACHMENTS} 个附件`);
          break;
        }
        if (file.size > MAX_FILE_BYTES) {
          setLocalError(`「${file.name}」超过 25 MB 上限`);
          continue;
        }
        next.push({
          id: crypto.randomUUID(),
          file,
          previewUrl: isImageAttachment(file.name)
            ? URL.createObjectURL(file)
            : undefined,
        });
      }
      return next;
    });
  }, []);

  const removePending = useCallback((id: string) => {
    setPending((prev) => {
      const target = prev.find((p) => p.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((p) => p.id !== id);
    });
  }, []);

  const handleSend = useCallback(() => {
    const text = value.trim();
    if (sending) return;
    if (!text && pending.length === 0) return;
    const files = pending.map((p) => p.file);
    setValue("");
    setSending(true);
    void (async () => {
      await useMessagingStore.getState().sendMessage(chatId, text, files);
      setSending(false);
      // Keep the staged files if the send failed (e.g. an upload error) so the
      // user can retry without re-picking; clear them on success.
      if (!useMessagingStore.getState().sendError) {
        for (const p of pending) {
          if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
        }
        setPending([]);
      }
    })();
  }, [value, pending, sending, chatId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData.files);
    if (files.length > 0) {
      e.preventDefault();
      addFiles(files);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) addFiles(files);
  };

  const canSend = (Boolean(value.trim()) || pending.length > 0) && !sending;

  return (
    <div className="px-4 pb-4 pt-2">
      {(sendError || localError) && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertTriangle size={15} className="shrink-0" />
          <span className="min-w-0 flex-1">{sendError ?? localError}</span>
          <IconButton
            onClick={() => {
              clearSendError();
              setLocalError(null);
            }}
            aria-label="关闭"
            className="text-destructive/70 hover:bg-transparent hover:text-destructive"
          >
            <X size={14} />
          </IconButton>
        </div>
      )}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`rounded-xl border bg-card shadow-sm transition-colors ${
          dragging ? "border-primary bg-primary/5" : "border-border"
        }`}
      >
        {pending.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {pending.map((p) => (
              <div
                key={p.id}
                className="group/att relative flex items-center gap-2 rounded-lg border border-border bg-background py-1.5 pl-1.5 pr-2"
              >
                {p.previewUrl ? (
                  <img
                    src={p.previewUrl}
                    alt={p.file.name}
                    className="size-9 rounded-lg object-cover"
                  />
                ) : (
                  <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
                    <FileText size={16} className="text-muted-foreground" />
                  </span>
                )}
                <span className="max-w-[140px] truncate text-xs text-foreground">
                  {p.file.name}
                </span>
                <IconButton
                  onClick={() => removePending(p.id)}
                  aria-label="移除附件"
                  className="size-4 rounded-full bg-muted text-muted-foreground hover:bg-destructive hover:text-destructive-foreground"
                >
                  <X size={11} />
                </IconButton>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 px-3 py-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
          <IconButton
            size="md"
            onClick={() => fileInputRef.current?.click()}
            disabled={sending}
            aria-label="添加附件"
          >
            <Paperclip size={16} />
          </IconButton>
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder="输入消息…"
            className="max-h-40 w-full resize-none bg-transparent py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            rows={1}
          />
          <IconButton
            size="md"
            tone="primary"
            onClick={handleSend}
            disabled={!canSend}
            aria-label="发送"
          >
            {sending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Send size={14} />
            )}
          </IconButton>
        </div>
      </div>
    </div>
  );
}

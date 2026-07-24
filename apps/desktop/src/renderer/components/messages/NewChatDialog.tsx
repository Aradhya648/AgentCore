import { Button, IconButton, SearchField } from "@/components/ui";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  type UserSearchResult,
  messagingErrorMessage,
  searchUsers,
  startDm,
} from "@/services/messaging";
import { useMessagingStore } from "@/stores/messaging";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { avatarInitial } from "./chatDisplay";

interface Props {
  open: boolean;
  onClose: () => void;
  onStarted: (chatId: string) => void;
}

/**
 * Start a chat by 任意搜人 (exact-match people search → open dm). The server
 * filters search visibility and gates who-can-DM / blocks, so a refusal here
 * (403 contacts-only, 404 unknown) is surfaced via the shared zh phrasing.
 */
export function NewChatDialog({ open, onClose, onStarted }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UserSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Each open is a fresh search. (Focus is handled by the Dialog's
  // onOpenAutoFocus below, once the content has mounted.)
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setError(null);
    setStarting(null);
  }, [open]);

  // Debounced exact-match search; the empty query clears results.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const users = await searchUsers(q);
          if (!cancelled) {
            setResults(users);
            setError(null);
          }
        } catch (err) {
          if (!cancelled) {
            setResults([]);
            setError(messagingErrorMessage(err, "搜索失败，请重试"));
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
      })();
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, open]);

  const handleStart = async (user: UserSearchResult) => {
    setStarting(user.id);
    setError(null);
    try {
      const chat = await startDm(user.id);
      useMessagingStore.getState().upsertChat(chat);
      onStarted(chat.id);
      onClose();
    } catch (err) {
      setError(messagingErrorMessage(err, "无法发起会话"));
      setStarting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        position="top"
        showClose={false}
        className="max-w-md"
        aria-describedby={undefined}
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          inputRef.current?.focus();
        }}
      >
        <DialogTitle className="sr-only">新建会话</DialogTitle>
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <SearchField
            ref={inputRef}
            variant="plain"
            value={query}
            onValueChange={setQuery}
            placeholder="查找联系人…"
            aria-label="按用户名或 ID 查找联系人"
            clearable={false}
            escapeClears={false}
            className="flex-1"
          />
          <IconButton
            onClick={onClose}
            aria-label="关闭"
            className="shrink-0 hover:bg-transparent"
          >
            <X size={15} />
          </IconButton>
        </div>

        <div className="max-h-80 overflow-y-auto">
          {error && (
            <p className="px-4 py-3 text-sm text-destructive">{error}</p>
          )}
          {!error && loading && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              查找中…
            </p>
          )}
          {!error && !loading && !query.trim() && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              输入用户名或 ID 查找联系人
            </p>
          )}
          {!error && !loading && query.trim() && results.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted-foreground">
              未找到用户（需精确用户名或 ID）
            </p>
          )}
          {results.length > 0 && (
            <ul className="py-1.5">
              {results.map((u) => (
                <li key={u.id}>
                  <Button
                    variant="ghost"
                    disabled={starting !== null}
                    onClick={() => void handleStart(u)}
                    className="h-auto w-full justify-start gap-3 rounded-none px-4 py-2 font-normal disabled:opacity-50"
                  >
                    <span className="flex w-full items-center gap-3 text-left">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-medium text-primary">
                        {avatarInitial(u.display_name || u.username)}
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-sm text-foreground">
                          {u.display_name || u.username}
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          @{u.username}
                        </span>
                      </span>
                      {starting === u.id && (
                        <span className="shrink-0 text-xs text-muted-foreground">
                          发起中…
                        </span>
                      )}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

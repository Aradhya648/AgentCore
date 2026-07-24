import { IconButton, SearchField } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useChats, useMessagingStore } from "@/stores/messaging";
import { SquarePen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ChatListItem } from "./ChatListItem";
import { chatDisplayName } from "./chatDisplay";

interface Props {
  activeChatId: string | null;
  onSelect: (chatId: string) => void;
  onNewChat: () => void;
}

/** Left pane: the chat list with a header, a local filter, and empty states. */
export function ChatList({ activeChatId, onSelect, onNewChat }: Props) {
  const chats = useChats();
  const loading = useMessagingStore((s) => s.loadingChats);
  const loaded = useMessagingStore((s) => s.chatsLoaded);
  const [query, setQuery] = useState("");

  // Hydrate the list once; the firehose keeps it fresh thereafter (stage D).
  useEffect(() => {
    if (!useMessagingStore.getState().chatsLoaded) {
      void useMessagingStore.getState().fetchChats();
    }
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return chats;
    return chats.filter((c) => chatDisplayName(c).toLowerCase().includes(q));
  }, [chats, query]);

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-base font-medium text-foreground">消息</span>
        <SimpleTooltip label="发起会话">
          <IconButton
            aria-label="发起会话"
            onClick={onNewChat}
            className="[-webkit-app-region:no-drag]"
          >
            <SquarePen size={16} />
          </IconButton>
        </SimpleTooltip>
      </div>

      {chats.length > 0 && (
        <div className="px-3 pb-2">
          <SearchField
            value={query}
            onValueChange={setQuery}
            placeholder="筛选会话…"
            aria-label="筛选会话"
          />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {!loaded && loading ? (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">
            加载中…
          </p>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-1 px-4 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              {chats.length === 0 ? "还没有会话" : "没有匹配的会话"}
            </p>
            {chats.length === 0 && (
              <p className="text-xs text-muted-foreground/70">
                点击右上角发起会话
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-0.5">
            {filtered.map((c) => (
              <ChatListItem
                key={c.id}
                chat={c}
                active={c.id === activeChatId}
                onSelect={() => onSelect(c.id)}
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

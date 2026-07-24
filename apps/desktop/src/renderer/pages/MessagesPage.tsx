import { ChatList } from "@/components/messages/ChatList";
import { ChatThread } from "@/components/messages/ChatThread";
import { NewChatDialog } from "@/components/messages/NewChatDialog";
import { useMessagingStore } from "@/stores/messaging";
import { Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

/**
 * 消息 page (找人 IM): a two-pane layout (chat list + thread), mirroring the
 * FilesPage shell. The route param `:chatId` is the source of truth for the open
 * chat — syncing it into the store (load history + mark read) mirrors how
 * ConversationPage drives the AI 对话 page (消息IM.md §六).
 */
export function MessagesPage() {
  const { chatId } = useParams<{ chatId: string }>();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    const store = useMessagingStore.getState();
    if (!chatId) {
      store.setActiveChat(null);
      return;
    }
    if (chatId !== store.activeChatId) void store.openChat(chatId);
  }, [chatId]);

  return (
    <div className="flex h-full w-full">
      <ChatList
        activeChatId={chatId ?? null}
        onSelect={(id) => navigate(`/messages/${id}`)}
        onNewChat={() => setDialogOpen(true)}
      />
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {chatId ? (
          <ChatThread chatId={chatId} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <Mail size={28} className="text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              选择一个会话，或发起新会话
            </p>
          </div>
        )}
      </section>
      <NewChatDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onStarted={(id) => navigate(`/messages/${id}`)}
      />
    </div>
  );
}

import { findOfficialChatId } from "@/components/messages/chatDisplay";
import { useChats, useMessagingStore } from "@/stores/messaging";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

/**
 * Legacy `#/more/notices` (and handbook `APP_PATHS.more.notices`) → messages
 * page official broadcast chat. Product inbox now lives in IM.
 */
export function RedirectToOfficialChat() {
  const navigate = useNavigate();
  const chats = useChats();
  const loaded = useMessagingStore((s) => s.chatsLoaded);
  const fetchChats = useMessagingStore((s) => s.fetchChats);

  useEffect(() => {
    if (!loaded) void fetchChats();
  }, [loaded, fetchChats]);

  useEffect(() => {
    if (!loaded) return;
    const id = findOfficialChatId(chats);
    navigate(id ? `/messages/${id}` : "/messages", { replace: true });
  }, [loaded, chats, navigate]);

  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-muted-foreground">正在打开官方号…</p>
    </div>
  );
}

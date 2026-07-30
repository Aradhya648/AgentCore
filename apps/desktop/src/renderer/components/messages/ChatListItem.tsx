import { Button } from "@/components/ui";
import { formatMessageTime } from "@/lib/format";
import type { ChatSummary } from "@/services/messaging";
import { useMessagingStore } from "@/stores/messaging";
import { BadgeCheck, BellOff, Pin, Users } from "lucide-react";
import { PresenceAvatar } from "./PresenceAvatar";
import { avatarInitial, chatDisplayName } from "./chatDisplay";

interface Props {
  chat: ChatSummary;
  active: boolean;
  onSelect: () => void;
}

/** One row in the IM chat list (消息页左栏). */
export function ChatListItem({ chat, active, onSelect }: Props) {
  const name = chatDisplayName(chat);
  const time = chat.last_message_at
    ? formatMessageTime(chat.last_message_at)
    : "";
  const preview =
    chat.last_message_preview ?? (chat.state === "pending" ? "消息请求" : "");
  const peerOnline = chat.type === "dm" && !!chat.peer?.online;
  const isOfficial = chat.type === "official";
  // Official membership is pinned on enroll; still show pin affordance if flagged.
  const showPin = chat.pinned || isOfficial;
  // 静音 × 被 @: still show the unread badge when a mention alert is pending.
  const mentionAlert = useMessagingStore(
    (s) => s.mentionAlertByChat[chat.id] ?? false,
  );
  const showUnreadBadge = chat.unread > 0 && (!chat.muted || mentionAlert);

  return (
    <Button
      variant="ghost"
      onClick={onSelect}
      className={`h-auto w-full justify-start gap-3 rounded-lg px-2.5 py-2 font-normal ${
        active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50"
      }`}
    >
      <span className="flex w-full items-center gap-3 text-left">
        <PresenceAvatar
          label={avatarInitial(name)}
          sizeClass="size-9"
          textClass="text-sm"
          online={peerOnline}
        />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex items-center gap-1">
            {chat.type === "group" && (
              <Users size={12} className="shrink-0 text-muted-foreground" />
            )}
            {isOfficial && (
              <BadgeCheck size={12} className="shrink-0 text-primary" />
            )}
            {showPin && (
              <Pin size={11} className="shrink-0 text-muted-foreground" />
            )}
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
              {name}
            </span>
            {time && (
              <span className="shrink-0 text-xs text-muted-foreground">
                {time}
              </span>
            )}
          </span>
          <span className="flex items-center gap-1">
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {preview}
            </span>
            {chat.muted && (
              <BellOff
                size={12}
                className="shrink-0 text-muted-foreground/60"
              />
            )}
            {showUnreadBadge && (
              <span className="flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground">
                {chat.unread > 99 ? "99+" : chat.unread}
              </span>
            )}
          </span>
        </span>
      </span>
    </Button>
  );
}

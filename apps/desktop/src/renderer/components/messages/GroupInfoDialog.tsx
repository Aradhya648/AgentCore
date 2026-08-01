import { Button } from "@/components/ui";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useChatMembers, useMessagingStore } from "@/stores/messaging";
import { LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PresenceAvatar } from "./PresenceAvatar";
import { avatarInitial, chatDisplayName } from "./chatDisplay";

interface Props {
  chatId: string;
  open: boolean;
  onClose: () => void;
}

/** A pill switch for a per-chat flag (mute / pin). */
function Toggle({
  on,
  onToggle,
  label,
}: {
  on: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <Button
      variant="ghost"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      className="h-auto w-full justify-between px-1 py-2 text-sm hover:bg-accent/50"
    >
      <span className="text-foreground">{label}</span>
      <span
        className={`flex h-5 w-9 items-center rounded-full px-0.5 transition-colors ${
          on ? "bg-primary" : "bg-muted"
        }`}
      >
        <span
          className={`size-4 rounded-full bg-background transition-transform ${
            on ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </span>
    </Button>
  );
}

/**
 * 群信息 / 官方号会话设置: per-chat mute & pin. Groups also show roster + leave;
 * the official broadcast chat omits leave (backend 422) and the member list.
 */
export function GroupInfoDialog({ chatId, open, onClose }: Props) {
  const chat = useMessagingStore(
    (s) => s.chats.find((c) => c.id === chatId) ?? null,
  );
  const members = useChatMembers(chatId);
  const loadMembers = useMessagingStore((s) => s.loadMembers);
  const setMembershipFlags = useMessagingStore((s) => s.setMembershipFlags);
  const leaveChat = useMessagingStore((s) => s.leaveChat);
  const openProfile = useMessagingStore((s) => s.openProfile);
  const navigate = useNavigate();
  const [confirmingLeave, setConfirmingLeave] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    if (open) {
      setConfirmingLeave(false);
      if (chat?.type !== "official") void loadMembers(chatId);
    }
  }, [open, chatId, loadMembers, chat?.type]);

  if (!chat) return null;
  const name = chatDisplayName(chat);
  const isOfficial = chat.type === "official";

  const handleLeave = async () => {
    setLeaving(true);
    const ok = await leaveChat(chatId);
    setLeaving(false);
    if (ok) {
      onClose();
      navigate("/messages");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-sm" aria-describedby={undefined}>
        <div className="flex flex-col items-center gap-2 border-b border-border px-5 py-5">
          <span className="flex size-14 items-center justify-center rounded-full bg-primary/10 text-xl font-medium text-primary">
            {avatarInitial(name)}
          </span>
          <DialogTitle className="text-center">{name}</DialogTitle>
          <span className="text-xs text-muted-foreground">
            {isOfficial ? "官方广播" : `${members.length} 名成员`}
          </span>
        </div>

        <div className="px-4 py-2">
          <Toggle
            label="消息免打扰"
            on={chat.muted}
            onToggle={() =>
              void setMembershipFlags(chatId, { muted: !chat.muted })
            }
          />
          <Toggle
            label="置顶会话"
            on={chat.pinned}
            onToggle={() =>
              void setMembershipFlags(chatId, { pinned: !chat.pinned })
            }
          />
        </div>

        {!isOfficial && (
          <div className="min-h-0 border-t border-border">
            <p className="px-5 pb-1 pt-3 text-xs font-medium text-muted-foreground">
              成员
            </p>
            <ul className="max-h-60 overflow-y-auto px-2 pb-2">
              {members.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => openProfile(m.id)}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`查看 ${m.display_name || m.username} 的资料`}
                  >
                    <PresenceAvatar
                      label={avatarInitial(m.display_name || m.username)}
                      sizeClass="size-8"
                      textClass="text-sm"
                      online={!!m.online}
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-sm text-foreground">
                          {m.display_name || m.username}
                        </span>
                        {m.is_admin && (
                          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                            管理员
                          </span>
                        )}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {m.online ? "在线" : `@${m.username}`}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {!isOfficial && (
          <div className="border-t border-border px-5 py-4">
            {confirmingLeave ? (
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">
                  退出后需重新邀请才能再加入
                </span>
                <div className="flex shrink-0 gap-2">
                  <Button
                    variant="neutral"
                    onClick={() => setConfirmingLeave(false)}
                  >
                    取消
                  </Button>
                  <Button
                    variant="destructive"
                    className="disabled:opacity-50"
                    disabled={leaving}
                    onClick={() => void handleLeave()}
                  >
                    {leaving ? "退出中…" : "确认退出"}
                  </Button>
                </div>
              </div>
            ) : (
              <Button
                variant="danger"
                className="h-auto w-full py-2 text-sm"
                icon={<LogOut size={16} />}
                onClick={() => setConfirmingLeave(true)}
              >
                退出群聊
              </Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

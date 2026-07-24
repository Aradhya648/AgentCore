import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { formatMessageTime } from "@/lib/format";
import { notifyError } from "@/lib/toast";
import { deleteMessage } from "@/services/messages";
import { useConversationStore } from "@/stores/conversation";
import { Check, Trash2, X } from "lucide-react";
import { useState } from "react";

/** Small icon+label action shown beneath a message on hover. */
export function MessageAction({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button variant="neutral" className="px-1.5" icon={icon} onClick={onClick}>
      {label}
    </Button>
  );
}

export function DeleteMessageAction({
  messageId,
  compact = false,
}: {
  messageId: string;
  /** Icon-only toolbar style for the assistant message footer. */
  compact?: boolean;
}) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const [confirming, setConfirming] = useState(false);

  const onDelete = async () => {
    setConfirming(false);
    if (!conversationId) return;
    try {
      await deleteMessage(conversationId, messageId);
    } catch (err) {
      notifyError(err, "删除失败");
    }
  };

  if (confirming) {
    if (compact) {
      return (
        <span className="inline-flex items-center gap-0.5">
          <SimpleTooltip label="确认删除">
            <IconButton
              size="sm"
              tone="destructive"
              aria-label="确认删除"
              onClick={() => void onDelete()}
            >
              <Check size={14} />
            </IconButton>
          </SimpleTooltip>
          <SimpleTooltip label="取消">
            <IconButton
              size="sm"
              aria-label="取消"
              onClick={() => setConfirming(false)}
            >
              <X size={14} />
            </IconButton>
          </SimpleTooltip>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-0.5">
        <Button
          variant="danger"
          className="px-1.5"
          icon={<Check size={13} />}
          onClick={() => void onDelete()}
        >
          确认删除
        </Button>
        <Button
          variant="neutral"
          className="px-1.5"
          icon={<X size={13} />}
          onClick={() => setConfirming(false)}
        >
          取消
        </Button>
      </span>
    );
  }

  if (compact) {
    return (
      <SimpleTooltip label="删除">
        <IconButton
          size="sm"
          aria-label="删除"
          onClick={() => setConfirming(true)}
        >
          <Trash2 size={14} />
        </IconButton>
      </SimpleTooltip>
    );
  }

  return (
    <MessageAction
      icon={<Trash2 size={13} />}
      label="删除"
      onClick={() => setConfirming(true)}
    />
  );
}

export function MessageTime({ iso }: { iso: string }) {
  const label = formatMessageTime(iso);
  if (!label) return null;
  return (
    <SimpleTooltip label={new Date(iso).toLocaleString()}>
      <span className="ml-1 cursor-default text-xs text-muted-foreground/60">
        {label}
      </span>
    </SimpleTooltip>
  );
}

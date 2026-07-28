import { Button } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { formatMessageTimeOfDay } from "@/lib/format";
import type { ImBubbleLayout } from "@/lib/imMessageLayout";
import { notifyActionError } from "@/lib/toast";
import {
  type ChatMessageDetail,
  downloadChatAttachment,
  isImageAttachment,
} from "@/services/messaging";
import { Download, FileText, Folder } from "lucide-react";
import { ChatImageGallery } from "./ChatImageGallery";
import { avatarInitial, avatarSrc } from "./chatDisplay";

interface Props {
  message: ChatMessageDetail;
  /** Sent by the viewing user → right-aligned. */
  mine: boolean;
  /** Sender's display name, shown above the bubble in group threads (others only). */
  senderName?: string;
  /** Fallback label for the avatar initial. */
  avatarName?: string;
  /** Profile image when available. */
  senderAvatarUrl?: string | null;
  layout: ImBubbleLayout;
}

function textBubbleRadius(
  mine: boolean,
  position: ImBubbleLayout["clusterPosition"],
) {
  if (position === "single") return "rounded-xl";
  if (mine) {
    if (position === "first") return "rounded-xl rounded-br-sm";
    if (position === "middle") return "rounded-lg rounded-r-xl";
    return "rounded-xl rounded-tr-sm";
  }
  if (position === "first") return "rounded-xl rounded-bl-sm";
  if (position === "middle") return "rounded-lg rounded-l-xl";
  return "rounded-xl rounded-tl-sm";
}

/** Circular avatar: image when a URL exists, else a themed initial. */
function ChatAvatar({
  name,
  url,
}: {
  name: string;
  url?: string | null;
}) {
  const src = avatarSrc(url);
  if (src) {
    return (
      <img
        src={src}
        alt=""
        className="size-8 shrink-0 rounded-full object-cover"
      />
    );
  }
  return (
    <span
      className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary"
      aria-hidden
    >
      {avatarInitial(name)}
    </span>
  );
}

/** A human-readable byte size for a file chip (e.g. "1.2 MB"). */
function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * One IM message bubble. Human chat is rendered as plain wrapped text (not
 * Markdown): a stray `#`/`*` in a person's message shouldn't become a heading,
 * and own-bubble theming (primary background) would fight Markdown's fixed
 * foreground color.
 *
 * 富消息: image attachments render via {@link ChatImageGallery} (thumb grid +
 * lightbox); other files render as download chips. `system_card` (official
 * notices) renders as a centered system pill.
 */
export function ChatBubble({
  message,
  mine,
  senderName,
  avatarName,
  senderAvatarUrl,
  layout,
}: Props) {
  const time = formatMessageTimeOfDay(message.created_at);

  if (message.content_type === "system_card") {
    return (
      <div className="flex justify-center py-1">
        <span className="rounded-lg bg-muted px-2.5 py-1 text-xs text-muted-foreground">
          {message.content || "[通知]"}
        </span>
      </div>
    );
  }

  const attachments = message.attachments ?? [];
  const images = attachments.filter(
    (a) => a.kind !== "dir" && a.workspace_path && isImageAttachment(a.name),
  );
  const files = attachments.filter((a) => !images.includes(a));
  const hasText = Boolean(message.content);

  const avatarLabel = avatarName ?? senderName ?? "?";

  return (
    <div
      className={`group flex max-w-[75%] flex-col ${
        mine ? "ml-auto items-end" : "items-start"
      } ${layout.tightTop ? "-mt-1" : ""}`}
    >
      <div
        className={`flex items-start gap-2 ${mine ? "flex-row-reverse" : ""}`}
      >
        <div
          className={`mt-0.5 shrink-0 ${layout.showAvatar ? "" : "invisible"}`}
          aria-hidden={!layout.showAvatar}
        >
          <ChatAvatar name={avatarLabel} url={senderAvatarUrl} />
        </div>

        <div
          className={`flex min-w-0 flex-col ${
            mine ? "items-end" : "flex-1 items-start"
          }`}
        >
          {!mine && layout.showSenderName && senderName && (
            <span className="mb-0.5 px-1 text-xs text-muted-foreground">
              {senderName}
            </span>
          )}

          <div
            className={`flex flex-col gap-1.5 ${
              mine ? "items-end" : "items-start"
            }`}
          >
            {hasText && (
              <div
                className={`whitespace-pre-wrap break-words px-3 py-2 text-sm ${textBubbleRadius(
                  mine,
                  layout.clusterPosition,
                )} ${
                  mine
                    ? "bg-primary text-primary-foreground"
                    : "border border-border bg-card text-foreground"
                }`}
              >
                {message.content}
              </div>
            )}

            {images.length > 0 && (
              <ChatImageGallery chatId={message.chat_id} images={images} />
            )}

            {files.map((a) => {
              const downloadable =
                a.kind !== "dir" && Boolean(a.workspace_path);
              return (
                <Button
                  key={a.workspace_path ?? a.path}
                  variant="ghost"
                  disabled={!downloadable}
                  onClick={() =>
                    downloadable &&
                    a.workspace_path &&
                    void downloadChatAttachment(
                      message.chat_id,
                      a.workspace_path,
                      a.name,
                    ).catch((e) => notifyActionError("下载失败", e))
                  }
                  className={`h-auto w-full max-w-[260px] gap-2 rounded-xl border border-border bg-card px-3 py-2 font-normal ${
                    mine ? "justify-end text-right" : "justify-start text-left"
                  } ${downloadable ? "hover:bg-accent" : "opacity-70"}`}
                >
                  <span className="flex w-full items-center gap-2">
                    {a.kind === "dir" ? (
                      <Folder
                        size={16}
                        className="shrink-0 text-muted-foreground"
                      />
                    ) : (
                      <FileText
                        size={16}
                        className="shrink-0 text-muted-foreground"
                      />
                    )}
                    <span className="min-w-0 flex-1">
                      <SimpleTooltip label={a.name}>
                        <span className="block truncate text-sm text-foreground">
                          {a.name}
                          {a.kind === "dir" ? "/" : ""}
                        </span>
                      </SimpleTooltip>
                      {a.size_bytes != null && (
                        <span className="block text-xs text-muted-foreground">
                          {formatBytes(a.size_bytes)}
                        </span>
                      )}
                    </span>
                    {downloadable && (
                      <Download
                        size={14}
                        className="shrink-0 text-muted-foreground"
                      />
                    )}
                  </span>
                </Button>
              );
            })}
          </div>
        </div>
      </div>

      {time && (
        <SimpleTooltip label={new Date(message.created_at).toLocaleString()}>
          <span
            className={`cursor-default px-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 ${
              mine ? "mr-10" : "ml-10"
            }`}
          >
            {time}
          </span>
        </SimpleTooltip>
      )}
    </div>
  );
}

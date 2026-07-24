import { Button } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { downloadWorkspaceFile } from "@/services/workspace";
import type { MessageAttachmentMeta } from "@/stores/conversation";
import { Download, Folder, MessageSquare, Paperclip } from "lucide-react";
import { useState } from "react";

export function AttachmentChip({
  att,
  conversationId,
}: {
  att: MessageAttachmentMeta;
  conversationId: string | null;
}) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const downloadable =
    att.kind !== "dir" && !!att.workspacePath && !!conversationId;

  const base =
    "inline-flex max-w-[220px] items-center gap-1.5 rounded-lg bg-accent px-2 py-1 text-xs text-accent-foreground";
  const icon =
    att.kind === "dir" ? (
      <Folder size={12} className="shrink-0" />
    ) : att.kind === "conversation" ? (
      <MessageSquare size={12} className="shrink-0" />
    ) : (
      <Paperclip size={12} className="shrink-0" />
    );
  const label = (
    <>
      <span className="truncate">
        {att.name}
        {att.kind === "dir" ? "/" : ""}
      </span>
      {att.truncated && (
        <span className="shrink-0 text-muted-foreground">
          {att.kind === "dir"
            ? "部分"
            : att.kind === "conversation"
              ? "近期"
              : "已截断"}
        </span>
      )}
    </>
  );

  if (!downloadable) {
    return (
      <SimpleTooltip
        label={att.kind === "conversation" ? "引用对话" : att.path}
      >
        <span className={base}>
          {icon}
          {label}
        </span>
      </SimpleTooltip>
    );
  }

  const onDownload = async () => {
    if (state === "loading") return;
    setState("loading");
    try {
      await downloadWorkspaceFile(
        conversationId as string,
        att.workspacePath as string,
        att.name,
      );
      setState("idle");
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2000);
    }
  };

  return (
    <SimpleTooltip
      label={state === "error" ? "下载失败，点击重试" : `下载 ${att.name}`}
    >
      <Button
        variant="ghost"
        onClick={onDownload}
        className={`${base} h-auto transition-colors hover:bg-accent/70 ${
          state === "error" ? "text-destructive" : ""
        }`}
      >
        {icon}
        {label}
        <Download
          size={12}
          className={`shrink-0 ${state === "loading" ? "animate-pulse" : "opacity-60"}`}
        />
      </Button>
    </SimpleTooltip>
  );
}

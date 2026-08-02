import { IconButton } from "@/components/ui";
import { statusAccentText, statusChip } from "@/components/ui/tone-presets";
import { cn } from "@/lib/utils";
import { useWorkspaceChannelStore } from "@/stores/workspaceChannel";
import { AlertTriangle, X } from "lucide-react";

/**
 * Soft hint when the local file channel hung (活性挂起). Hint-only — no ban on
 * open/write, no one-click channel rebuild. Dismissible for the moment; a later
 * file-op hang can raise it again.
 */
export function WorkspaceChannelBanner() {
  const notReady = useWorkspaceChannelStore((s) => s.notReady);
  const dismiss = useWorkspaceChannelStore((s) => s.dismiss);

  if (!notReady) return null;

  return (
    // biome-ignore lint/a11y/useSemanticElements: 内嵌关闭按钮，保留 aria live 容器。
    <div
      role="status"
      className={cn(
        "flex shrink-0 items-center gap-2 border-b px-3 py-2 text-sm",
        statusChip.primary,
      )}
    >
      <AlertTriangle
        size={15}
        className={cn("shrink-0", statusAccentText.primary)}
      />
      <span className="min-w-0 flex-1 text-foreground">
        本地文件通道未就绪。请重试当前操作，或重新打开应用后再试。
      </span>
      <IconButton
        onClick={() => dismiss()}
        aria-label="关闭"
        className="text-muted-foreground hover:bg-transparent hover:text-foreground"
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}

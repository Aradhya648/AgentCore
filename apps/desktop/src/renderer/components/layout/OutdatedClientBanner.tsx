import { Button, IconButton } from "@/components/ui";
import { statusAccentText, statusChip } from "@/components/ui/tone-presets";
import { hasAutoUpdater } from "@/lib/capabilities";
import { cn } from "@/lib/utils";
import { useUpdatesStore } from "@/stores/updates";
import { AlertTriangle, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

/**
 * Soft outdated-client banner under the title bar (部署与运维.md §7.6).
 * Shown when local Electron build < policy.min_desktop_version. Dismissible for
 * the session; CTA opens the update dialog when a version is already available,
 * otherwise jumps to 设置·关于 and triggers a check. Web clients never render
 * this ({@link hasAutoUpdater} is false).
 */
export function OutdatedClientBanner() {
  const navigate = useNavigate();
  const minVersion = useUpdatesStore((s) => s.outdatedMinVersion);
  const dismissed = useUpdatesStore((s) => s.outdatedDismissed);
  const dismiss = useUpdatesStore((s) => s.dismissOutdated);
  const status = useUpdatesStore((s) => s.status);
  const check = useUpdatesStore((s) => s.check);
  const openUpdateDialog = useUpdatesStore((s) => s.openUpdateDialog);

  if (!hasAutoUpdater() || !minVersion || dismissed) return null;

  return (
    // biome-ignore lint/a11y/useSemanticElements: 内嵌 CTA / 关闭按钮，<output> 语义不符——保留 aria live 容器。
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
        当前版本过旧，请更新后继续使用
      </span>
      <Button
        variant="primary"
        size="sm"
        className="shrink-0"
        onClick={() => {
          if (
            status.phase === "available" ||
            status.phase === "downloading" ||
            status.phase === "downloaded"
          ) {
            openUpdateDialog();
            return;
          }
          navigate("/more/about");
          void check();
        }}
      >
        去更新
      </Button>
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

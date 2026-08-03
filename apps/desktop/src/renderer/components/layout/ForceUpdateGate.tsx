import { Button } from "@/components/ui";
import { hasAutoUpdater } from "@/lib/capabilities";
import { clientVersion } from "@/lib/clientBuildInfo";
import { formatDownloadProgress } from "@/lib/format";
import { useUpdatesStore } from "@/stores/updates";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Hard force-update gate (部署与运维 / 发布与门禁 §7.6).
 * Shown when local Electron build < policy.min_desktop_version. Blocks AppShell
 * until the client is updated; web clients never render ({@link hasAutoUpdater}
 * is false). Fail-open: missing policy leaves this hidden.
 */
export function ForceUpdateGate() {
  const minVersion = useUpdatesStore((s) => s.outdatedMinVersion);
  const status = useUpdatesStore((s) => s.status);
  const check = useUpdatesStore((s) => s.check);
  const download = useUpdatesStore((s) => s.download);
  const install = useUpdatesStore((s) => s.install);
  const openUpdateDialog = useUpdatesStore((s) => s.openUpdateDialog);

  if (!hasAutoUpdater() || !minVersion) return null;

  const current = clientVersion();
  const checking = status.phase === "checking";
  const downloading = status.phase === "downloading";
  const available = status.phase === "available";
  const downloaded = status.phase === "downloaded";

  let ctaLabel = "检查更新";
  let ctaDisabled = false;
  let ctaIcon: ReactNode = null;
  let onCta: () => void = () => {
    void check();
  };

  if (downloaded) {
    ctaLabel = "重启安装";
    onCta = () => {
      void install();
    };
  } else if (downloading) {
    ctaLabel = "下载中…";
    ctaDisabled = true;
    ctaIcon = <Loader2 size={14} className="animate-spin" />;
    onCta = () => {};
  } else if (available) {
    ctaLabel = "立即更新";
    onCta = () => {
      openUpdateDialog();
      void download();
    };
  } else if (checking) {
    ctaLabel = "检查中…";
    ctaDisabled = true;
    ctaIcon = <Loader2 size={14} className="animate-spin" />;
    onCta = () => {};
  }

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="force-update-title"
      aria-describedby="force-update-desc"
      className="fixed inset-0 z-40 flex items-center justify-center bg-background/95 p-6"
    >
      <div className="flex w-full max-w-md flex-col items-center gap-4 text-center">
        <AlertTriangle size={28} className="text-primary" aria-hidden />
        <h1
          id="force-update-title"
          className="text-base font-semibold text-foreground"
        >
          当前版本过旧，须更新后才能继续使用
        </h1>
        <p id="force-update-desc" className="text-sm text-muted-foreground">
          当前版本 {current} · 最低要求 {minVersion}
        </p>

        {downloading ? (
          <div className="w-full space-y-2 text-left">
            <p className="text-sm text-muted-foreground">
              下载进度{" "}
              {formatDownloadProgress({
                percent: status.percent,
                transferred: status.transferred,
                total: status.total,
                bytesPerSecond: status.bytesPerSecond,
              })}
            </p>
            <progress
              className="h-2 w-full overflow-hidden rounded-full bg-muted [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
              value={Math.min(100, status.percent)}
              max={100}
            />
          </div>
        ) : null}

        {status.phase === "error" ? (
          <p className="text-sm text-destructive">{status.message}</p>
        ) : null}

        <Button
          variant="primary"
          size="md"
          disabled={ctaDisabled}
          icon={ctaIcon}
          onClick={onCta}
        >
          {ctaLabel}
        </Button>
      </div>
    </div>
  );
}

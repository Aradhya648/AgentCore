import { Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { hasAutoUpdater } from "@/lib/capabilities";
import { clientVersion } from "@/lib/clientBuildInfo";
import { formatBytes, formatDownloadProgress } from "@/lib/format";
import { UPDATE_NOTES_FALLBACK, useUpdatesStore } from "@/stores/updates";
import { Loader2 } from "lucide-react";

/**
 * Consent-first update explanation dialog (发布与门禁.md §7.6).
 * Opens on `available` (subject to skip/snooze); shows download progress when
 * downloading; closable anytime — About page keeps mirroring status.
 */
export function UpdateAvailableDialog() {
  const dialogOpen = useUpdatesStore((s) => s.dialogOpen);
  const status = useUpdatesStore((s) => s.status);
  const closeUpdateDialog = useUpdatesStore((s) => s.closeUpdateDialog);
  const download = useUpdatesStore((s) => s.download);
  const remindLater = useUpdatesStore((s) => s.remindLater);
  const skipVersion = useUpdatesStore((s) => s.skipVersion);
  const install = useUpdatesStore((s) => s.install);

  if (!hasAutoUpdater()) return null;

  const version =
    status.phase === "available" ||
    status.phase === "downloading" ||
    status.phase === "downloaded"
      ? status.version
      : null;

  const relevant =
    status.phase === "available" ||
    status.phase === "downloading" ||
    status.phase === "downloaded" ||
    status.phase === "error";

  const open = dialogOpen && relevant;

  const releaseNotes =
    status.phase === "available"
      ? status.releaseNotes?.trim() || UPDATE_NOTES_FALLBACK
      : UPDATE_NOTES_FALLBACK;

  const sizeBytes =
    status.phase === "available" ? (status.sizeBytes ?? null) : null;

  const current = clientVersion();
  const title =
    status.phase === "downloaded"
      ? `新版本 ${version} 已就绪`
      : status.phase === "downloading"
        ? `正在下载 ${version}`
        : status.phase === "error"
          ? "更新失败"
          : `发现新版本 ${version ?? ""}`;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) closeUpdateDialog();
      }}
    >
      {relevant ? (
        <DialogContent
          className="flex max-h-[min(80vh,32rem)] max-w-md flex-col gap-0 p-0"
          showClose
        >
          <DialogHeader className="pr-10">
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>

          <DialogDescription asChild>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-2">
              {status.phase === "available" ? (
                <>
                  <p className="text-sm text-muted-foreground">
                    当前版本 {current}
                    {sizeBytes != null && sizeBytes > 0
                      ? ` · 安装包约 ${formatBytes(sizeBytes)}`
                      : null}
                  </p>
                  <p className="whitespace-pre-wrap text-sm text-foreground">
                    {releaseNotes}
                  </p>
                </>
              ) : null}

              {status.phase === "downloading" ? (
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">
                    下载进度{" "}
                    {formatDownloadProgress({
                      percent: status.percent,
                      transferred: status.transferred,
                      total: status.total,
                      bytesPerSecond: status.bytesPerSecond,
                    })}{" "}
                    — 可关闭本窗口，进度仍可在「设置 · 关于」查看。
                  </p>
                  <progress
                    className="h-2 w-full overflow-hidden rounded-full bg-muted [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
                    value={Math.min(100, status.percent)}
                    max={100}
                  />
                </div>
              ) : null}

              {status.phase === "downloaded" ? (
                <p className="text-sm text-muted-foreground">
                  将在重启后安装。也可稍后在「设置 · 关于」安装。
                </p>
              ) : null}

              {status.phase === "error" ? (
                <p className="text-sm text-destructive">{status.message}</p>
              ) : null}
            </div>
          </DialogDescription>

          <DialogFooter>
            {status.phase === "available" ? (
              <>
                <Button variant="ghost" size="md" onClick={() => skipVersion()}>
                  跳过此版本
                </Button>
                <Button
                  variant="neutral"
                  size="md"
                  onClick={() => remindLater()}
                >
                  稍后提醒
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => void download()}
                >
                  立即更新
                </Button>
              </>
            ) : null}

            {status.phase === "downloading" ? (
              <Button
                variant="neutral"
                size="md"
                icon={<Loader2 size={14} className="animate-spin" />}
                onClick={() => closeUpdateDialog()}
              >
                后台下载
              </Button>
            ) : null}

            {status.phase === "downloaded" ? (
              <Button
                variant="primary"
                size="md"
                onClick={() => void install()}
              >
                重启安装
              </Button>
            ) : null}

            {status.phase === "error" ? (
              <>
                <Button
                  variant="neutral"
                  size="md"
                  onClick={() => closeUpdateDialog()}
                >
                  关闭
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => void download()}
                >
                  重试下载
                </Button>
              </>
            ) : null}
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

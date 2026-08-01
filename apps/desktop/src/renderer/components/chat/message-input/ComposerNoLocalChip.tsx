import { SimpleTooltip } from "@/components/ui/tooltip";
import { isWebRuntime } from "@/lib/capabilities";
import { openDesktopDownloadPage } from "@/lib/desktopDownload";
import { MonitorOff } from "lucide-react";

/**
 * Web-only composer chip: signals no local Host capabilities and offers the
 * official desktop download CTA. Hidden in Electron (local ability is via Host).
 */
export function ComposerNoLocalChip() {
  if (!isWebRuntime()) return null;

  return (
    <SimpleTooltip label="网页版无本机文件、终端等能力；下载桌面端以使用本机能力">
      <button
        type="button"
        data-testid="composer-no-local-chip"
        onClick={openDesktopDownloadPage}
        className="inline-flex h-7 max-w-[220px] shrink items-center gap-1 px-1.5 text-xs font-normal text-muted-foreground hover:text-foreground"
        aria-label="网页版无本机能力，下载桌面端"
      >
        <MonitorOff size={12} className="shrink-0" aria-hidden />
        <span className="min-w-0 truncate">网页版 · 无本机</span>
        <span className="shrink-0 text-primary underline-offset-2 hover:underline">
          下载
        </span>
      </button>
    </SimpleTooltip>
  );
}

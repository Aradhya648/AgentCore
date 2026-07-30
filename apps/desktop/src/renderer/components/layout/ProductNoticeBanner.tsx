import { Button, IconButton } from "@/components/ui";
import {
  type StatusTone,
  statusAccentText,
  statusChip,
} from "@/components/ui/tone-presets";
import { cn } from "@/lib/utils";
import type { ActiveNotice } from "@/services/notices";
import { useProductNoticesStore } from "@/stores/productNotices";
import { AlertTriangle, Info, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

/** Map notice severity → tone-presets (no hardcoded hex / warning slot). */
export function noticeSeverityTone(severity: string): StatusTone {
  switch (severity) {
    case "critical":
      return "destructive";
    case "high":
      return "primary";
    default:
      return "muted";
  }
}

/** http(s) → system browser; in-app `#/…` or `/…` path → navigate. */
export function openNoticeCta(
  url: string,
  navigate: (to: string) => void,
): void {
  const trimmed = url.trim();
  if (!trimmed) return;
  // Hash-router deep links from ops CTA (e.g. `#/more/providers`).
  if (trimmed.startsWith("#/")) {
    navigate(trimmed.slice(1));
    return;
  }
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) {
    navigate(trimmed);
    return;
  }
  if (/^https?:\/\//i.test(trimmed)) {
    window.open(trimmed, "_blank", "noopener,noreferrer");
  }
}

/**
 * Product notice banner under the title bar (layout mirrors OutdatedClientBanner).
 * Store already picks ≤1 banner; critical/high/normal use tone-presets.
 */
export function ProductNoticeBanner() {
  const navigate = useNavigate();
  const banner = useProductNoticesStore((s) => s.banner);
  const dismiss = useProductNoticesStore((s) => s.dismiss);

  if (!banner) return null;

  return (
    <NoticeBannerRow notice={banner} onDismiss={dismiss} navigate={navigate} />
  );
}

function NoticeBannerRow({
  notice,
  onDismiss,
  navigate,
}: {
  notice: ActiveNotice;
  onDismiss: (id: string) => Promise<void>;
  navigate: (to: string) => void;
}) {
  const tone = noticeSeverityTone(notice.severity);
  const Icon = tone === "destructive" ? AlertTriangle : Info;

  return (
    // biome-ignore lint/a11y/useSemanticElements: 内嵌 CTA / 关闭按钮，<output> 语义不符——保留 aria live 容器。
    <div
      role="status"
      className={cn(
        "flex shrink-0 items-center gap-2 border-b px-3 py-2 text-sm",
        statusChip[tone],
      )}
    >
      <Icon size={15} className={cn("shrink-0", statusAccentText[tone])} />
      <span className="min-w-0 flex-1 text-foreground">{notice.title}</span>
      {notice.cta_label && notice.cta_url ? (
        <Button
          variant="primary"
          size="sm"
          className="shrink-0"
          onClick={() => {
            const url = notice.cta_url;
            if (url) openNoticeCta(url, navigate);
          }}
        >
          {notice.cta_label}
        </Button>
      ) : null}
      {/* Banner always closable (industry default). once → server dismiss; never → session snooze. */}
      <IconButton
        onClick={() => void onDismiss(notice.id)}
        aria-label="关闭公告"
        className="text-muted-foreground hover:bg-transparent hover:text-foreground"
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}

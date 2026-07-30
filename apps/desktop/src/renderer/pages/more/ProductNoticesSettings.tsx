import {
  noticeSeverityTone,
  openNoticeCta,
} from "@/components/layout/ProductNoticeBanner";
import { Button } from "@/components/ui";
import { statusPillInline } from "@/components/ui/tone-presets";
import { cn } from "@/lib/utils";
import type { ActiveNotice } from "@/services/notices";
import { useProductNoticesStore } from "@/stores/productNotices";
import { ChevronDown, ChevronRight, Megaphone } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SettingsHeader } from "./SettingsHeader";

const SEVERITY_LABEL: Record<string, string> = {
  critical: "紧急",
  high: "重要",
  normal: "一般",
};

/**
 * 设置 · 公告 (/more/notices) — 轻量 inbox，回看 / dismiss 产品全局公告。
 * 与 IM / 自动化收件箱数据与命名分离。
 */
export function ProductNoticesSettings() {
  const navigate = useNavigate();
  const inbox = useProductNoticesStore((s) => s.inbox);
  const dismiss = useProductNoticesStore((s) => s.dismiss);
  const loading = useProductNoticesStore((s) => s.loading);

  const sorted = useMemo(() => {
    return [...inbox].sort((a, b) => {
      if (a.dismissed !== b.dismissed) return a.dismissed ? 1 : -1;
      const ta = a.published_at ? Date.parse(a.published_at) : 0;
      const tb = b.published_at ? Date.parse(b.published_at) : 0;
      return tb - ta;
    });
  }, [inbox]);

  return (
    <div className="space-y-6">
      <SettingsHeader
        title="公告"
        description="产品更新与重要通知；关闭后可在此回看。"
      />

      {sorted.length === 0 && !loading ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-border bg-muted/20 px-4 py-10 text-center">
          <Megaphone size={20} className="text-muted-foreground" />
          <p className="text-sm text-muted-foreground">暂无公告</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {sorted.map((notice) => (
            <NoticeInboxItem
              key={notice.id}
              notice={notice}
              onDismiss={dismiss}
              navigate={navigate}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function NoticeInboxItem({
  notice,
  onDismiss,
  navigate,
}: {
  notice: ActiveNotice;
  onDismiss: (id: string) => Promise<void>;
  navigate: (to: string) => void;
}) {
  const [open, setOpen] = useState(!notice.dismissed);
  const tone = noticeSeverityTone(notice.severity);
  const canDismiss = notice.dismiss_policy !== "never" && !notice.dismissed;
  const neverClosable = notice.dismiss_policy === "never";
  const ctaUrl = notice.cta_url;
  const ctaLabel = notice.cta_label;

  return (
    <li
      className={cn(
        "rounded-lg border border-border bg-card",
        notice.dismissed && "opacity-70",
      )}
    >
      <button
        type="button"
        className="flex w-full items-start gap-2 px-3 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown
            size={16}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
        ) : (
          <ChevronRight
            size={16}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-foreground">
              {notice.title}
            </span>
            <span className={statusPillInline[tone]}>
              {SEVERITY_LABEL[notice.severity] ?? notice.severity}
            </span>
            {notice.dismissed ? (
              <span className={statusPillInline.muted}>已关闭</span>
            ) : null}
            {neverClosable ? (
              <span className={statusPillInline.muted}>不可关闭</span>
            ) : null}
          </div>
          {notice.published_at ? (
            <p className="text-xs text-muted-foreground">
              {formatPublished(notice.published_at)}
            </p>
          ) : null}
        </div>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-border px-3 py-3 pl-9">
          <p className="whitespace-pre-wrap text-sm text-foreground">
            {notice.body}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {ctaLabel && ctaUrl ? (
              <Button
                variant="primary"
                size="sm"
                onClick={() => openNoticeCta(ctaUrl, navigate)}
              >
                {ctaLabel}
              </Button>
            ) : null}
            {canDismiss ? (
              <Button
                variant="neutral"
                size="sm"
                onClick={() => void onDismiss(notice.id)}
              >
                关闭
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </li>
  );
}

function formatPublished(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

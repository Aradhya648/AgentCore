import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  CircleOff,
  CircleSlash,
  type LucideIcon,
  Repeat,
  TrendingDown,
} from "lucide-react";

export const FINISH_REASON_META: Record<
  string,
  { label: string; Icon: LucideIcon; tone: "muted" }
> = {
  cancelled: {
    label: "已中断 · 已保存完成的部分",
    Icon: CircleSlash,
    tone: "muted",
  },
  interrupted: {
    label: "已中断，可重试",
    Icon: CircleSlash,
    tone: "muted",
  },
  max_rounds: {
    label: "已达最大轮次 · 提前收尾",
    Icon: Repeat,
    tone: "muted",
  },
  degraded: {
    label: "降级完成 · 模型多次空响应",
    Icon: TrendingDown,
    tone: "muted",
  },
  unproductive: {
    label: "无有效进展 · 提前收尾",
    Icon: CircleOff,
    tone: "muted",
  },
  error: {
    label: "调用失败",
    Icon: AlertTriangle,
    tone: "muted",
  },
};

/** Top-of-bubble chip for abnormal turn endings (前端UX设计.md §一B finishReasonChip). */
export function FinishReasonChip({
  reason,
  diagnosisLabel,
  className,
}: {
  reason: string | undefined;
  /** When degraded due to empty response, show diagnosis instead of the default label. */
  diagnosisLabel?: string;
  className?: string;
}) {
  const meta = reason ? FINISH_REASON_META[reason] : undefined;
  if (!meta) return null;
  const { Icon } = meta;
  const label =
    reason === "degraded" && diagnosisLabel
      ? `降级完成 · ${diagnosisLabel}`
      : meta.label;
  return (
    <Badge
      tone="muted"
      pill
      className={`mb-1.5 inline-flex items-center gap-1.5 px-2 py-0.5 font-normal ${className ?? ""}`}
    >
      <Icon size={14} />
      {label}
    </Badge>
  );
}

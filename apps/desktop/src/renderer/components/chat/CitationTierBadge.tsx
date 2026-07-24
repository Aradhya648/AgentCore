/**
 * 来源卡可信度徽标——渲染 Citation.tier（官方 / 媒体 / 待评 / 弱源）。
 * 配色走语义 token（color-tokens.mdc）；未知 / 缺字段不渲染（legacy 卡零噪音）。
 */

const TIER_META: Record<string, { label: string; className: string }> = {
  official: {
    label: "官方",
    className: "bg-success/10 text-success",
  },
  media: {
    label: "媒体",
    className: "bg-primary/10 text-primary",
  },
  unknown: {
    label: "待评",
    className: "bg-muted text-muted-foreground",
  },
  weak: {
    label: "弱源",
    className: "bg-warning/10 text-warning",
  },
};

export function CitationTierBadge({
  tier,
}: {
  tier?: string | null;
}) {
  if (!tier) return null;
  const meta = TIER_META[tier];
  if (!meta) return null;
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 text-xs font-medium ${meta.className}`}
      title={`来源可信度：${meta.label}`}
    >
      {meta.label}
    </span>
  );
}

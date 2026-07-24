import { statusPillInline } from "@/components/ui/tone-presets";
import type { DebateFindingInfo } from "@/types/events";

/** finding 严重度三档 → 展示元数据（与 RiskBoard 旧 high/medium/low 视觉家族对齐）。 */
export const FINDING_SEVERITY = {
  critical: {
    label: "致命",
    rank: 0,
    pill: statusPillInline.destructive,
    surface: "border-l-2 border-destructive/50 pl-2.5",
  },
  major: {
    label: "重大",
    rank: 1,
    pill: statusPillInline.muted,
    surface: "border-l-2 border-border pl-2.5",
  },
  minor: {
    label: "次要",
    rank: 2,
    pill: statusPillInline.muted,
    surface: "border-l-2 border-border pl-2.5",
  },
} as const;

export type FindingSeverity = keyof typeof FINDING_SEVERITY;

/** finding 生命周期状态徽章。 */
export const FINDING_STATUS = {
  open: { label: "待回应", pill: statusPillInline.primary },
  answered: { label: "已回应", pill: statusPillInline.muted },
  closed: { label: "已关闭", pill: statusPillInline.success },
  escalated: { label: "升级", pill: statusPillInline.destructive },
  deadlocked: { label: "僵持", pill: statusPillInline.muted },
  unanswered: { label: "未回应", pill: statusPillInline.destructive },
} as const;

export type FindingStatus = keyof typeof FINDING_STATUS;

const DISPOSITION_LABELS: Record<string, string> = {
  accept: "接受",
  mitigate: "缓解",
  rebut: "反驳",
  defer: "挂起",
};

export function findingDispositionLabel(raw: string): string {
  const key = raw.trim().toLowerCase();
  return DISPOSITION_LABELS[key] ?? (raw.trim() || "");
}

/** 门决枚举 → 人话（brief.gate）。 */
export const GATE_LABELS: Record<string, string> = {
  conditional_pass: "有条件通过",
  needs_major_rework: "需重大修改",
  not_viable: "不可行",
};

export function gateLabel(gate: string | undefined): string | null {
  if (!gate) return null;
  return GATE_LABELS[gate] ?? gate;
}

export function findingSeverityRank(
  severity: DebateFindingInfo["severity"],
): number {
  return FINDING_SEVERITY[severity]?.rank ?? 99;
}

/** 按严重度危→轻、同档按 id 排序。 */
export function sortFindings<
  T extends { id: string; severity: FindingSeverity },
>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => {
    const d = findingSeverityRank(a.severity) - findingSeverityRank(b.severity);
    return d !== 0 ? d : a.id.localeCompare(b.id);
  });
}

/** 门决/盘口用：按 status 计数。 */
export function findingStatusCounts(
  findings: readonly { status: FindingStatus }[],
): Partial<Record<FindingStatus, number>> {
  const counts: Partial<Record<FindingStatus, number>> = {};
  for (const f of findings) {
    counts[f.status] = (counts[f.status] ?? 0) + 1;
  }
  return counts;
}

/**
 * risk_ack option labels may start with a severity tag: `[高]` / `[中]` / `[低]`.
 * Missing prefix → plain row (no severity chrome).
 */
export type RiskSeverity = "high" | "medium" | "low";

const SEVERITY_RE = /^\[(高|中|低)\]\s*/;

const SEVERITY_MAP: Record<"高" | "中" | "低", RiskSeverity> = {
  高: "high",
  中: "medium",
  低: "low",
};

export function parseRiskLabel(label: string): {
  severity: RiskSeverity | null;
  text: string;
} {
  const m = SEVERITY_RE.exec(label);
  if (!m) return { severity: null, text: label };
  const tag = m[1] as "高" | "中" | "低";
  return {
    severity: SEVERITY_MAP[tag],
    text: label.slice(m[0].length).trim() || label,
  };
}

export const RISK_SEVERITY_META: Record<
  RiskSeverity,
  { tag: string; chip: string; border: string }
> = {
  high: {
    tag: "高",
    chip: "bg-destructive/10 text-destructive",
    border: "border-destructive/35",
  },
  medium: {
    tag: "中",
    chip: "bg-warning/10 text-warning",
    border: "border-warning/35",
  },
  low: {
    tag: "低",
    chip: "bg-muted text-muted-foreground",
    border: "border-border",
  },
};

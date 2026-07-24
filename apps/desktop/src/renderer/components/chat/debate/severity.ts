import { statusPillInline } from "@/components/ui/tone-presets";
import type { DebateBriefInfo, DebateSideInfo } from "@/types/events";

/**
 * 红队风险严重度三档 → 展示元数据（与后端 `risk_severities` 的 high/medium/low 同口径）——**单一源**：
 * 流末终审「风险清单」（{@link import("./arena/brief").BriefCard} 内 RiskBoard）与记分牌紧凑「风险
 * 盘口」（{@link import("./arena/Scoreboard").Scoreboard} 红队行）共用这一套档位语义 / 配色 / 排序，
 * 避免两处各写一套危度色而漂移。注意语义与 `confidencePill` 相反：风险 high=最坏=destructive(红)、
 * low=最轻=muted(灰)，故另起一套而非复用置信色。`rank` 决定看板 / 盘口内由危到轻的排序。
 */
export const RISK_SEVERITY = {
  high: {
    label: "高危",
    rank: 0,
    pill: statusPillInline.destructive,
    surface: "border-l-2 border-destructive/50 pl-2.5",
  },
  medium: {
    label: "中危",
    rank: 1,
    pill: statusPillInline.muted,
    surface: "border-l-2 border-border pl-2.5",
  },
  low: {
    label: "低危",
    rank: 2,
    pill: statusPillInline.muted,
    surface: "border-l-2 border-border pl-2.5",
  },
} as const;
export type RiskLevel = keyof typeof RISK_SEVERITY;
export const RISK_LEVELS = ["high", "medium", "low"] as const;
export type RiskItem = {
  side: DebateSideInfo;
  text: string;
  level: RiskLevel | null;
};

/** 把后端风险严重度（已归一为 high/medium/low）映射成档位；容忍中文「高/中/低」与同义词，识别不到
 *  返回 null = 未评级（看板 / 盘口降级为中性卡，不杜撰档位）。 */
export function riskLevelOf(raw: string | undefined): RiskLevel | null {
  if (!raw) return null;
  const s = raw.trim().toLowerCase();
  if ((RISK_LEVELS as readonly string[]).includes(s)) return s as RiskLevel;
  if (s.includes("high") || raw.includes("高")) return "high";
  if (s.includes("low") || raw.includes("低")) return "low";
  if (s.includes("medium") || raw.includes("中")) return "medium";
  return null;
}

export function rankOf(level: RiskLevel | null): number {
  return level ? RISK_SEVERITY[level].rank : 99;
}

/**
 * 从 roster + brief 建红队风险清单（旧降级路径：按方 `risk_severities`）。
 * 新场次权威是 `brief.findings`（Phase 2 英雄区按 finding 线程渲染）；本函数仅服务旧磁带 /
 * 缺 findings 时的 RiskBoard 降级。被审方案方不入清单。
 */
export function buildRiskItems(
  sides: DebateSideInfo[],
  brief: DebateBriefInfo,
): RiskItem[] {
  // 新场次有 finding 台账时仍可由旧看板降级拼一条「按攻击方聚合」视图（Phase 2 替换）。
  if (brief.findings?.length) {
    const byAttacker = new Map<
      string,
      { text: string; level: RiskLevel | null }
    >();
    for (const f of brief.findings) {
      const mapped =
        f.severity === "critical"
          ? "high"
          : f.severity === "major"
            ? "medium"
            : "low";
      const prev = byAttacker.get(f.attacker_key);
      if (!prev || rankOf(mapped) < rankOf(prev.level)) {
        byAttacker.set(f.attacker_key, {
          text: f.target || f.id,
          level: mapped,
        });
      }
    }
    return sides
      .filter((s) => !s.is_subject && byAttacker.has(s.key))
      .flatMap((s) => {
        const hit = byAttacker.get(s.key);
        if (!hit) return [];
        return [{ side: s, text: hit.text, level: hit.level }];
      });
  }
  const severities = brief.risk_severities ?? {};
  return sides
    .filter((s) => !s.is_subject)
    .map((s) => ({
      side: s,
      text: brief.strongest_points[s.key],
      level: riskLevelOf(severities[s.key]),
    }))
    .filter((r): r is RiskItem => Boolean(r.text));
}

/** 风险清单按档位计数（盘口）——高 / 中 / 低各几条，未评级不计。看板与盘口共用。 */
export function riskCounts(risks: RiskItem[]): Record<RiskLevel, number> {
  const counts: Record<RiskLevel, number> = { high: 0, medium: 0, low: 0 };
  for (const r of risks) {
    if (r.level) counts[r.level] += 1;
  }
  return counts;
}

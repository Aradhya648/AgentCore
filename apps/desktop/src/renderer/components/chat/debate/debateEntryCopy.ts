import { confidenceLabel, confidencePill } from "@/components/ui/tone-presets";
import type { Execution } from "@/stores/execution";
import { tallyScores, toDebateModel } from "./model";

const FORM_LABEL: Record<string, string> = {
  debate: "正反",
  red_team: "红队审查",
  roundtable: "圆桌探讨",
};

const CONFIDENCE_LEVELS = ["high", "medium", "low"] as const;
type ConfidenceLevel = (typeof CONFIDENCE_LEVELS)[number];

function confidenceLevel(raw: string): ConfidenceLevel {
  const s = raw.toLowerCase();
  if (CONFIDENCE_LEVELS.includes(s as ConfidenceLevel)) {
    return s as ConfidenceLevel;
  }
  if (s.includes("high") || raw.includes("高")) return "high";
  if (s.includes("low") || raw.includes("低")) return "low";
  return "medium";
}

/** StatusStrip 辩论分支预告片文案（§3.4）。收场优先 brief 倾向·置信。 */
export function debatePreviewSubtitle(execution: Execution): string {
  const model = toDebateModel(execution);
  if (!model) return "辩论";

  const rounds = model.rounds.length;
  const formLabel = FORM_LABEL[model.form] ?? "辩论";

  if (!model.settled) {
    const liveNo =
      model.rounds.find((r) => r.inFlight)?.roundNo ?? (rounds || 1);
    return `辩论 · 第 ${liveNo} 轮进行中`;
  }

  const brief = model.brief;
  if (brief?.leaning?.trim()) {
    const level = confidenceLevel(brief.confidence ?? "medium");
    return `${brief.leaning.trim()} · 置信${confidenceLabel[level]}`;
  }

  if (model.form === "debate") {
    const tally = tallyScores(model.rounds);
    if (tally.length >= 2) {
      const sorted = [...tally].sort((a, b) => b.total - a.total);
      if (sorted[0].total !== sorted[1].total) {
        return `辩论完成 · 正反 ${rounds} 轮 · ${sorted[0].name}方略占优`;
      }
    }
    return `辩论完成 · 正反 ${rounds} 轮`;
  }

  return `辩论完成 · ${formLabel} ${rounds} 轮`;
}

/** 收场结论钩子：倾向 + 置信等级（供状态条次行 CTA；无 brief 返回 null）。 */
export function debateConclusionHook(execution: Execution): {
  leaning: string;
  confidenceLevel: ConfidenceLevel;
  confidenceLabel: string;
  confidenceClass: string;
} | null {
  const model = toDebateModel(execution);
  if (!model?.settled || !model.brief?.leaning?.trim()) return null;
  const level = confidenceLevel(model.brief.confidence ?? "medium");
  return {
    leaning: model.brief.leaning.trim(),
    confidenceLevel: level,
    confidenceLabel: confidenceLabel[level],
    confidenceClass: confidencePill[level],
  };
}

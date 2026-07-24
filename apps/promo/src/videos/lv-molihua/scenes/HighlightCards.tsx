/*
 * Simplified highlight cards for cold-open shots 3–4.
 * Full debate decision / score panels are out of hybrid scope — these present
 * the tape's key numbers with product tokens so they read on-brand.
 */

import { DECISION_BRIEF, FINAL_SCORES, MOTION } from "../data/coldOpen";

export function ScorePanelCard() {
  return (
    <div className="w-[560px] rounded-2xl border border-border bg-card p-8 text-card-foreground shadow-lg">
      <div className="mb-6 text-sm font-medium tracking-widest text-muted-foreground">
        末轮评分
      </div>
      <div className="space-y-4">
        <ScoreRow label="茉莉奶白" score={FINAL_SCORES.molihua} lead />
        <ScoreRow label="LV" score={FINAL_SCORES.lv} />
      </div>
      <div className="mt-8 flex items-center justify-between border-t border-border pt-5">
        <span className="text-base text-muted-foreground">判定</span>
        <span className="rounded-full bg-primary/15 px-4 py-1.5 text-base font-medium text-primary">
          {FINAL_SCORES.status}
        </span>
      </div>
      <div className="mt-4 text-center text-lg font-medium text-foreground">
        {FINAL_SCORES.headline}
      </div>
    </div>
  );
}

function ScoreRow({
  label,
  score,
  lead = false,
}: {
  label: string;
  score: number;
  lead?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-6">
      <span
        className={`text-2xl font-medium ${lead ? "text-foreground" : "text-muted-foreground"}`}
      >
        {label}
      </span>
      <span
        className={`tabular-nums text-5xl font-semibold ${lead ? "text-primary" : "text-foreground"}`}
      >
        {score}
      </span>
    </div>
  );
}

export function DecisionBriefCard() {
  return (
    <div className="w-[640px] rounded-2xl border border-border bg-card p-9 text-card-foreground shadow-lg">
      <div className="mb-5 text-sm font-medium tracking-widest text-muted-foreground">
        决策简报
      </div>
      <div className="text-3xl font-semibold leading-snug text-foreground">
        {DECISION_BRIEF.leaning}
      </div>
      <div className="mt-4 flex items-baseline gap-3">
        <span className="text-lg text-muted-foreground">
          {DECISION_BRIEF.confidenceLabel}
        </span>
        <span className="tabular-nums text-5xl font-semibold text-primary">
          {DECISION_BRIEF.confidence}
        </span>
      </div>
      <div className="mt-7 border-t border-border pt-5 text-base leading-relaxed text-muted-foreground">
        辩题 · {MOTION}
      </div>
    </div>
  );
}

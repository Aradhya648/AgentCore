import { ResolvedDecisionRecord } from "@/components/chat/decision";
import type { PlanReviewDisplay } from "@/stores/conversation";
import {
  Ban,
  Check,
  Clock,
  type LucideIcon,
  OctagonX,
  Pencil,
} from "lucide-react";
import { PendingDecisionMarker } from "./PendingDecisionMarker";

/**
 * Inline plan_review card — the WaveScheduler paused after a `checkpoint_after` step
 * completed and before its dependents run (结构化挂起). Rendered under the assistant
 * bubble that raised it (会话流内，alongside any ask_user checkpoints), replaying inline on
 * reload.
 *
 * 挂起即收口 (②, Phase 3): plan_review never parks live inline anymore — the scheduler
 * finalizes the turn at the boundary (`SUSPEND → PAUSED`), so the actionable surface is the
 * durable resume card (ResumePrompt). 方案 C（一个焦点 + 一个入口）: inline pending is a
 * single-line {@link PendingDecisionMarker} — full context lives on the 拍板中心
 * (ResumePrompt); a resolved one keeps a settled record folded to one line (继续 ran the
 * gated downstream / 调整 steered it / 停止 ended the run), matching team_preview.
 */
export function PlanReviewCard({ review }: { review: PlanReviewDisplay }) {
  if (review.status === "resolved") {
    return <ResolvedPlanReview review={review} />;
  }
  return <PendingDecisionMarker label="等你确认 · 计划复核 · 确认后才会继续" />;
}

/** The just-completed step(s) under review: each worker's role + a capped excerpt
 * of its product (the backend already truncates `summary`). */
function ReviewedSteps({ review }: { review: PlanReviewDisplay }) {
  return (
    <div className="mt-2 space-y-1.5">
      {review.steps.map((s) => (
        <div
          key={s.run_id}
          className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
        >
          <p className="text-xs font-medium text-foreground">{s.role}</p>
          {s.summary && (
            <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
              {s.summary}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

const RESOLVED_META: Record<
  NonNullable<PlanReviewDisplay["decision"]> | "timeout",
  { icon: LucideIcon; label: string }
> = {
  continue: { icon: Check, label: "已继续 · 放行下游" },
  per_call: { icon: Check, label: "已继续 · 放行下游" },
  adjust: {
    icon: Pencil,
    label: "已调整 · 指示已注入下游并继续",
  },
  stop: { icon: OctagonX, label: "已停止 · 未运行下游" },
  research_first: {
    icon: OctagonX,
    label: "已停止 · 未运行下游",
  },
  timeout: { icon: Clock, label: "未及时回应，已自动放行继续" },
  orphaned: {
    icon: Ban,
    label: "已失效（回合已结束或服务已重启）",
  },
};

function rolesSuffix(review: PlanReviewDisplay): string {
  const roles = review.steps.map((s) => s.role).filter(Boolean);
  return roles.length > 0
    ? roles.join(" · ")
    : `${review.steps.length} 步已完成`;
}

/** The settled record of a plan_review: whether the downstream was released. */
function ResolvedPlanReview({ review }: { review: PlanReviewDisplay }) {
  const meta = RESOLVED_META[review.decision ?? "timeout"];
  const summary = `${meta.label} · ${rolesSuffix(review)}`;

  return (
    <ResolvedDecisionRecord
      layout="neutralCollapsible"
      disclosureKey={`plan-review:${review.id}`}
      icon={meta.icon}
      summary={summary}
    >
      <ReviewedSteps review={review} />
      {review.note && (
        <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-foreground">
          {review.note}
        </p>
      )}
    </ResolvedDecisionRecord>
  );
}

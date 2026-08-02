import type { PlanReviewDisplay } from "@/stores/conversation";
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
 * (ResumePrompt). resolved 不再占时间线一行；放行/调整结论收进协作图对应 worker 节点 face 徽标。
 */
export function PlanReviewCard({ review }: { review: PlanReviewDisplay }) {
  if (review.status === "resolved") {
    return null;
  }
  return <PendingDecisionMarker label="等你确认 · 计划复核 · 确认后才会继续" />;
}

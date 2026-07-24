/** Decisions a user can actively make on a plan_review / kickoff card.
 * plan_review: `continue` / `adjust` / `stop`.
 * team_preview (开工卡): `continue` (= grant + start; note → steer) / `stop`;
 *   debate may offer `research_first`（先多视角调研再辩）when `offer_research_first`.
 *   `per_call` retained in the type for historical resolve payloads; UI no longer sends it.
 * `timeout` is engine-only and never sent by the client.
 *
 * Settlement is cold `POST .../resume` (services/turns.ts `runResume`). */
export type PlanReviewUserDecision =
  | "continue"
  | "per_call"
  | "adjust"
  | "stop"
  | "research_first";

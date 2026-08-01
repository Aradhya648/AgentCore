/**
 * Layout-only debate tag predicate (mirrors desktop `stores/execution/debate.ts`).
 * Duplicated here so this package never imports UI stores. Keep the group
 * whitelist in lockstep with the execution-store source of truth.
 */
const DEBATE_PARTICIPANT_GROUPS = new Set([
  "debate:debate",
  "debate:red_team",
  "debate:roundtable",
  "debate:witness",
]);

/** stance 非空或显式辩形态 / 证人席 group。 */
export function isDebateTaggedRun(r: {
  stance?: string | null;
  group?: string | null;
}): boolean {
  return (
    r.stance != null ||
    (r.group != null && DEBATE_PARTICIPANT_GROUPS.has(r.group))
  );
}

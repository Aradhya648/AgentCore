/**
 * Per-role visual identity for the team collaboration graph (前端UX设计.md §五 角色身份).
 *
 * Worker roles are free text the CEO assigns at plan time (研究员 / 工程师 / 设计师 …),
 * so identity is *derived deterministically from the role string* — same role ⇒ same
 * color + glyph across nodes, turns, and reloads, with no backend field. The color is
 * one of the 8 `--agent-N` OKLCH tokens (styles/globals.css); the glyph is the role's
 * first character, which for CJK role names reads as a natural avatar monogram (研/工/设).
 *
 * Identity is intentionally decoupled from run STATUS: the avatar disc carries identity,
 * the card ring + a small presence dot carry status (AgentNode), so a role's color never
 * competes with the 6-state status palette (color-tokens.mdc).
 */

/** Number of `--agent-N` identity tokens defined in globals.css (:root / .dark). */
const AGENT_PALETTE_SIZE = 8;

/**
 * Deterministic 32-bit string hash (FNV-1a). Stable across sessions/platforms so a
 * given role always maps to the same identity slot — never `Math.random` / insertion
 * order, which would reshuffle colors between turns or on reload.
 */
function hashRole(role: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < role.length; i++) {
    h ^= role.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** 1-based index of the role's `--agent-N` token. Empty/blank role falls back to slot 1. */
export function agentColorIndex(role: string): number {
  const key = role.trim();
  if (!key) return 1;
  return (hashRole(key) % AGENT_PALETTE_SIZE) + 1;
}

/** The role's identity color as a CSS `var(--agent-N)` reference (use inline, per
 * color-tokens.mdc — these are semantic OKLCH tokens, not ad-hoc colors). */
export function agentColorVar(role: string): string {
  return `var(--agent-${agentColorIndex(role)})`;
}

/**
 * The avatar monogram: the role's first character (surrogate-pair safe, so an emoji
 * role renders whole). Blank role → 「?」 placeholder rather than an empty disc.
 */
export function agentGlyph(role: string): string {
  const key = role.trim();
  if (!key) return "?";
  return Array.from(key)[0];
}

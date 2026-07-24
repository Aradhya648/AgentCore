/**
 * Structured graph id single source — construction + parsing for every synthetic
 * / namespaced id the collaboration graph uses. Kept React-free so the pure IR
 * layer ({@link buildGraphScene}), ELK helpers, and the layout modules can all
 * reference it without importing node components.
 *
 * Nothing downstream should hand-concatenate or `split("::")` these strings;
 * always go through the constructors / parsers here so the namespaces stay in
 * lockstep (historically the source of「幽灵列」/ mis-nested id bugs).
 */

/** Synthetic graph bookend id (the user-input endpoint node). */
export const INPUT_ID = "__input__";

export const isEndpointId = (id: string): boolean => id === INPUT_ID;

// ── Sub-team compound group id ──────────────────────────────────────────────
// A folded sub-team renders as a compound box whose id derives from its parent
// run. `buildGraphStructure` builds the boxes; the projection reads `groupId`.

const GROUP_PREFIX = "__group__";

/** Compound group id for a sub-team whose parent is `parentId`. */
export const subTeamGroupId = (parentId: string): string =>
  `${GROUP_PREFIX}${parentId}`;

// ── Folded-act summary card id (幕级 LOD, 批 R2) ─────────────────────────────
// A non-focused act renders as a single 幕摘要卡 node; its id round-trips to the
// act id so the click handler can focus that act.

const ACT_CARD_PREFIX = "__act__";

/** Synthetic node id for an act's folded 幕摘要卡. */
export const actCardId = (actId: string): string =>
  `${ACT_CARD_PREFIX}${actId}`;

/** Recover an act id from a card node id (null when not an act card). */
export const parseActCardId = (id: string): string | null =>
  id.startsWith(ACT_CARD_PREFIX) ? id.slice(ACT_CARD_PREFIX.length) : null;

/** Downgraded cross-act chain edge id (links neighbouring act blocks). */
export const actChainEdgeId = (index: number): string => `__actchain__${index}`;

// ── Canvas per-turn namespace ───────────────────────────────────────────────
// The conversation canvas nests every turn's DAG under a turn compound in one
// ReactFlow store, namespacing node/edge ids as `${turnId}::${bareId}`.

const TURN_SEP = "::";

/** Namespace a bare (turn-local) node/edge id under its turn. */
export const namespaceId = (turnId: string, bareId: string): string =>
  `${turnId}${TURN_SEP}${bareId}`;

/** Split a namespaced id into `{ turnId, bare }`, or null when not namespaced. */
export function parseNamespacedId(
  id: string,
): { turnId: string; bare: string } | null {
  const sep = id.indexOf(TURN_SEP);
  if (sep < 0) return null;
  return { turnId: id.slice(0, sep), bare: id.slice(sep + TURN_SEP.length) };
}

/** Bare id under a turn namespace (or the id unchanged when not namespaced). */
export const stripNamespace = (id: string): string =>
  parseNamespacedId(id)?.bare ?? id;

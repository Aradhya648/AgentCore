/**
 * Pure display-layer renumbering for web citation markers.
 *
 * Backend / SSE keep a turn-level pool with canonical 1-based indices (`[n]` in
 * the model body). The UI remaps those to contiguous display numbers by
 * first-appearance order in the reply, so chips / tooltips / SourceCards share
 * one numbering. Unreferenced pool entries trail the referenced ones.
 *
 * Streaming: pass the previous **cited-only** map (`stableCited`); new first
 * appearances only append — already-assigned display numbers never jump.
 * Unreferenced trailing numbers are recomputed each call and are not part of
 * the stable map (so a later first citation can still take the next slot).
 */

const MARKER = /\[(\d+)\]/g;
const LEDGER_MARKER = /#r(\d+)\b/g;

export interface CitationDisplayMap {
  /**
   * Canonical 1-based pool index → display number for every pool slot
   * (cited + trailing unreferenced). Use for chip / card labels.
   */
  toDisplay: Map<number, number>;
  /**
   * Cited-only canonical → display map. Pass this back as `previous` on the
   * next stream frame so numbering stays append-only.
   */
  stableCited: Map<number, number>;
  /**
   * SourceCards row order: referenced first (by display number), then
   * unreferenced in original pool order. `poolIndex` is 0-based.
   */
  rows: Array<{ poolIndex: number; display: number; cited: boolean }>;
  /** Display numbers that appear as inline markers in the body. */
  referencedDisplay: Set<number>;
}

/**
 * Build (or append to) the display map for a message body + citation pool size.
 *
 * @param content Reply body (or growing stream prefix).
 * @param citationCount Pool length; markers outside `1..count` are ignored.
 * @param previous Prior `stableCited` from an earlier stream frame (append-only).
 * @param citations Optional pool rows — when present, inline `#rN` markers that
 *   match ``citations[].id`` also count as cited (same first-appearance order).
 */
export function buildCitationDisplayMap(
  content: string,
  citationCount: number,
  previous?: ReadonlyMap<number, number> | null,
  citations?: ReadonlyArray<{ id?: string | null }> | null,
): CitationDisplayMap {
  const stableCited = new Map<number, number>(previous ?? undefined);

  if (citationCount > 0 && content) {
    MARKER.lastIndex = 0;
    let m: RegExpExecArray | null;
    // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic regex scan
    while ((m = MARKER.exec(content)) !== null) {
      const canonical = Number(m[1]);
      if (canonical < 1 || canonical > citationCount) continue;
      if (stableCited.has(canonical)) continue;
      stableCited.set(canonical, stableCited.size + 1);
    }
    if (citations?.length) {
      const idToCanonical = new Map<string, number>();
      for (let i = 0; i < citations.length; i++) {
        const id = citations[i]?.id;
        if (id) idToCanonical.set(id, i + 1);
      }
      LEDGER_MARKER.lastIndex = 0;
      // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic regex scan
      while ((m = LEDGER_MARKER.exec(content)) !== null) {
        const canonical = idToCanonical.get(`#r${m[1]}`);
        if (canonical == null || canonical < 1 || canonical > citationCount) {
          continue;
        }
        if (stableCited.has(canonical)) continue;
        stableCited.set(canonical, stableCited.size + 1);
      }
    }
  }

  const referencedDisplay = new Set(stableCited.values());

  const rows: CitationDisplayMap["rows"] = [];
  const citedOrdered = [...stableCited.entries()].sort((a, b) => a[1] - b[1]);
  for (const [canonical, display] of citedOrdered) {
    rows.push({ poolIndex: canonical - 1, display, cited: true });
  }

  const toDisplay = new Map(stableCited);
  let next = stableCited.size + 1;
  for (let i = 1; i <= citationCount; i++) {
    if (stableCited.has(i)) continue;
    toDisplay.set(i, next);
    rows.push({ poolIndex: i - 1, display: next, cited: false });
    next += 1;
  }

  return { toDisplay, stableCited, rows, referencedDisplay };
}

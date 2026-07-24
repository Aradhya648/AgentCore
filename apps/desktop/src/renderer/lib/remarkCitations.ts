/**
 * Remark plugin: turn inline citation markers `[n]` / `#rN` into custom `citemark`
 * elements so the Markdown renderer can map them to citation chips.
 *
 * Payload rides on `data.hProperties` (same pattern as {@link ./remarkEvidence}):
 * react-markdown's default `urlTransform` strips non-http(s) link schemes, so the
 * older `cite:n` encoding never reached the chip component.
 *
 * - `[n]` outside `1..max` stay literal text.
 * - `#rN` only rewritten when present in ``knownLedgerIds``; unknown ids stay text
 *   (不得炸；历史消息 / 闸剥离后残留均安全)。
 * Markers inside code / inline-code / existing links are left untouched.
 */

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
  data?: {
    hName?: string;
    hProperties?: Record<string, string>;
  };
}

// Subtrees whose text must stay verbatim (don't rewrite [n] / #rN inside code/links).
const SKIP_TYPES = new Set([
  "code",
  "inlineCode",
  "link",
  "linkReference",
  "definition",
]);

const POOL_MARKER = /\[(\d+)\]/g;
const LEDGER_MARKER = /#r(\d+)\b/g;

/** One `citemark` element carrying the canonical 1-based pool index. */
function citeNode(n: number): MdNode {
  return {
    type: "cite",
    data: {
      hName: "citemark",
      hProperties: { dataN: String(n) },
    },
    children: [{ type: "text", value: String(n) }],
  };
}

/** One `citemark` element carrying a turn-ledger id (`#rN`). */
function ledgerCiteNode(id: string): MdNode {
  return {
    type: "cite",
    data: {
      hName: "citemark",
      hProperties: { dataLedgerId: id },
    },
    children: [{ type: "text", value: id }],
  };
}

type MarkerHit =
  | { kind: "pool"; index: number; start: number; end: number; n: number }
  | { kind: "ledger"; index: number; start: number; end: number; id: string };

/** Split a text value into text + `citemark` nodes for in-range / known markers. */
export function splitCitationText(
  value: string,
  max: number,
  knownLedgerIds?: ReadonlySet<string> | null,
): MdNode[] {
  const hits: MarkerHit[] = [];
  POOL_MARKER.lastIndex = 0;
  let m: RegExpExecArray | null;
  // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic regex scan
  while ((m = POOL_MARKER.exec(value)) !== null) {
    const n = Number(m[1]);
    if (n < 1 || n > max) continue;
    hits.push({
      kind: "pool",
      index: m.index,
      start: m.index,
      end: m.index + m[0].length,
      n,
    });
  }
  if (knownLedgerIds && knownLedgerIds.size > 0) {
    LEDGER_MARKER.lastIndex = 0;
    // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic regex scan
    while ((m = LEDGER_MARKER.exec(value)) !== null) {
      const id = `#r${m[1]}`;
      if (!knownLedgerIds.has(id)) continue;
      hits.push({
        kind: "ledger",
        index: m.index,
        start: m.index,
        end: m.index + m[0].length,
        id,
      });
    }
  }
  if (hits.length === 0) return [{ type: "text", value }];
  hits.sort((a, b) => a.start - b.start || a.end - b.end);

  const parts: MdNode[] = [];
  let last = 0;
  for (const hit of hits) {
    // Skip overlaps (prefer earlier hit).
    if (hit.start < last) continue;
    if (hit.start > last) {
      parts.push({ type: "text", value: value.slice(last, hit.start) });
    }
    parts.push(hit.kind === "pool" ? citeNode(hit.n) : ledgerCiteNode(hit.id));
    last = hit.end;
  }
  if (last < value.length) {
    parts.push({ type: "text", value: value.slice(last) });
  }
  return parts.length ? parts : [{ type: "text", value }];
}

function walk(
  node: MdNode,
  max: number,
  knownLedgerIds?: ReadonlySet<string> | null,
): void {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (
      child.type === "text" &&
      child.value &&
      (child.value.includes("[") || child.value.includes("#r"))
    ) {
      next.push(...splitCitationText(child.value, max, knownLedgerIds));
    } else {
      if (child.children && !SKIP_TYPES.has(child.type)) {
        walk(child, max, knownLedgerIds);
      }
      next.push(child);
    }
  }
  node.children = next;
}

/** remark attacher factory; pass the source count as `max` and optional known `#rN` ids. */
export function remarkCitations(
  max: number,
  knownLedgerIds?: ReadonlySet<string> | null,
) {
  return function attacher() {
    return (tree: MdNode) => {
      if (max > 0 || (knownLedgerIds && knownLedgerIds.size > 0)) {
        walk(tree, max, knownLedgerIds);
      }
    };
  };
}

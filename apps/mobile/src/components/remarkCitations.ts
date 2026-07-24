// Remark plugin: turn inline citation markers `[n]` / `#rN` into custom `citemark`
// elements so the Markdown renderer can map them to citation chips.
//
// Mirror of the desktop lib/remarkCitations.ts — a dependency-free pure leaf (cross-
// platform-frontend.mdc allows mirroring such leaves; mobile keeps its own to stay
// decoupled). Payload rides on `data.hProperties` (not `cite:n` links — react-markdown
// urlTransform strips non-http schemes). Markers inside code / links stay verbatim.

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

const SKIP_TYPES = new Set([
  "code",
  "inlineCode",
  "link",
  "linkReference",
  "definition",
]);

const POOL_MARKER = /\[(\d+)\]/g;
const LEDGER_MARKER = /#r(\d+)\b/g;

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
  | { kind: "pool"; start: number; end: number; n: number }
  | { kind: "ledger"; start: number; end: number; id: string };

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

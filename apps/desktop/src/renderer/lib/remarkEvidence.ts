/**
 * Remark plugin: turn inline evidence-status markers a debater writes —
 * `【已核实·<出处>】` (verified, with a source) / `【待核实·推断】` (unverified /
 * inferred) — into a custom `evidencemark` element the Markdown renderer maps to
 * an {@link import("@/components/chat/EvidenceBadge").EvidenceBadge} chip, so the
 * 举证责任 pillar (辩论编排设计.md §4-2.3 契约② P3, 方案 A) is glanceable:
 * grounded vs merely-asserted claims read at a glance instead of hiding in prose.
 *
 * Backend twin: the debater system prompt (`prompt.py:EVIDENCE_RULE`) tells every
 * debater to tag factual claims with exactly these two markers, and the judge
 * scores `evidence` / penalizes unverified-passed-as-fact off the same markers —
 * so 辩手标 → 裁判据标记记分 → 前端渲成徽章 read one convention end to end.
 *
 * Unlike {@link import("./remarkCitations").remarkCitations} (which also carries
 * its payload on `data.hProperties` as a custom `citemark` element), this keeps
 * evidence markers off the link/`urlTransform` path so react-markdown never strips
 * them. Markers inside code / inline-code / links are left verbatim. No external
 * mdast/unist dependency — a small hand-rolled tree walk, mirroring remarkCitations.
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

// Subtrees whose text must stay verbatim (don't rewrite markers inside code/links).
const SKIP_TYPES = new Set([
  "code",
  "inlineCode",
  "link",
  "linkReference",
  "definition",
]);

// 【已核实·出处】 / 【待核实·推断】 / bare 【已核实】 / 【待核实】. The optional
// ·<note> runs up to the closing bracket (never contains 】), so a source/label with
// its own middots is captured whole.
const MARKER = /【(已核实|待核实)(?:·([^】]*))?】/g;

/** One `evidencemark` element node carrying kind (+ optional source/note as text child). */
function evidenceNode(kind: "verified" | "unverified", note: string): MdNode {
  return {
    type: "evidence",
    data: {
      hName: "evidencemark",
      hProperties: { dataKind: kind },
    },
    children: note ? [{ type: "text", value: note }] : [],
  };
}

/** Split a text value into text + `evidencemark` nodes for each evidence marker. */
export function splitEvidenceText(value: string): MdNode[] {
  const parts: MdNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  MARKER.lastIndex = 0;
  // biome-ignore lint/suspicious/noAssignInExpressions: idiomatic regex scan
  while ((m = MARKER.exec(value)) !== null) {
    if (m.index > last) {
      parts.push({ type: "text", value: value.slice(last, m.index) });
    }
    const kind = m[1] === "已核实" ? "verified" : "unverified";
    parts.push(evidenceNode(kind, (m[2] ?? "").trim()));
    last = m.index + m[0].length;
  }
  if (parts.length === 0) return [{ type: "text", value }];
  if (last < value.length) {
    parts.push({ type: "text", value: value.slice(last) });
  }
  return parts;
}

function walk(node: MdNode): void {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value?.includes("【")) {
      next.push(...splitEvidenceText(child.value));
    } else {
      if (child.children && !SKIP_TYPES.has(child.type)) walk(child);
      next.push(child);
    }
  }
  node.children = next;
}

/** remark attacher — enable via the Markdown `evidence` prop (debate speech only). */
export function remarkEvidence() {
  return function attacher() {
    return (tree: MdNode) => {
      walk(tree);
    };
  };
}

/**
 * Best-effort repairs for common Mermaid syntax that models emit but parsers reject.
 * Applied before mermaid.parse() — parse failure still falls back to source display.
 */

const ARROW_RE =
  /(-->|---|==>|-\.->|--o|--x|o--o|o--x|x--o|x--x|<-->|<-->|o---o)(?:\|[^|]*\|)?/;

/**
 * Full-width / CJK punctuation → ASCII equivalents that Mermaid's parser needs
 * in structural positions (sequence message separators, edge-label pipes, etc.).
 * Full-width parens are intentionally excluded: unquoted labels like `A[步骤（1）]`
 * render fine as literal text, whereas rewriting them to ASCII `(` would trigger
 * node-shape syntax and BREAK an otherwise-valid diagram.
 */
const FULLWIDTH_PUNCT: Record<string, string> = {
  "\uFF1A": ":", // ：
  "\uFF1B": ";", // ；
  "\uFF0C": ",", // ，
  "\uFF5C": "|", // ｜
  "\u3000": " ", // full-width space
};

/**
 * Repair "typographic" Unicode punctuation that models emit where Mermaid only
 * accepts ASCII. Curly/smart quotes are converted unconditionally because models
 * use them as the ASCII label delimiter. Other full-width punctuation is fixed
 * ONLY outside ASCII-quoted strings, so real label display text such as
 * `A["用户：管理员"]` keeps its characters while a structural separator like the
 * sequence message `用户->>前端：点击按钮` gets repaired.
 */
function normalizePunctuation(line: string): string {
  const dequoted = line
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u2018\u2019]/g, "'");

  let out = "";
  let inQuote = false;
  let quoteChar = "";

  for (const ch of dequoted) {
    if ((ch === '"' || ch === "'") && !inQuote) {
      inQuote = true;
      quoteChar = ch;
      out += ch;
    } else if (ch === quoteChar && inQuote) {
      inQuote = false;
      quoteChar = "";
      out += ch;
    } else if (
      !inQuote &&
      Object.prototype.hasOwnProperty.call(FULLWIDTH_PUNCT, ch)
    ) {
      out += FULLWIDTH_PUNCT[ch];
    } else {
      out += ch;
    }
  }

  return out;
}

/** Split on `&` outside of quoted strings. */
function splitByAmpersand(segment: string): string[] {
  const parts: string[] = [];
  let current = "";
  let inQuote = false;
  let quoteChar = "";

  for (const ch of segment) {
    if ((ch === '"' || ch === "'") && !inQuote) {
      inQuote = true;
      quoteChar = ch;
      current += ch;
    } else if (ch === quoteChar && inQuote) {
      inQuote = false;
      quoteChar = "";
      current += ch;
    } else if (ch === "&" && !inQuote) {
      const trimmed = current.trim();
      if (trimmed) parts.push(trimmed);
      current = "";
    } else {
      current += ch;
    }
  }

  const trimmed = current.trim();
  if (trimmed) parts.push(trimmed);
  return parts;
}

function fixSubgraphLine(line: string, sgCounter: { n: number }): string {
  const match = line.match(/^(\s*subgraph\s+)(.+?)(\s*)$/i);
  if (!match) return line;

  const [, prefix, label, suffix] = match;
  const trimmed = label.trim();

  // Already quoted or bracket-labelled — leave alone.
  // Unicode letters/digits allowed in the id (e.g. subgraph 图["一次 delegate"]).
  // Bare Unicode labels (no bracket/quote) must NOT early-return here — they still
  // need wrapping below. Keep the bare-id check ASCII-only for that reason.
  if (/^[\p{L}_][\p{L}\p{N}_]*\s*[\["']/u.test(trimmed)) return line;
  if (/^["']/.test(trimmed)) return line;
  // Bare ASCII id is valid Mermaid.
  if (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(trimmed)) return line;

  const id = `sg_${sgCounter.n++}`;
  const escaped = trimmed.replace(/"/g, '\\"');
  return `${prefix}${id}["${escaped}"]${suffix}`;
}

function expandAmpersandEdges(line: string): string | string[] {
  if (!line.includes("&")) return line;

  const arrowMatch = line.match(ARROW_RE);
  if (!arrowMatch || arrowMatch.index === undefined) return line;

  const arrowIdx = arrowMatch.index;
  const arrow = arrowMatch[0];
  const left = line.slice(0, arrowIdx).trim();
  const right = line.slice(arrowIdx + arrow.length).trim();

  const sources = splitByAmpersand(left);
  const targets = splitByAmpersand(right);
  if (sources.length <= 1 && targets.length <= 1) return line;

  const indent = line.match(/^(\s*)/)?.[1] ?? "";
  const edges: string[] = [];
  for (const src of sources) {
    for (const tgt of targets) {
      edges.push(`${indent}${src} ${arrow} ${tgt}`);
    }
  }
  return edges;
}

export function normalizeMermaidSource(code: string): string {
  const sgCounter = { n: 0 };
  const out: string[] = [];

  for (const line of code.split("\n")) {
    if (line.trimStart().startsWith("%%")) {
      out.push(line);
      continue;
    }

    const normalized = normalizePunctuation(line);
    const fixedSubgraph = fixSubgraphLine(normalized, sgCounter);
    const expanded = expandAmpersandEdges(fixedSubgraph);
    if (Array.isArray(expanded)) {
      out.push(...expanded);
    } else {
      out.push(expanded);
    }
  }

  return out.join("\n");
}

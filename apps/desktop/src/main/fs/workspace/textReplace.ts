/**
 * Newline-tolerant text replace — mirrors
 * `agentcore/workspace/text_replace.py` (exact first, then LF-normalized
 * fallback; restore CRLF when the original file contained `\r\n`).
 */

export type TextReplaceResult =
  | { ok: true; content: string; count: number; firstLine: number | null }
  | { ok: false; kind: "NoMatch" }
  | { ok: false; kind: "AmbiguousMatch"; count: number };

function toLf(s: string): string {
  return s.replaceAll("\r\n", "\n");
}

/** Non-overlapping occurrence count — aligns with Python ``str.count``. */
function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) return haystack.length + 1;
  return haystack.split(needle).length - 1;
}

function tryReplace(
  content: string,
  oldStr: string,
  newStr: string,
  all: boolean,
): TextReplaceResult {
  const count = countOccurrences(content, oldStr);
  if (count === 0) return { ok: false, kind: "NoMatch" };
  if (count > 1 && !all) {
    return { ok: false, kind: "AmbiguousMatch", count };
  }

  if (all) {
    return {
      ok: true,
      content: content.split(oldStr).join(newStr),
      count,
      firstLine: null,
    };
  }

  const idx = content.indexOf(oldStr);
  const newContent =
    content.slice(0, idx) + newStr + content.slice(idx + oldStr.length);
  const firstLine = content.slice(0, idx).split("\n").length;
  return { ok: true, content: newContent, count: 1, firstLine };
}

export function applyTextReplace(
  content: string,
  oldStr: string,
  newStr: string,
  all: boolean,
): TextReplaceResult {
  const exact = tryReplace(content, oldStr, newStr, all);
  if (exact.ok || exact.kind === "AmbiguousMatch") return exact;

  const eolCrlf = content.includes("\r\n");
  const normContent = toLf(content);
  const normOld = toLf(oldStr);
  const normNew = toLf(newStr);
  if (normContent === content && normOld === oldStr && normNew === newStr) {
    return { ok: false, kind: "NoMatch" };
  }

  const fallback = tryReplace(normContent, normOld, normNew, all);
  if (fallback.ok && eolCrlf) {
    return {
      ok: true,
      content: fallback.content.replaceAll("\n", "\r\n"),
      count: fallback.count,
      firstLine: fallback.firstLine,
    };
  }
  return fallback;
}

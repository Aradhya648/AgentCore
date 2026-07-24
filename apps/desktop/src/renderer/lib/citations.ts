/**
 * Helpers for presenting web sources (citations) in the chat UI.
 *
 * Kept separate from {@link ./remarkCitations} (the remark plugin that rewrites
 * inline `[n]` markers): these are pure display/derivation utilities reused by
 * the source cards and hover previews, with no mdast dependency.
 */

// A trailing "标题 - 某某网" suffix. Deliberately conservative to avoid eating
// real title text: a Western dash/pipe must be space-padded (so "2024-2025"
// survives), a CJK "_｜·" may be unspaced (the 百度百科 pattern), and the site
// segment is short and digit-free (a brand name, not a date or section number).
const TITLE_SUFFIX = /(?:\s[-|–—]\s|\s*[_｜·]\s*)[^-|_–—｜·\d]{2,20}$/;

/**
 * Strip a trailing site-name suffix from a source title so a card shows the page
 * title, not "标题 - 某某网". Removes only one matching tail and only when the
 * remainder is still substantial (≥2 chars); otherwise the original is returned.
 */
export function cleanSourceTitle(title?: string): string {
  const t = (title ?? "").trim();
  if (t.length < 8) return t;
  const stripped = t.replace(TITLE_SUFFIX, "").trim();
  return stripped.length >= 2 ? stripped : t;
}

/**
 * The set of 1-based source numbers actually cited as `[n]` in the reply body,
 * letting the source list distinguish "cited in the answer" from "only
 * retrieved". A lightweight string scan: an `[n]` inside a code block counts as
 * cited, which at worst shows a retrieved-only source at full strength — a
 * harmless over-count, never a wrong number.
 */
export function referencedCitationNumbers(
  content: string,
  max: number,
): Set<number> {
  const out = new Set<number>();
  if (max <= 0 || !content) return out;
  const re = /\[(\d+)\]/g;
  let m: RegExpExecArray | null = re.exec(content);
  while (m !== null) {
    const n = Number(m[1]);
    if (n >= 1 && n <= max) out.add(n);
    m = re.exec(content);
  }
  return out;
}

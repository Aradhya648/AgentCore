import { labelForPromptTag } from "@/lib/promptTagLabels";

/** One logical section of a system prompt or skill body. */
export interface PromptSection {
  /** XML tag name when present; null for preamble / untagged text. */
  tag: string | null;
  /** Display title (Chinese label for known tags). */
  title: string;
  body: string;
}

const SECTION_RE =
  /<([a-zA-Z_\u4e00-\u9fff][a-zA-Z0-9_\u4e00-\u9fff]*)>([\s\S]*?)<\/\1>/g;

/**
 * Split prompt text into tagged sections (`<tag>…</tag>`) plus optional preamble.
 * When no tags are found, returns a single section with the full text so callers
 * can still render it as Markdown.
 */
export function parsePromptDocument(text: string): PromptSection[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  const sections: PromptSection[] = [];
  let lastIndex = 0;

  for (const match of trimmed.matchAll(SECTION_RE)) {
    const index = match.index ?? 0;
    const preamble = trimmed.slice(lastIndex, index).trim();
    if (preamble) {
      sections.push({
        tag: null,
        title: sections.length === 0 ? "概述" : "",
        body: preamble,
      });
    }

    const tag = match[1];
    sections.push({
      tag,
      title: labelForPromptTag(tag),
      body: match[2].trim(),
    });

    lastIndex = index + match[0].length;
  }

  const tail = trimmed.slice(lastIndex).trim();
  if (tail) {
    sections.push({
      tag: null,
      title: sections.length === 0 ? "" : "",
      body: tail,
    });
  }

  if (sections.length === 0) {
    return [{ tag: null, title: "", body: trimmed }];
  }

  return sections;
}

/** True when the parser found at least one tagged section (structured view adds value). */
export function hasTaggedSections(sections: PromptSection[]): boolean {
  return sections.some((s) => s.tag !== null);
}

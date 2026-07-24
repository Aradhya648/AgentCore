import type { LucideIcon } from "lucide-react";
import { CONTENT_CHAPTERS } from "./content";
import { richTextToPlain } from "./richText";
import type { FaqAnswerPart, ManualBlock, ManualChapterContent } from "./types";

export interface SearchEntry {
  id: string;
  itemId: string;
  label: string;
  group: string;
  /** lucide 名称（内容源）；未迁移章可只提供 Icon */
  icon?: string;
  Icon?: LucideIcon;
  to: string;
  /** 全文检索语料：标题 + 正文 + FAQ 问句（小写） */
  haystack: string;
  /** 原始大小写正文，供命中摘要；未迁移章可省略（仅标题） */
  body?: string;
}

/** 从内容源抽取可搜索纯文本。 */
export function extractBlockText(block: ManualBlock): string {
  switch (block.type) {
    case "lead":
    case "paragraph":
    case "callout":
      return richTextToPlain(block.text);
    case "cards":
      return block.items.map((i) => `${i.title} ${i.desc}`).join(" ");
    case "bullets":
      return block.items.map((i) => `${i.title} ${i.desc}`).join(" ");
    case "steps":
      return block.items
        .map((i) => `${i.title} ${richTextToPlain(i.desc)}`)
        .join(" ");
    case "doDont":
      return [
        ...(block.good.label ? [block.good.label] : []),
        ...block.good.items,
        ...(block.bad.label ? [block.bad.label] : []),
        ...block.bad.items,
      ].join(" ");
    case "faq":
      return block.items.map((f) => `${f.q} ${faqAnswerPlain(f.a)}`).join(" ");
    case "boundaryTable":
      return block.rows.map((r) => `${r.can} ${r.approve} ${r.wont}`).join(" ");
    case "settingsRows":
      return block.rows.map((r) => `${r.label} ${r.desc}`).join(" ");
    case "embed":
      return "";
    default: {
      const _exhaustive: never = block;
      return _exhaustive;
    }
  }
}

function faqAnswerPlain(parts: FaqAnswerPart[]): string {
  return parts
    .map((p) => {
      if (p.type === "text") return richTextToPlain(p.text);
      return p.rows.map((r) => `${r.can} ${r.approve} ${r.wont}`).join(" ");
    })
    .join(" ");
}

/** 围绕查询词截取上下文摘要（命中显示用）。 */
export function matchSnippet(body: string, query: string, maxLen = 72): string {
  const q = query.trim();
  if (!q) return body.slice(0, maxLen);
  const lower = body.toLowerCase();
  const idx = lower.indexOf(q.toLowerCase());
  if (idx < 0) {
    const head = body.slice(0, maxLen).trim();
    return body.length > maxLen ? `${head}…` : head;
  }
  const pad = Math.floor((maxLen - q.length) / 2);
  const start = Math.max(0, idx - pad);
  const end = Math.min(body.length, start + maxLen);
  const slice = body.slice(start, end).trim();
  const prefix = start > 0 ? "…" : "";
  const suffix = end < body.length ? "…" : "";
  return `${prefix}${slice}${suffix}`;
}

export function buildChapterSearchEntries(
  chapter: ManualChapterContent,
): SearchEntry[] {
  return chapter.sections.map((section) => {
    const bodyText = section.blocks.map(extractBlockText).join(" ");
    const faqQs = section.blocks
      .filter(
        (b): b is Extract<ManualBlock, { type: "faq" }> => b.type === "faq",
      )
      .flatMap((b) => b.items.map((i) => i.q));
    const body = [section.title, bodyText, ...faqQs].join(" ");
    const haystack = body.toLowerCase();
    return {
      id: `${chapter.id}-${section.id}`,
      itemId: section.id,
      label: section.title,
      group: chapter.label,
      icon: section.icon,
      to: `${chapter.path}?s=${section.id}`,
      haystack,
      body,
    };
  });
}

/** 已迁移章：全文索引；未迁移章：仅标题（由调用方传入 title-only entries）。 */
export function buildContentSearchEntries(): SearchEntry[] {
  return CONTENT_CHAPTERS.flatMap(buildChapterSearchEntries);
}

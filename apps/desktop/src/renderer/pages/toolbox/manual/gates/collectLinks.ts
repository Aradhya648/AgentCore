/**
 * 从内容源抽取行内 go/jump 与 settingsRows.to，供路由/锚点校验。
 */

import { CONTENT_CHAPTERS } from "../content";
import type {
  FaqAnswerPart,
  InlineSpan,
  ManualBlock,
  ManualChapterContent,
  RichText,
} from "../types";

export type LinkKind = "go" | "jump" | "settings";

export interface CollectedLink {
  kind: LinkKind;
  to: string;
  /** 所在章 id */
  chapterId: string;
  /** 所在节 id */
  sectionId: string;
  where: string;
}

function walkRichText(
  text: RichText,
  chapter: ManualChapterContent,
  sectionId: string,
  where: string,
  out: CollectedLink[],
): void {
  if (typeof text === "string") return;
  text.forEach((span: InlineSpan, i) => {
    if (typeof span === "string" || !("link" in span) || !span.link) return;
    out.push({
      kind: span.link.kind,
      to: span.link.to,
      chapterId: chapter.id,
      sectionId,
      where: `${where}/span[${i}]「${span.text}」`,
    });
  });
}

function walkFaqParts(
  parts: FaqAnswerPart[],
  chapter: ManualChapterContent,
  sectionId: string,
  where: string,
  out: CollectedLink[],
): void {
  parts.forEach((part, i) => {
    if (part.type === "text") {
      walkRichText(
        part.text,
        chapter,
        sectionId,
        `${where}/faqPart[${i}]`,
        out,
      );
    }
  });
}

function walkBlock(
  block: ManualBlock,
  chapter: ManualChapterContent,
  sectionId: string,
  where: string,
  out: CollectedLink[],
): void {
  switch (block.type) {
    case "lead":
    case "paragraph":
    case "callout":
      walkRichText(block.text, chapter, sectionId, where, out);
      break;
    case "bullets":
      block.items.forEach((item, i) =>
        walkRichText(
          item.desc,
          chapter,
          sectionId,
          `${where}/bullet[${i}]`,
          out,
        ),
      );
      break;
    case "steps":
      block.items.forEach((item, i) =>
        walkRichText(item.desc, chapter, sectionId, `${where}/step[${i}]`, out),
      );
      break;
    case "faq":
      block.items.forEach((item, i) =>
        walkFaqParts(item.a, chapter, sectionId, `${where}/faq[${i}]`, out),
      );
      break;
    case "settingsRows":
      block.rows.forEach((row, i) => {
        out.push({
          kind: "settings",
          to: row.to,
          chapterId: chapter.id,
          sectionId,
          where: `${where}/settings[${i}]「${row.label}」`,
        });
      });
      break;
    default:
      break;
  }
}

export function collectContentLinks(): CollectedLink[] {
  const out: CollectedLink[] = [];
  for (const chapter of CONTENT_CHAPTERS) {
    for (const section of chapter.sections) {
      section.blocks.forEach((block, bi) =>
        walkBlock(
          block,
          chapter,
          section.id,
          `${chapter.id}/${section.id}/block[${bi}:${block.type}]`,
          out,
        ),
      );
    }
  }
  return out;
}

/** 章 id → section id 集合（由内容源派生）。 */
export function chapterSectionIds(): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const chapter of CONTENT_CHAPTERS) {
    map.set(chapter.id, new Set(chapter.sections.map((s) => s.id)));
  }
  return map;
}

/** path → 章 id（由内容源 path 派生）。 */
export function pathToChapterId(): Map<string, string> {
  const map = new Map<string, string>();
  for (const chapter of CONTENT_CHAPTERS) {
    map.set(chapter.path, chapter.id);
  }
  return map;
}

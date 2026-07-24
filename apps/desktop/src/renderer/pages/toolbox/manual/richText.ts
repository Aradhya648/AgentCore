import type { InlineSpan, RichText } from "./types";

/** 抽取纯文本，供搜索索引（无 React 依赖）。 */
export function richTextToPlain(text: RichText): string {
  if (typeof text === "string") return text;
  return text
    .map((span) => (typeof span === "string" ? span : span.text))
    .join("");
}

export function spanToPlain(span: InlineSpan): string {
  return typeof span === "string" ? span : span.text;
}

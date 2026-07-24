import type { ReactNode } from "react";
import { GoLink, JumpLink } from "./primitives";
import type { InlineSpan, RichText } from "./types";

export { richTextToPlain } from "./richText";

/** 把可序列化 RichText 渲成 React 节点。 */
export function renderRichText(text: RichText): ReactNode {
  if (typeof text === "string") return text;
  return text.map((span, i) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: 静态内容片段，无重排
    <span key={i}>{renderSpan(span)}</span>
  ));
}

function renderSpan(span: InlineSpan): ReactNode {
  if (typeof span === "string") return span;
  if ("link" in span && span.link) {
    if (span.link.kind === "jump") {
      return <JumpLink to={span.link.to}>{span.text}</JumpLink>;
    }
    return <GoLink to={span.link.to}>{span.text}</GoLink>;
  }
  if ("strong" in span && span.strong) {
    return <span className="font-medium">{span.text}</span>;
  }
  return span.text;
}

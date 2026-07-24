/**
 * Lightweight Markdown for admin conversation replay.
 * react-markdown + remark-gfm only — no katex / mermaid / highlight / citations.
 */
import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  a({ href, children, ...props }) {
    return (
      <a href={href} target="_blank" rel="noreferrer" {...props}>
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    // SECURITY (PI-001): never auto-load model-emitted images — downgrade to a link.
    const href = typeof src === "string" ? src : undefined;
    const label =
      typeof alt === "string" && alt.trim() ? alt.trim() : "图片链接";
    if (!href) return <>{label}</>;
    return (
      <a href={href} target="_blank" rel="noreferrer">
        {label}
      </a>
    );
  },
};

export const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
});

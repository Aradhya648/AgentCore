import { Markdown } from "@/components/chat/Markdown";
import {
  hasTaggedSections,
  parsePromptDocument,
} from "@/lib/parsePromptDocument";
import { cn } from "@/lib/utils";
import { useMemo } from "react";

/** Structured prompt / skill body: tagged sections rendered as Markdown.
 * Shared by 工具箱能力图鉴, 收到的上下文, and consult_skill result cards. */
export function PromptDocument({
  text,
  className,
  maxHeightClass = "max-h-[32rem]",
}: {
  text: string;
  className?: string;
  /** Tailwind max-height utility for the scroll container. */
  maxHeightClass?: string;
}) {
  const sections = useMemo(() => parsePromptDocument(text), [text]);
  const structured = hasTaggedSections(sections);

  if (!text.trim()) return null;

  return (
    <div className={cn("space-y-2", className)}>
      {structured ? (
        <div
          className={cn(
            "space-y-3 overflow-auto rounded-lg bg-muted/50 px-3 py-2",
            maxHeightClass,
          )}
        >
          {sections.map((section, i) => (
            <section
              key={`${section.tag ?? "preamble"}-${i}`}
              className="space-y-1"
            >
              {section.title ? (
                <h3 className="font-medium text-foreground text-xs">
                  {section.title}
                </h3>
              ) : null}
              <div className="markdown-body markdown-body--compact text-foreground/90">
                <Markdown content={section.body} muted />
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div
          className={cn(
            "overflow-auto rounded-lg bg-muted/50 px-3 py-2 markdown-body markdown-body--compact text-foreground/90",
            maxHeightClass,
          )}
        >
          <Markdown content={text} muted />
        </div>
      )}
    </div>
  );
}

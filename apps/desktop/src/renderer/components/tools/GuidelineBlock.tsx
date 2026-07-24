import { PromptDocument } from "@/components/prompt/PromptDocument";
import { Button } from "@/components/ui";
import { ChevronRight, ScrollText } from "lucide-react";
import { useState } from "react";

/** A collapsible prompt block (AI 工作准则). Collapsed by default — these are
 * long, and the page reads as a clean summary until the user opts in. Expanded
 * body uses {@link PromptDocument} (structured sections rendered as Markdown). */
export function GuidelineBlock({
  title,
  subtitle,
  text,
}: {
  title: string;
  subtitle: string;
  text: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-border bg-card">
      <Button
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="h-auto w-full justify-start gap-2 px-4 py-3 text-left font-normal"
      >
        <ScrollText size={16} className="shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <span className="block font-medium text-foreground text-sm">
            {title}
          </span>
          <span className="block text-muted-foreground text-xs">
            {subtitle}
          </span>
        </div>
        <ChevronRight
          size={14}
          className={`shrink-0 text-muted-foreground transition-transform ${
            open ? "rotate-90" : ""
          }`}
        />
      </Button>
      {open && <PromptDocument text={text} className="mx-4 mb-4" />}
    </div>
  );
}

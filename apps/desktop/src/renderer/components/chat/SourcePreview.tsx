import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cleanSourceTitle } from "@/lib/citations";
import type { Citation } from "@/types/events";
import type { ComponentProps, ReactNode } from "react";
import { Favicon } from "./Favicon";

/**
 * Rich hover preview for a single web source — favicon + domain (+ index) header,
 * the page title, and the search snippet when available. Shared by the source
 * cards under a reply and the inline `[n]` citation chips so both reveal the same
 * detail on hover (Perplexity / ChatGPT pattern), instead of a bare URL tooltip.
 */
export function SourcePreview({
  citation,
  index,
}: {
  citation: Citation;
  /** 1-based source number, shown when the preview backs an inline `[n]` chip. */
  index?: number;
}) {
  const { title, site, snippet, url } = citation;
  const displayTitle = cleanSourceTitle(title);
  return (
    <div className="w-72 max-w-[80vw]">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Favicon site={site} title={title} size={16} />
        <span className="min-w-0 flex-1 truncate">{site || url}</span>
        {index != null && (
          <span className="shrink-0 tabular-nums">来源 {index}</span>
        )}
      </div>
      <div className="mt-1.5 line-clamp-2 text-sm font-medium text-foreground">
        {displayTitle || url}
      </div>
      {snippet && (
        <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
          {snippet}
        </p>
      )}
    </div>
  );
}

/** Wraps a trigger so hovering/focusing it shows the {@link SourcePreview}. */
export function SourceTooltip({
  citation,
  index,
  side,
  children,
}: {
  citation: Citation;
  index?: number;
  side?: ComponentProps<typeof TooltipContent>["side"];
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className="max-w-none p-3">
        <SourcePreview citation={citation} index={index} />
      </TooltipContent>
    </Tooltip>
  );
}

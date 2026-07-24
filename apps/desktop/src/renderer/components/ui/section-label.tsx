import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

/** Group heading — toolbox sections, settings groups (text-xs muted). */
export function SectionLabel({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("text-xs font-medium text-muted-foreground", className)}
      {...props}
    />
  );
}

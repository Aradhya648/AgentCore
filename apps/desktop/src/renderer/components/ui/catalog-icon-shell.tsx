import { typeIconShellStyle } from "@/lib/catalogColors";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

export interface CatalogIconShellProps {
  colorVar: string;
  /** Softer fill for coming-soon / disabled tiles. */
  muted?: boolean;
  size?: "md" | "lg";
  className?: string;
  children: ReactNode;
}

/** Type-identity icon plate (artifact / catalog hues from design-tokens). */
export function CatalogIconShell({
  colorVar,
  muted,
  size = "md",
  className,
  children,
}: CatalogIconShellProps) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center",
        size === "lg" ? "size-12 rounded-xl" : "size-10 rounded-lg",
        className,
      )}
      style={typeIconShellStyle(colorVar, { muted })}
    >
      {children}
    </div>
  );
}

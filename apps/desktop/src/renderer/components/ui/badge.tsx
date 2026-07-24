import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";
import { type StatusTone, statusChip } from "./tone-presets";

export type BadgeTone = StatusTone;

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  /** Pill (rounded-full) vs inline chip (rounded-lg). */
  pill?: boolean;
}

/** Status / count / role chip — semantic tones only (color-tokens.mdc). */
export function Badge({
  tone = "muted",
  pill = false,
  className,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center border px-1.5 py-0.5 text-xs leading-none",
        pill ? "rounded-full" : "rounded-lg",
        statusChip[tone],
        className,
      )}
      {...props}
    />
  );
}

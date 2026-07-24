import { cn } from "@/lib/utils";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ComponentProps, ReactNode } from "react";

/**
 * Tooltip primitives over Radix — hover + keyboard-focus triggering, delay
 * grouping and collision-aware positioning are handled for us. A single
 * {@link TooltipProvider} is mounted once at the app root (see `App.tsx`); the
 * `SimpleTooltip` convenience covers the common "label on one trigger" case and
 * keeps migrating native `title=` attributes a one-line change.
 */
export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({
  className,
  sideOffset = 6,
  ...props
}: ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 max-w-xs rounded-lg border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-lg",
          "data-[state=delayed-open]:animate-dropdown-in",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
}

interface SimpleTooltipProps {
  /** The tip content shown on hover / focus. */
  label: ReactNode;
  /** The trigger element — styled in place via `asChild` (must accept a ref). */
  children: ReactNode;
  side?: ComponentProps<typeof TooltipPrimitive.Content>["side"];
  align?: ComponentProps<typeof TooltipPrimitive.Content>["align"];
}

export function SimpleTooltip({
  label,
  children,
  side,
  align,
}: SimpleTooltipProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align}>
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

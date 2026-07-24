import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

export type IconButtonSize = "sm" | "md";

const sizeClass: Record<IconButtonSize, string> = {
  sm: "size-7",
  md: "size-8",
};

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: IconButtonSize;
  /** Muted toolbar style vs accent hover on sidebar chrome. */
  tone?: "default" | "sidebar" | "primary" | "destructive";
}

/** Square icon-only button — sm = 28px, md = 32px per desktop-layout.mdc. */
export function IconButton({
  size = "sm",
  tone = "default",
  className,
  type = "button",
  ...props
}: IconButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg disabled:opacity-60",
        sizeClass[size],
        tone === "sidebar"
          ? "text-sidebar-foreground/60 hover:bg-sidebar-accent"
          : tone === "primary"
            ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
            : tone === "destructive"
              ? "bg-destructive text-destructive-foreground hover:bg-destructive/90 hover:text-destructive-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Shared header row for timeline cards (后台任务 / 状态条类卡片). */
export function PatternCardHeader({
  icon,
  iconClassName,
  label,
  labelClassName,
  badge,
  trailing,
}: {
  icon: ReactNode;
  iconClassName?: string;
  label: ReactNode;
  labelClassName?: string;
  badge?: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      {icon != null && (
        <span className={cn("mt-0.5 shrink-0", iconClassName)}>{icon}</span>
      )}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className={cn("text-xs font-medium", labelClassName)}>
          {label}
        </span>
        {badge}
        {trailing != null && (
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {trailing}
          </span>
        )}
      </div>
    </div>
  );
}

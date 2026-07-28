import { permissionAxesShortLabel } from "@/services/permissionAxes";
import type { PermissionChange } from "@/stores/permissionChanges";
import { Shield } from "lucide-react";

/**
 * 聊天主流里的「权限切换」系统提示行。
 * 锚在它生效的那一回合之前（切换「下一回合生效」）。
 */
export function PermissionChangeLine({ change }: { change: PermissionChange }) {
  const from =
    permissionAxesShortLabel(change.previous) ??
    (typeof change.previous === "string" ? change.previous : "？");
  const to =
    permissionAxesShortLabel(change.next) ??
    (typeof change.next === "string" ? change.next : "？");
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5">
        <Shield size={12} className="shrink-0" />
        权限 {from} → {to}
      </span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

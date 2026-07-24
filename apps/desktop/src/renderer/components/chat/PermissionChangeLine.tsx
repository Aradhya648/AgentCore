import { permissionPresetShortLabel } from "@/services/permissionPreset";
import type { PermissionChange } from "@/stores/permissionChanges";
import { Shield } from "lucide-react";

/**
 * 聊天主流里的「权限模式切换」系统提示行（原侧栏安全台账「权限模式 A → B」条目）。
 *
 * 居中分隔线样式，锚在它生效的那一回合之前（切换「下一回合生效」）——见 mergeTimeline。
 */
export function PermissionChangeLine({ change }: { change: PermissionChange }) {
  const from = permissionPresetShortLabel(change.previous) ?? change.previous;
  const to = permissionPresetShortLabel(change.next) ?? change.next;
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      <span className="inline-flex shrink-0 items-center gap-1.5">
        <Shield size={12} className="shrink-0" />
        权限模式 {from} → {to}
      </span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

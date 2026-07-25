import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  patchConversationCache,
  useConversations,
} from "@/hooks/useConversations";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  PERMISSION_PRESET_LABELS,
  isPermissionDowngrade,
  resolveDefaultPermissionPreset,
  setConversationPermissionPreset,
} from "@/services/permissionPreset";
import { useConversationStore } from "@/stores/conversation";
import { usePermissionChangeStore } from "@/stores/permissionChanges";
import type { SidecarPermissionPreset } from "@shared/sidecar-contract";
import { ChevronDown, Shield } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const OPTIONS: SidecarPermissionPreset[] = [
  "observe",
  "workspace",
  "full_trust",
];

/**
 * Composer permission-mode badge — sits beside {@link ModelPicker}.
 * New chats: picks the user's default (AutonomySettings → 新会话默认).
 * Existing chats: reads / writes conversation.permissionPreset
 * (升到「完全信任」需确认；只观察→开工授权直接切)。
 */
export function PermissionPresetBadge({ disabled }: { disabled?: boolean }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversations = useConversations();
  const [draftPreset, setDraftPreset] =
    useState<SidecarPermissionPreset>("workspace");
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const fromCache = conversationId
    ? conversations.find((c) => c.id === conversationId)?.permissionPreset
    : undefined;
  const preset = fromCache ?? draftPreset;

  useEffect(() => {
    if (fromCache) return;
    let alive = true;
    void resolveDefaultPermissionPreset().then((p) => {
      if (alive) setDraftPreset(p);
    });
    return () => {
      alive = false;
    };
  }, [fromCache]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const apply = async (next: SidecarPermissionPreset) => {
    if (next === preset || pending || disabled) return;
    if (
      !isPermissionDowngrade(preset, next) &&
      next === "full_trust" &&
      !window.confirm(
        "切换到「完全信任」后，AI 将与你同权执行命令（含本地运行代码）。确定继续？",
      )
    ) {
      return;
    }
    setOpen(false);
    if (!conversationId) {
      setDraftPreset(next);
      return;
    }
    setPending(true);
    try {
      const saved = await setConversationPermissionPreset(conversationId, next);
      patchConversationCache(conversationId, { permissionPreset: saved });
      // 切换在返回前已同步写下 permission.preset_changed 审计行；重拉会话权限审计让主流的系统
      // 提示行即时出现（不阻塞、失败静默）。
      void usePermissionChangeStore
        .getState()
        .load(conversationId)
        .catch(() => {});
      notifySuccess(`已切换为「${PERMISSION_PRESET_LABELS[saved].short}」`);
    } catch (e) {
      notifyError(e, "切换权限模式失败");
    } finally {
      setPending(false);
    }
  };

  const label = PERMISSION_PRESET_LABELS[preset].short;

  return (
    <div ref={rootRef} className="relative shrink-0">
      <SimpleTooltip label={PERMISSION_PRESET_LABELS[preset].description}>
        <button
          type="button"
          disabled={disabled || pending}
          onClick={() => setOpen((v) => !v)}
          aria-label={`权限模式：${label}`}
          aria-expanded={open}
          className={`inline-flex h-8 max-w-36 items-center gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground ${
            disabled || pending ? "cursor-not-allowed opacity-60" : ""
          }`}
        >
          <Shield size={14} className="shrink-0" />
          <span className="truncate">{label}</span>
          <ChevronDown size={12} className="shrink-0 opacity-60" />
        </button>
      </SimpleTooltip>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 w-56 rounded-xl border border-border bg-popover p-1 shadow-lg">
          {OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              aria-current={opt === preset ? "true" : undefined}
              onClick={() => void apply(opt)}
              className={
                opt === preset
                  ? "flex w-full flex-col rounded-lg bg-primary/10 px-3 py-2 text-left"
                  : "flex w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-accent/50"
              }
            >
              <span className="text-sm font-medium text-foreground">
                {PERMISSION_PRESET_LABELS[opt].short}
              </span>
              <span className="mt-0.5 text-xs text-muted-foreground">
                {PERMISSION_PRESET_LABELS[opt].description}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

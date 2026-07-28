import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  patchConversationCache,
  useConversations,
} from "@/hooks/useConversations";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  type AutonomyRecipe,
  COMMAND_OPTIONS,
  DEFAULT_PERMISSION_AXES,
  FILE_WRITE_OPTIONS,
  HOST_OPTIONS,
  type PermissionAxes,
  RECIPE_LABELS,
  RECIPE_ORDER,
  TEAM_KICKOFF_OPTIONS,
  axesEqual,
  axesShortLabel,
  confirmAutoCommandIfNeeded,
  isIllegalAxes,
  matchRecipe,
  recipeToAxes,
  resolveDefaultPermissionAxes,
  setComposerDraftAxes,
  setConversationPermissionAxes,
  setUserDefaultRecipe,
} from "@/services/permissionAxes";
import { useConversationStore } from "@/stores/conversation";
import { usePermissionChangeStore } from "@/stores/permissionChanges";
import { ChevronDown, Shield } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Composer permission badge — recipes first; four-axis custom folded.
 * New chats: draft axes (seeded from 新会话默认配方); existing: read/write
 * ``conversation.permissionAxes``（下一回合生效）.
 */
export function PermissionAxesBadge({ disabled }: { disabled?: boolean }) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversations = useConversations();
  const [draftAxes, setDraftAxes] = useState<PermissionAxes>(
    DEFAULT_PERMISSION_AXES,
  );
  const [open, setOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const fromCache = conversationId
    ? conversations.find((c) => c.id === conversationId)?.permissionAxes
    : undefined;
  const axes = fromCache ?? draftAxes;
  const recipe = matchRecipe(axes);
  const label = axesShortLabel(axes);
  const isCustom = recipe === "custom";

  useEffect(() => {
    if (fromCache) return;
    let alive = true;
    void resolveDefaultPermissionAxes().then((a) => {
      if (alive) setDraftAxes(a);
    });
    return () => {
      alive = false;
    };
  }, [fromCache]);

  useEffect(() => {
    if (!open) {
      setCustomOpen(false);
      return;
    }
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const apply = async (next: PermissionAxes, opts: { close: boolean }) => {
    if (pending || disabled) return;
    if (isIllegalAxes(next)) return;
    if (axesEqual(next, axes)) {
      return;
    }
    if (!confirmAutoCommandIfNeeded(axes, next)) return;
    if (opts.close) setOpen(false);
    if (!conversationId) {
      setDraftAxes(next);
      setComposerDraftAxes(next);
      return;
    }
    setPending(true);
    try {
      const saved = await setConversationPermissionAxes(conversationId, next);
      patchConversationCache(conversationId, { permissionAxes: saved });
      void usePermissionChangeStore
        .getState()
        .load(conversationId)
        .catch(() => {});
      notifySuccess(`已切换为「${axesShortLabel(saved)}」`);
    } catch (e) {
      notifyError(e, "切换权限失败");
    } finally {
      setPending(false);
    }
  };

  const applyRecipe = (id: AutonomyRecipe) => {
    setCustomOpen(false);
    void apply(recipeToAxes(id), { close: true });
  };

  const setAsSessionDefault = async () => {
    if (recipe === "custom" || pending || disabled) return;
    // Only built-in recipes may become the user-level default.
    setPending(true);
    try {
      const saved = await setUserDefaultRecipe(recipe);
      notifySuccess(`新会话将默认「${RECIPE_LABELS[saved].short}」`);
    } catch (e) {
      notifyError(e, "设置默认失败");
    } finally {
      setPending(false);
    }
  };

  const patchAxis = <K extends keyof PermissionAxes>(
    key: K,
    value: PermissionAxes[K],
  ) => {
    const next = { ...axes, [key]: value };
    // Selecting auto while file_write=ask → coerce file_write to session
    // (illegal combo must not be selectable / sent).
    if (key === "command" && value === "auto" && next.file_write === "ask") {
      next.file_write = "session";
    }
    if (key === "file_write" && value === "ask" && next.command === "auto") {
      return; // disabled in UI
    }
    void apply(next, { close: false });
  };

  const tip = isCustom
    ? `自定义：${axesCustomTip(axes)}`
    : RECIPE_LABELS[recipe].description;

  return (
    <div ref={rootRef} className="relative shrink-0">
      <SimpleTooltip label={tip}>
        <button
          type="button"
          disabled={disabled || pending}
          onClick={() => setOpen((v) => !v)}
          aria-label={`权限：${label}`}
          aria-expanded={open}
          className={cn(
            "inline-flex h-8 max-w-44 items-center gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            (disabled || pending) && "cursor-not-allowed opacity-60",
          )}
        >
          <Shield size={14} className="shrink-0" />
          <span className="truncate">{label}</span>
          <ChevronDown size={12} className="shrink-0 opacity-60" />
        </button>
      </SimpleTooltip>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 w-80 rounded-xl border border-border bg-popover p-2 shadow-lg">
          <p className="px-1 pb-1.5 text-xs font-medium text-muted-foreground">
            配方
          </p>
          <div className="space-y-0.5">
            {RECIPE_ORDER.map((id) => {
              const selected = recipe === id;
              const meta = RECIPE_LABELS[id];
              return (
                <SimpleTooltip key={id} label={meta.description}>
                  <button
                    type="button"
                    aria-current={selected ? "true" : undefined}
                    onClick={() => applyRecipe(id)}
                    className={cn(
                      "flex w-full items-baseline gap-1.5 rounded-lg px-2.5 py-1.5 text-left",
                      selected ? "bg-primary/10" : "hover:bg-accent/50",
                    )}
                  >
                    <span className="shrink-0 text-sm font-medium text-foreground">
                      {meta.short}
                      {id === "write_code" ? " · 荐" : ""}
                    </span>
                    <span className="min-w-0 truncate text-xs text-muted-foreground">
                      {meta.description}
                    </span>
                  </button>
                </SimpleTooltip>
              );
            })}
          </div>

          <div className="mt-2 border-t border-border/60 px-1 pt-2">
            <SimpleTooltip
              label={
                isCustom
                  ? "仅内置配方可设为新会话默认"
                  : "写入账户默认；只影响之后新建的对话"
              }
            >
              <span className="block">
                <button
                  type="button"
                  disabled={isCustom || pending || disabled}
                  onClick={() => void setAsSessionDefault()}
                  className={cn(
                    "w-full rounded-lg px-2.5 py-1.5 text-left text-xs font-medium",
                    isCustom || pending || disabled
                      ? "cursor-not-allowed text-muted-foreground/50"
                      : "text-foreground hover:bg-accent/50",
                  )}
                >
                  设为新会话默认
                </button>
              </span>
            </SimpleTooltip>
          </div>

          <div className="mt-2 border-t border-border/60 pt-2">
            <button
              type="button"
              aria-expanded={customOpen}
              onClick={() => setCustomOpen((v) => !v)}
              className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left hover:bg-accent/50"
            >
              <span className="text-xs font-medium text-muted-foreground">
                自定义权限轴
                {isCustom ? (
                  <span className="ml-1.5 text-foreground">· 当前</span>
                ) : null}
              </span>
              <ChevronDown
                size={12}
                className={cn(
                  "shrink-0 text-muted-foreground opacity-60 transition-transform",
                  customOpen && "rotate-180",
                )}
              />
            </button>

            {customOpen && (
              <div className="mt-1 space-y-2 px-0.5 pb-1">
                <AxisSegment
                  title="改文件"
                  options={FILE_WRITE_OPTIONS}
                  value={axes.file_write}
                  disabledOption={(v) => v === "ask" && axes.command === "auto"}
                  disabledReason="免审执行须同时「本会话信任」改文件"
                  onSelect={(v) => patchAxis("file_write", v)}
                />
                <AxisSegment
                  title="执行命令"
                  options={COMMAND_OPTIONS}
                  value={axes.command}
                  disabledOption={(v) =>
                    v === "auto" && axes.file_write === "ask"
                  }
                  disabledReason="免审执行须同时「本会话信任」改文件"
                  onSelect={(v) => patchAxis("command", v)}
                />
                <AxisSegment
                  title="组队确认"
                  options={TEAM_KICKOFF_OPTIONS}
                  value={axes.team_kickoff}
                  onSelect={(v) => patchAxis("team_kickoff", v)}
                />
                <AxisSegment
                  title="本机 Host"
                  options={HOST_OPTIONS}
                  value={axes.host}
                  onSelect={(v) => patchAxis("host", v)}
                />
                <div className="flex justify-end pt-1">
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-lg px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                  >
                    完成
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** @deprecated Prefer {@link PermissionAxesBadge}. */
export const PermissionPresetBadge = PermissionAxesBadge;

function axesCustomTip(axes: PermissionAxes): string {
  const file =
    FILE_WRITE_OPTIONS.find((o) => o.value === axes.file_write)?.short ?? "";
  const cmd =
    COMMAND_OPTIONS.find((o) => o.value === axes.command)?.short ?? "";
  const team =
    TEAM_KICKOFF_OPTIONS.find((o) => o.value === axes.team_kickoff)?.short ??
    "";
  const host = HOST_OPTIONS.find((o) => o.value === axes.host)?.short ?? "";
  return `${file} · ${cmd} · ${team} · ${host}`;
}

function AxisSegment<T extends string>({
  title,
  options,
  value,
  onSelect,
  disabledOption,
  disabledReason,
}: {
  title: string;
  options: { value: T; short: string; description: string }[];
  value: T;
  onSelect: (v: T) => void;
  disabledOption?: (v: T) => boolean;
  disabledReason?: string;
}) {
  return (
    <div>
      <p className="px-1 pb-1 text-xs font-medium text-muted-foreground">
        {title}
      </p>
      <div className="flex flex-wrap gap-1">
        {options.map((opt) => {
          const selected = opt.value === value;
          const blocked = disabledOption?.(opt.value) ?? false;
          const tip = blocked
            ? (disabledReason ?? opt.description)
            : opt.description;
          return (
            <SimpleTooltip key={opt.value} label={tip}>
              {/* span: disabled buttons skip pointer events → tooltip still works */}
              <span className="inline-flex">
                <button
                  type="button"
                  disabled={blocked}
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onSelect(opt.value)}
                  className={cn(
                    "rounded-lg px-2.5 py-1 text-xs",
                    blocked && "cursor-not-allowed opacity-40",
                    !blocked &&
                      (selected
                        ? "bg-primary/15 font-medium text-foreground"
                        : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"),
                  )}
                >
                  {opt.short}
                </button>
              </span>
            </SimpleTooltip>
          );
        })}
      </div>
      {disabledReason && options.some((o) => disabledOption?.(o.value)) ? (
        <p className="mt-1 px-1 text-xs text-muted-foreground">
          {disabledReason}
        </p>
      ) : null}
    </div>
  );
}

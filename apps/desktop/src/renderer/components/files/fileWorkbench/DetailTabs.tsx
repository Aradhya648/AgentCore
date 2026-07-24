import { IconButton } from "@/components/ui";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { cn } from "@/lib/utils";
import { FileText, X } from "lucide-react";
import { type Tab, tabKey } from "./storage";

/**
 * Horizontal tab strip for the detail pane. Pointer-down (not click) activates so
 * a tab switches even when the close button steals the click; middle-click closes
 * (browser-tab convention). Right-click opens 关闭 / 关闭其他 / 关闭全部. Overflows
 * scroll horizontally rather than wrapping.
 */
export function DetailTabs({
  tabs,
  activeKey,
  onActivate,
  onClose,
  onCloseOthers,
  onCloseAll,
}: {
  tabs: Tab[];
  activeKey: string | null;
  onActivate: (key: string) => void;
  onClose: (key: string) => void;
  onCloseOthers: (key: string) => void;
  onCloseAll: () => void;
}) {
  return (
    <div className="flex shrink-0 items-stretch overflow-x-auto border-b">
      {tabs.map((t) => {
        const key = tabKey(t.wsId, t.path);
        const active = key === activeKey;
        return (
          <ContextMenu key={key}>
            <ContextMenuTrigger asChild>
              <div
                role="tab"
                aria-selected={active}
                tabIndex={0}
                title={t.path}
                onPointerDown={(e) => {
                  if (e.button === 1) {
                    e.preventDefault();
                    onClose(key);
                  } else if (e.button === 0) {
                    onActivate(key);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onActivate(key);
                  } else if (e.key === "Delete" || e.key === "Backspace") {
                    e.preventDefault();
                    onClose(key);
                  }
                }}
                className={cn(
                  "group flex min-w-0 max-w-[180px] shrink-0 cursor-pointer items-center gap-1.5 border-r px-3 py-1.5 text-sm",
                  active
                    ? "bg-background text-foreground"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted",
                )}
              >
                <FileText size={13} className="shrink-0 opacity-60" />
                <span className="min-w-0 flex-1 truncate">{t.name}</span>
                <IconButton
                  aria-label={`关闭 ${t.name}`}
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    onClose(key);
                  }}
                  className={cn(
                    "size-6 shrink-0",
                    active ? "opacity-70" : "opacity-0 group-hover:opacity-70",
                  )}
                >
                  <X size={13} />
                </IconButton>
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent className="min-w-40">
              <ContextMenuItem onSelect={() => onClose(key)}>
                <X size={14} className="shrink-0" />
                <span className="flex-1 truncate">关闭</span>
              </ContextMenuItem>
              <ContextMenuItem
                disabled={tabs.length <= 1}
                onSelect={() => onCloseOthers(key)}
              >
                <span className="flex-1 truncate">关闭其他</span>
              </ContextMenuItem>
              <ContextMenuSeparator />
              <ContextMenuItem onSelect={onCloseAll}>
                <span className="flex-1 truncate">关闭全部</span>
              </ContextMenuItem>
            </ContextMenuContent>
          </ContextMenu>
        );
      })}
    </div>
  );
}

import { Button, IconButton } from "@/components/ui";
import { chord } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { Search } from "lucide-react";

/** Fake input that opens the global command palette (Cmd/Ctrl+K). */
export function SearchTrigger({
  collapsed = false,
  onClick,
  className,
}: {
  collapsed?: boolean;
  onClick: () => void;
  className?: string;
}) {
  if (collapsed) {
    return (
      <div className={cn("flex justify-center", className)}>
        <IconButton
          tone="sidebar"
          onClick={onClick}
          aria-label="搜索或运行命令"
        >
          <Search size={16} />
        </IconButton>
      </div>
    );
  }

  return (
    <Button
      variant="neutral"
      onClick={onClick}
      icon={<Search size={13} className="shrink-0" />}
      className={cn(
        "w-full justify-start gap-2 border border-sidebar-border px-3 text-sm text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground",
        className,
      )}
    >
      搜索或运行命令…
      <kbd className="ml-auto text-xs text-sidebar-foreground/40">
        {chord("k")}
      </kbd>
    </Button>
  );
}

/** Compact trigger for the desktop title bar (not full-width). */
export function TitleBarSearchTrigger({
  onClick,
  className,
}: {
  onClick: () => void;
  className?: string;
}) {
  return (
    <Button
      variant="neutral"
      onClick={onClick}
      icon={<Search size={13} className="shrink-0" />}
      className={cn(
        "mr-2 h-7 gap-2 border border-sidebar-border px-3 text-sm text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground",
        className,
      )}
    >
      搜索或运行命令…{" "}
      <kbd className="text-xs text-sidebar-foreground/40">{chord("k")}</kbd>
    </Button>
  );
}

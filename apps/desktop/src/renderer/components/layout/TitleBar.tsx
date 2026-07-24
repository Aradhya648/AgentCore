import { WindowControls } from "@/components/layout/WindowControls";
import { WindowFrameMenu } from "@/components/layout/WindowFrameMenu";
import { IconButton, TitleBarSearchTrigger } from "@/components/ui";
import { isMac, macTitleBarInsetClass } from "@/lib/platform";
import { useSidebarStore } from "@/stores/sidebar";
import { useUIStore } from "@/stores/ui";
import { PanelLeft, PanelLeftClose } from "lucide-react";

// Shared frameless-window title-bar shell: fixed height, bottom border, sidebar
// surface, full-width drag region (macOS adds a left inset for the traffic lights).
const shellClass = `flex h-10 shrink-0 items-center border-b border-sidebar-border bg-sidebar [-webkit-app-region:drag] ${isMac ? macTitleBarInsetClass : ""}`;

export function TitleBar() {
  const collapsed = useSidebarStore((s) => s.collapsed);
  const toggleCollapsed = useSidebarStore((s) => s.toggleCollapsed);
  const openSearch = useUIStore((s) => s.openSearch);

  return (
    <header className={shellClass}>
      {/* Left: brand + sidebar toggle — width syncs with sidebar */}
      <div
        className={`flex items-center gap-2 px-3 transition-[width] duration-200 ${collapsed ? "w-14" : "w-60"}`}
      >
        {!collapsed && (
          <span className="flex flex-1 items-center gap-1.5 text-sm font-semibold text-sidebar-foreground [-webkit-app-region:no-drag]">
            AgentCore
            {import.meta.env.DEV && (
              <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
                DEV
              </span>
            )}
          </span>
        )}
        <IconButton
          tone="sidebar"
          onClick={toggleCollapsed}
          className="[-webkit-app-region:no-drag]"
        >
          {collapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
        </IconButton>
      </div>

      {/* Drag spacer */}
      <div className="flex-1" />

      {/* Search trigger + window controls (Win/Linux; macOS uses traffic lights) */}
      <div className="flex items-center [-webkit-app-region:no-drag]">
        <WindowFrameMenu />
        <TitleBarSearchTrigger onClick={() => openSearch()} />

        <WindowControls />
      </div>
    </header>
  );
}

/**
 * Window chrome for the pre-auth screens (登录 / 加载中 / 后端不可用), which render
 * outside AppShell and would otherwise have no title bar at all. On a frameless window
 * that leaves no way to drag or close the window until login succeeds — so this keeps
 * the drag region + min/max/close (macOS uses the native traffic lights in the inset),
 * while dropping the sidebar toggle and search (meaningless before auth).
 */
export function MinimalTitleBar() {
  return (
    <header className={shellClass}>
      <div className="flex-1" />
      <div className="flex items-center [-webkit-app-region:no-drag]">
        <WindowControls />
      </div>
    </header>
  );
}

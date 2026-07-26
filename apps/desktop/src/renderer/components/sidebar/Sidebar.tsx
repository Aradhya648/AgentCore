import { BrandMark } from "@/components/brand/BrandMark";
import { IconButton, SearchTrigger, SurfaceRowButton } from "@/components/ui";
import { isWebClient } from "@/lib/capabilities";
import { startNewConversation } from "@/lib/newConversation";
import { useUnreadTotal } from "@/stores/messaging";
import { useSidebarStore } from "@/stores/sidebar";
import { useUIStore } from "@/stores/ui";
import {
  Files,
  Mail,
  MessageSquare,
  PanelLeft,
  PanelLeftClose,
  Wrench,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  RecentConversations,
  ViewAllConversations,
} from "./RecentConversations";
import { UserMenu } from "./UserMenu";
import { WorkspaceGroups } from "./WorkspaceGroups";

const NAV_ITEMS = [
  { icon: MessageSquare, label: "新对话", route: "/" },
  { icon: Files, label: "文件", route: "/files" },
  { icon: Mail, label: "消息", route: "/messages" },
  { icon: Wrench, label: "工具箱", route: "/toolbox" },
] as const;

export function Sidebar() {
  const collapsed = useSidebarStore((s) => s.collapsed);
  const toggleCollapsed = useSidebarStore((s) => s.toggleCollapsed);
  const openSearch = useUIStore((s) => s.openSearch);
  const unread = useUnreadTotal();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // 浏览器版没有桌面顶栏（AppShell 已隐藏），品牌 / 折叠按钮 / 搜索改由侧栏顶部承载。
  // 桌面 & 离线预览下这里不渲染（它们仍有顶栏）。
  const webClient = isWebClient();

  // 「对话」(route "/") 既是「新建对话」动作、又兼作对话区的区段指示：仅在「没有具体会话被
  // 选中」的状态下高亮——空白草稿 `/` 与「全部对话」页 `/conversations`；一旦进入具体会话
  // `/conversations/:id`，高亮就让位给下方最近列表里的那条会话行（避免导航与会话行双重高亮）。
  // 其余导航是普通区段 tab，落在该区段（含子路由）即整段高亮。
  const isNavActive = (route: string) =>
    route === "/"
      ? pathname === "/" || pathname === "/conversations"
      : pathname === route || pathname.startsWith(`${route}/`);

  // 「对话」入口默认就是新建一个空白对话；回到旧对话走下方列表 /「全部对话」。
  const handleNewConversation = () => startNewConversation(navigate);

  return (
    <aside
      className={`flex flex-shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 ${collapsed ? "w-14" : "w-60"}`}
      style={{ backgroundImage: "var(--sidebar-gradient)" }}
    >
      {/* 浏览器版头部：品牌 + 折叠按钮 + 紧凑搜索（替代被隐藏的桌面顶栏）。折叠成 w-14
          图标条时按钮仍在，展开 w-60 时显示品牌，两种状态都够得着。 */}
      {webClient && (
        <>
          <div className="space-y-2 px-2 pt-2">
            <div
              className={`flex items-center gap-1 ${collapsed ? "justify-center" : "px-1"}`}
            >
              {!collapsed && (
                <span className="flex flex-1 items-center gap-1.5 text-sidebar-foreground">
                  <BrandMark size="sm" />
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
                aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
              >
                {collapsed ? (
                  <PanelLeft size={16} />
                ) : (
                  <PanelLeftClose size={16} />
                )}
              </IconButton>
            </div>

            <SearchTrigger collapsed={collapsed} onClick={() => openSearch()} />
          </div>
          <div className="mx-3 mt-2 border-t border-sidebar-border" />
        </>
      )}

      {/* Navigation */}
      <nav className="space-y-0.5 px-2 pt-2 pb-2">
        {NAV_ITEMS.map((item) => {
          const active = isNavActive(item.route);
          const showBadge = item.route === "/messages" && unread > 0;
          return (
            <SurfaceRowButton
              key={item.route}
              active={active}
              onClick={() =>
                item.route === "/"
                  ? handleNewConversation()
                  : navigate(item.route)
              }
              // 与下方列表同高（h-8）——整条侧栏一个 34px 节奏；导航的层级由分隔线 +
              // font-medium + 图标承担，不再靠行高撑。
              className={`relative h-8 font-medium ${collapsed ? "justify-center px-0" : ""}`}
            >
              <item.icon size={16} className="shrink-0" />
              {!collapsed && <span>{item.label}</span>}
              {showBadge &&
                (collapsed ? (
                  <span
                    aria-label={`${unread} 条未读`}
                    className="absolute right-2 top-1.5 size-2 rounded-full bg-primary"
                  />
                ) : (
                  <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground">
                    {unread > 99 ? "99+" : unread}
                  </span>
                ))}
            </SurfaceRowButton>
          );
        })}
      </nav>

      {/* Divider — nav vs conversation list */}
      <div className="mx-3 border-t border-sidebar-border" />

      {/* 项目 (collapsible folder groups) + 快速对话 (裸聊 flat list); full list
          lives on /conversations (前端UX §一 方案B). */}
      <div className="flex-1 overflow-y-auto">
        {!collapsed && (
          <>
            <WorkspaceGroups />
            <RecentConversations />
            <ViewAllConversations />
          </>
        )}
      </div>

      {/* Footer: User menu */}
      <UserMenu />
    </aside>
  );
}

import { listChats } from "@/api/messaging";
import { usePolling } from "@/lib/usePolling";
// Persistent bottom tab bar (手机端布局重构 · 底部 4-tab 导航).
//
// The mobile shell's top-level switcher: 对话 (AI) / 消息 (人际 IM) / 文件 (跨工作区文件总览) /
// 我的 (账户·设置). Mirrors the desktop sidebar's mental model (apps/desktop … sidebar/Sidebar
// NAV_ITEMS) compressed to the four destinations that survive the 手机端「减法」and have a
// built mobile home. Rendered by TabLayout on top-level pages only; full-screen detail pages
// (聊天 / IM 线程 / 设置子页 / 文件预览) push over it without the bar, so it never fights a
// page's own bottom composer.
//
// The 消息 tab carries an aggregate unread badge. Mobile has no global messaging store (each
// page fetches its own), so the count is polled here (visibility-aware, see usePolling) by
// summing the chat list's per-chat unread — the same listChats the 消息 page already uses.
import type { LucideIcon } from "lucide-react";
import { Files, Mail, MessageSquare, User } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

interface TabDef {
  label: string;
  route: string;
  Icon: LucideIcon;
}

const TABS: TabDef[] = [
  { label: "对话", route: "/", Icon: MessageSquare },
  { label: "消息", route: "/im", Icon: Mail },
  { label: "文件", route: "/files", Icon: Files },
  { label: "我的", route: "/more", Icon: User },
];

/** A tab owns its section: the 对话 tab covers the draft home (`/`) AND an open conversation
 *  (`/c/:id`); others light over their drill-down children (e.g. /files/:wsId keeps 文件 lit).
 *  Detail pages that hide the bar never reach this. */
function isActive(pathname: string, route: string): boolean {
  if (route === "/") return pathname === "/" || pathname.startsWith("/c/");
  return pathname === route || pathname.startsWith(`${route}/`);
}

export function TabBar() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [unread, setUnread] = useState(0);

  usePolling(async () => {
    try {
      const chats = await listChats();
      setUnread(chats.reduce((n, c) => n + (c.unread ?? 0), 0));
    } catch {
      /* keep the last count — a transient failure shouldn't clear the badge */
    }
  }, 15_000);

  return (
    <nav className="tabbar">
      {TABS.map(({ label, route, Icon }) => {
        const active = isActive(pathname, route);
        const showBadge = route === "/im" && unread > 0;
        return (
          <button
            key={route}
            type="button"
            className={`tab${active ? " tab-active" : ""}`}
            aria-current={active ? "page" : undefined}
            onClick={() => navigate(route)}
          >
            <span className="tab-icon">
              <Icon size={22} strokeWidth={active ? 2.4 : 2} />
              {showBadge && (
                <span className="tab-badge">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </span>
            <span className="tab-label">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}

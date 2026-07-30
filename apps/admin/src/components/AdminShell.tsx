import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/services/api";
import { logout } from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import {
  BarChart3,
  LayoutDashboard,
  LogOut,
  type LucideIcon,
  Megaphone,
  MessageSquare,
  ScrollText,
  Server,
  ShieldCheck,
  Users,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { toast } from "sonner";

/**
 * The console's sections: 概览 / 用户 / 分析 / 审计 / 公告 / 系统.
 * URL-routed via react-router for bookmarkable deep links.
 * Invites UI is deprecated (open registration); API remains for legacy codes.
 */
export type AdminTab =
  | "overview"
  | "users"
  | "conversations"
  | "analytics"
  | "audit"
  | "notices"
  | "system";

const NAV: { id: AdminTab; label: string; icon: LucideIcon; path: string }[] =
  [
    { id: "overview", label: "概览", icon: LayoutDashboard, path: "/overview" },
    { id: "users", label: "用户", icon: Users, path: "/users" },
    { id: "conversations", label: "对话", icon: MessageSquare, path: "/conversations/conversations" },
    { id: "analytics", label: "分析", icon: BarChart3, path: "/analytics/cost" },
    { id: "audit", label: "审计", icon: ScrollText, path: "/audit" },
    { id: "notices", label: "公告", icon: Megaphone, path: "/notices" },
    { id: "system", label: "系统", icon: Server, path: "/system" },
  ];

function navClassName({ isActive }: { isActive: boolean }) {
  return cn(
    "flex h-10 w-full items-center gap-3 rounded-lg px-3 text-base outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
    isActive
      ? "bg-accent font-medium text-accent-foreground"
      : "text-muted-foreground hover:bg-accent hover:text-foreground",
  );
}

function navItemActive(id: AdminTab, pathname: string): boolean {
  if (id === "users") return pathname.startsWith("/users");
  if (id === "analytics") return pathname.startsWith("/analytics");
  if (id === "conversations") return pathname.startsWith("/conversations");
  return pathname === NAV.find((n) => n.id === id)?.path;
}

export function AdminShell() {
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const setUnauthenticated = useAuthStore((s) => s.setUnauthenticated);

  const handleLogout = async () => {
    try {
      await logout();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setUnauthenticated();
    }
  };

  const displayName = user?.displayName || user?.username;

  return (
    <div className="flex h-screen">
      <aside className="flex w-60 shrink-0 flex-col border-border border-r bg-muted/30">
        <div className="flex h-14 shrink-0 items-center gap-3 px-6 font-semibold text-base text-foreground">
          <ShieldCheck size={20} className="text-primary" />
          管理后台
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-3">
          {NAV.map((item) => {
            const Icon = item.icon;
            const isActive = navItemActive(item.id, location.pathname);
            return (
              <NavLink
                key={item.id}
                to={item.path}
                aria-current={isActive ? "page" : undefined}
                className={navClassName({ isActive })}
              >
                <Icon size={18} className="shrink-0" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="flex shrink-0 items-center gap-2 border-border border-t p-3">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-sm font-medium uppercase">
              {(displayName ?? "?").charAt(0)}
            </div>
            <NavLink
              to="/account"
              className="min-w-0 flex-1 truncate text-base text-muted-foreground transition-colors hover:text-foreground"
              title={displayName}
            >
              {displayName}
            </NavLink>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0 gap-2 text-muted-foreground hover:text-foreground"
            onClick={() => void handleLogout()}
          >
            <LogOut size={16} />
            退出
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

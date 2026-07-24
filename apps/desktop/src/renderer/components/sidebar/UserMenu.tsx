import { Button, IconButton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { logout } from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar";
import { useUserStore } from "@/stores/user";
import { BookOpen, LogOut, MoreVertical, Settings } from "lucide-react";
import { useNavigate } from "react-router-dom";

export function UserMenu() {
  const collapsed = useSidebarStore((s) => s.collapsed);
  const profile = useUserStore((s) => s.profile);
  const authUser = useAuthStore((s) => s.user);
  const navigate = useNavigate();

  const displayName =
    authUser?.displayName || authUser?.username || profile.displayName;
  const initials = displayName.charAt(0).toUpperCase();

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      /* clear the session client-side regardless of the network result */
    }
    useAuthStore.getState().setUnauthenticated();
  };

  const avatarUrl = authUser?.avatarUrl ?? profile.avatarUrl;
  const avatar = (
    <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-sm font-medium text-sidebar-accent-foreground">
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt={displayName}
          className="size-8 rounded-full object-cover"
        />
      ) : (
        initials
      )}
    </div>
  );

  const menu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {collapsed ? (
          <Button
            variant="ghost"
            aria-label="账户菜单"
            className="h-auto rounded-full p-0 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-accent"
          >
            {avatar}
          </Button>
        ) : (
          <IconButton
            tone="sidebar"
            aria-label="更多"
            className="text-sidebar-foreground/50 outline-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-accent"
          >
            <MoreVertical size={14} />
          </IconButton>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent side={collapsed ? "right" : "top"} align="end">
        <DropdownMenuItem onSelect={() => navigate("/toolbox/manual")}>
          <BookOpen size={14} />
          产品手册
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/more")}>
          <Settings size={14} />
          设置
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="danger" onSelect={() => void handleLogout()}>
          <LogOut size={14} />
          登出
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  return (
    <div className="border-t border-sidebar-border p-2">
      <div
        className={`flex items-center ${collapsed ? "justify-center" : "gap-3 px-3"}`}
      >
        {collapsed ? (
          <SimpleTooltip label="账户菜单" side="right">
            {menu}
          </SimpleTooltip>
        ) : (
          <>
            {avatar}
            <span className="flex-1 truncate text-sm text-sidebar-foreground/80">
              {displayName}
            </span>
            <SimpleTooltip label="登出">
              <IconButton
                tone="sidebar"
                onClick={() => void handleLogout()}
                aria-label="登出"
                className="text-sidebar-foreground/50 outline-none hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-accent"
              >
                <LogOut size={14} />
              </IconButton>
            </SimpleTooltip>
            <SimpleTooltip label="更多">{menu}</SimpleTooltip>
          </>
        )}
      </div>
    </div>
  );
}

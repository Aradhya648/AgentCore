import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { useStandingInboxBadge } from "@/stores/standingInbox";
import { ChevronLeft } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

const TABS = [
  {
    id: "tasks",
    label: "任务",
    to: APP_PATHS.toolbox.automations.root,
    end: true,
  },
  {
    id: "inbox",
    label: "收件箱",
    to: APP_PATHS.toolbox.automations.inbox,
    end: false,
    badge: true as const,
  },
] as const;

/**
 * 工具箱 · 自动化专页壳：任务 | 收件箱（子路径深链）。
 */
export function AutomationsPage() {
  const navigate = useNavigate();
  const inboxBadge = useStandingInboxBadge();

  return (
    <PageContainer width="canvas">
      <Button
        variant="ghost"
        onClick={() => navigate("/toolbox")}
        className="mb-4 h-auto gap-1 px-0 py-0 text-sm text-muted-foreground hover:text-foreground"
        icon={<ChevronLeft size={16} />}
      >
        工具箱
      </Button>

      <header>
        <h1 className="text-xl font-semibold text-foreground">自动化</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          定时或 Webhook 触发后，由 CEO 自动开一轮协作；回来只审摘要与待拍板。
        </p>
      </header>

      <nav
        aria-label="自动化分区"
        className="mt-6 flex w-fit items-center gap-0.5 rounded-lg border border-border p-0.5"
      >
        {TABS.map((tab) => (
          <NavLink
            key={tab.id}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm transition-colors",
                isActive
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )
            }
          >
            {tab.label}
            {"badge" in tab && inboxBadge > 0 ? (
              <span
                aria-label={`${inboxBadge} 条待处理`}
                className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground"
              >
                {inboxBadge > 99 ? "99+" : inboxBadge}
              </span>
            ) : null}
          </NavLink>
        ))}
      </nav>

      <div className="mt-6">
        <Outlet />
      </div>
    </PageContainer>
  );
}

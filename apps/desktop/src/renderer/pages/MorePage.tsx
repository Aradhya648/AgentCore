import { SectionLabel, SurfaceNavLink } from "@/components/ui";
import { useProductNoticesUndismissedCount } from "@/stores/productNotices";
import {
  Cpu,
  Gauge,
  Info,
  KeyRound,
  Keyboard,
  type LucideIcon,
  Megaphone,
  MessageSquarePlus,
  Palette,
  Shield,
  UserCog,
} from "lucide-react";
import { Outlet } from "react-router-dom";

interface NavItem {
  icon: LucideIcon;
  label: string;
  path: string;
  /** Show undismissed product-notice count (公告 only). */
  noticesBadge?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Settings are grouped by intent: 模型 (组合) + 服务商 (Key) adjacent; 账户 /
// 偏好 / 关于. Opening /more 落点见 MoreIndexRedirect。
// 「自动化」已迁至工具箱 #/toolbox/automations。
// AI 记忆内容管理在「文件」页，不设设置子页。
// 新会话默认权限配方：对话内权限徽章「设为新会话默认」（无设置子页）。
const NAV_GROUPS: NavGroup[] = [
  {
    label: "模型",
    items: [
      { icon: Cpu, label: "模型", path: "/more/model" },
      { icon: KeyRound, label: "服务商", path: "/more/providers" },
    ],
  },
  {
    label: "账户",
    items: [
      { icon: UserCog, label: "账户设置", path: "/more/account" },
      { icon: Gauge, label: "用量", path: "/more/usage" },
    ],
  },
  {
    label: "消息",
    items: [{ icon: Shield, label: "消息隐私", path: "/more/messages" }],
  },
  {
    label: "偏好",
    items: [
      { icon: Palette, label: "外观", path: "/more/appearance" },
      { icon: Keyboard, label: "快捷键", path: "/more/shortcuts" },
    ],
  },
  {
    label: "反馈",
    items: [{ icon: MessageSquarePlus, label: "反馈", path: "/more/feedback" }],
  },
  {
    label: "关于",
    items: [
      {
        icon: Megaphone,
        label: "公告",
        path: "/more/notices",
        noticesBadge: true,
      },
      { icon: Info, label: "关于", path: "/more/about" },
    ],
  },
];

export function MorePage() {
  return (
    <div className="flex h-full w-full">
      {/* Secondary navigation */}
      <nav className="flex w-[220px] shrink-0 flex-col overflow-y-auto border-r border-border bg-muted/30 py-4">
        <div className="space-y-4 px-2">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <SectionLabel className="px-3 pb-1">{group.label}</SectionLabel>
              <div className="space-y-0.5">
                {group.items.map((item) => (
                  <NavRow key={item.path} item={item} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </nav>

      {/* Content area — a left-anchored reading column (split layout, so it sets
          its own width rather than the centered content gradient). */}
      <div className="h-full w-full overflow-y-auto">
        <div className="w-full max-w-3xl px-6 py-8">
          <Outlet />
        </div>
      </div>
    </div>
  );
}

/** One grouped nav row. */
function NavRow({ item }: { item: NavItem }) {
  if (item.noticesBadge) {
    return <NoticesNavRow item={item} />;
  }
  return <PlainNavRow item={item} />;
}

function PlainNavRow({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <SurfaceNavLink to={item.path} className="relative">
      <Icon size={16} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
    </SurfaceNavLink>
  );
}

function NoticesNavRow({ item }: { item: NavItem }) {
  const Icon = item.icon;
  const count = useProductNoticesUndismissedCount();
  return (
    <SurfaceNavLink to={item.path} className="relative">
      <Icon size={16} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {count > 0 ? (
        <span
          aria-label={`${count} 条未读公告`}
          className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </SurfaceNavLink>
  );
}

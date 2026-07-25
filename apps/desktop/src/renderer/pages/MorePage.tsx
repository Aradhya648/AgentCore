import { SectionLabel, SurfaceNavLink } from "@/components/ui";
import {
  Brain,
  Cpu,
  Gauge,
  Info,
  KeyRound,
  Keyboard,
  type LucideIcon,
  MessageSquarePlus,
  Palette,
  Shield,
  SlidersHorizontal,
  UserCog,
} from "lucide-react";
import { Outlet } from "react-router-dom";

interface NavItem {
  icon: LucideIcon;
  label: string;
  path: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Settings are grouped by intent: 模型 (组合) + 服务商 (Key) adjacent; 账户 /
// 偏好 / 关于. Opening /more 落点见 MoreIndexRedirect。
const NAV_GROUPS: NavGroup[] = [
  {
    label: "模型",
    items: [
      { icon: Cpu, label: "模型", path: "/more/model" },
      { icon: KeyRound, label: "服务商", path: "/more/providers" },
    ],
  },
  {
    label: "AI",
    items: [
      { icon: Brain, label: "AI 记忆", path: "/more/memory" },
      { icon: SlidersHorizontal, label: "自主度", path: "/more/autonomy" },
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
    items: [{ icon: Info, label: "关于", path: "/more/about" }],
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
  const Icon = item.icon;
  return (
    <SurfaceNavLink to={item.path}>
      <Icon size={16} className="shrink-0" />
      <span>{item.label}</span>
    </SurfaceNavLink>
  );
}

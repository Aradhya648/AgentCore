import { Button } from "@/components/ui";
import { type Theme, resolveDark } from "@/lib/theme";
import { useUIStore } from "@/stores/ui";
import { Check, type LucideIcon, Monitor, Moon, Sun } from "lucide-react";
import { SettingsHeader } from "./SettingsHeader";

interface ThemeOption {
  value: Theme;
  label: string;
  description: string;
  icon: LucideIcon;
}

const THEME_OPTIONS: ThemeOption[] = [
  {
    value: "light",
    label: "浅色",
    description: "始终使用浅色界面。",
    icon: Sun,
  },
  {
    value: "dark",
    label: "深色",
    description: "始终使用深色界面。",
    icon: Moon,
  },
  {
    value: "system",
    label: "跟随系统",
    description: "随操作系统的外观自动切换。",
    icon: Monitor,
  },
];

/**
 * 外观设置（/more/appearance）— 主题选择。
 *
 * 写入共享的 `useUIStore.theme`（持久化到 localStorage），应用由 `lib/theme.ts`
 * 统一收口（AppShell 的 `useApplyTheme` 切 root `.dark` 类、`系统`档随 OS 跟随），
 * 与命令面板的「切换主题」命令同一条链路——这里只是它的可视化入口。
 */
export function AppearanceSettings() {
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);

  return (
    <div>
      <SettingsHeader
        title="外观"
        description="选择界面主题。也可在命令面板（Ctrl/Cmd+K）中快速切换。"
      />

      <section className="mt-6">
        <h2 className="text-base font-medium">主题</h2>
        <div className="mt-4 space-y-2">
          {THEME_OPTIONS.map((option) => (
            <ThemeRow
              key={option.value}
              option={option}
              selected={theme === option.value}
              onSelect={() => setTheme(option.value)}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

/** One selectable theme card: icon badge + label/description + a check when
 * active. The 跟随系统 row also shows what it currently resolves to. */
function ThemeRow({
  option,
  selected,
  onSelect,
}: {
  option: ThemeOption;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = option.icon;
  const resolvedHint =
    option.value === "system"
      ? `当前解析为「${resolveDark("system") ? "深色" : "浅色"}」`
      : null;

  return (
    <Button
      variant="ghost"
      onClick={onSelect}
      aria-pressed={selected}
      className={`h-auto w-full justify-start gap-3 rounded-xl border bg-card px-3 py-2.5 text-left font-normal ${
        selected ? "border-primary" : "border-border hover:bg-accent"
      }`}
    >
      <span
        className={`flex size-8 shrink-0 items-center justify-center rounded-lg ${
          selected
            ? "bg-primary/10 text-primary"
            : "bg-muted text-muted-foreground"
        }`}
      >
        <Icon size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-foreground">{option.label}</span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
          {option.description}
          {resolvedHint ? ` · ${resolvedHint}` : ""}
        </span>
      </span>
      {selected && <Check size={16} className="shrink-0 text-primary" />}
    </Button>
  );
}

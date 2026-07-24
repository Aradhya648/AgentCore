import { Button } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  WINDOW_FRAME_PRESETS,
  type WindowFramePreset,
} from "@shared/window-contract";
import { Check, Scan } from "lucide-react";
import { useEffect, useState } from "react";

const hasFrameApi = (): boolean =>
  typeof window.windowApi?.applyFramePreset === "function";

function PresetRow({
  active,
  label,
  onSelect,
}: {
  active: boolean;
  label: string;
  onSelect: () => void;
}) {
  return (
    <DropdownMenuItem onSelect={onSelect} className="justify-between">
      <span>{label}</span>
      <Check
        size={14}
        className={cn("shrink-0", active ? "opacity-100" : "opacity-0")}
      />
    </DropdownMenuItem>
  );
}

/**
 * TitleBar 拍摄比例菜单：一键跳到 16:9 / 4:3 标准外框并锁定比例，方便 OBS 录屏。
 * 仅 Electron 桌面壳展示（浏览器 / 预览桩无 windowApi.applyFramePreset）。
 */
export function WindowFrameMenu() {
  const [preset, setPreset] = useState<WindowFramePreset>("free");
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    if (!hasFrameApi()) return;
    setAvailable(true);
    void window.windowApi.getFramePreset().then(setPreset);
  }, []);

  if (!available) return null;

  const apply = (next: WindowFramePreset) => {
    setPreset(next);
    void window.windowApi.applyFramePreset(next);
  };

  const activeLabel =
    preset === "free"
      ? "自由"
      : (WINDOW_FRAME_PRESETS.find((p) => p.id === preset)?.label ?? "拍摄");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="neutral"
          icon={<Scan size={13} className="shrink-0" />}
          className="mr-2 h-7 gap-1.5 border border-sidebar-border px-2.5 text-sm text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground [-webkit-app-region:no-drag]"
        >
          {activeLabel}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>窗口拍摄比例</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <PresetRow
          active={preset === "free"}
          label="自由缩放"
          onSelect={() => apply("free")}
        />
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          16:9
        </DropdownMenuLabel>
        {WINDOW_FRAME_PRESETS.filter((p) => p.id.startsWith("16:9")).map(
          (p) => (
            <PresetRow
              key={p.id}
              active={preset === p.id}
              label={p.label}
              onSelect={() => apply(p.id)}
            />
          ),
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          4:3
        </DropdownMenuLabel>
        {WINDOW_FRAME_PRESETS.filter((p) => p.id.startsWith("4:3")).map((p) => (
          <PresetRow
            key={p.id}
            active={preset === p.id}
            label={p.label}
            onSelect={() => apply(p.id)}
          />
        ))}
        <DropdownMenuSeparator />
        <p className="px-3 py-1 text-xs text-muted-foreground">
          锁定后拖边角仍保持比例；最大化时暂不强制。
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

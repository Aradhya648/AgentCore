import { IconButton } from "@/components/ui";
import { hasWindowControls } from "@/lib/capabilities";
import { isMac } from "@/lib/platform";
import { Minus, Square, X } from "lucide-react";

interface WindowControlsProps {
  className?: string;
  buttonClassName?: string;
}

/** Custom min/max/close — Windows/Linux only; macOS uses native traffic lights. */
export function WindowControls({
  className,
  buttonClassName = "h-10 w-12 rounded-none",
}: WindowControlsProps) {
  // 桌面 macOS 用原生交通灯；web（任意 OS）用浏览器自带窗口 chrome——都不画自绘控件。
  if (isMac || !hasWindowControls()) return null;

  return (
    <div className={className}>
      <IconButton
        tone="sidebar"
        aria-label="最小化"
        onClick={() => window.windowApi.minimize()}
        className={buttonClassName}
      >
        <Minus size={14} />
      </IconButton>
      <IconButton
        tone="sidebar"
        aria-label="最大化"
        onClick={() => window.windowApi.maximize()}
        className={buttonClassName}
      >
        <Square size={12} />
      </IconButton>
      <IconButton
        tone="sidebar"
        aria-label="关闭"
        onClick={() => window.windowApi.close()}
        className={`${buttonClassName} hover:bg-destructive hover:text-destructive-foreground`}
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}

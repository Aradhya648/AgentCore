import { Button, IconButton as UiIconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { Loader2 } from "lucide-react";

/**
 * Shared presentational primitives for the file UIs (文件中枢统一) — the tree /
 * preview / snapshot surfaces of both the Files page and the conversation
 * workspace panel. Kept intentionally file-scoped (not generic app UI).
 */

export function IconButton({
  title,
  onClick,
  spinning,
  disabled,
  children,
}: {
  title: string;
  onClick: () => void;
  spinning?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <SimpleTooltip label={title}>
      <UiIconButton
        onClick={onClick}
        disabled={spinning || disabled}
        aria-label={title}
      >
        {spinning ? <Loader2 size={14} className="animate-spin" /> : children}
      </UiIconButton>
    </SimpleTooltip>
  );
}

export function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center">{children}</div>
  );
}

export function InlineError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <p className="text-xs text-muted-foreground">加载失败</p>
      <Button variant="neutral" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

export function EmptyHint({
  icon,
  title,
  hint,
  inline,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  inline?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 px-6 text-center ${
        inline ? "h-full" : "flex-1"
      }`}
    >
      {icon}
      <p className="text-sm text-muted-foreground">{title}</p>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Pin, X } from "lucide-react";
import {
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useRef,
} from "react";

/** Session-level geometry for one in-app float (UX §十 · 应用内浮窗). */
export type FloatingPanelRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export const FLOATING_PANEL_MIN_WIDTH = 280;
export const FLOATING_PANEL_MIN_HEIGHT = 200;
export const FLOATING_PANEL_DEFAULT_WIDTH = 420;
export const FLOATING_PANEL_DEFAULT_HEIGHT = 480;

export type FloatingPanelShellProps = {
  /** Stable id for a11y / tests; chrome only — body is `children`. */
  id: string;
  title: string;
  rect: FloatingPanelRect;
  /** Stack order among sibling floats (higher = on top). */
  zIndex: number;
  /** Visual focus ring; parent owns which float is focused. */
  focused?: boolean;
  /** Click / pointer-down on chrome or body → raise focus. */
  onFocus?: () => void;
  /** 钉回主坞. */
  onDock?: () => void;
  /** Explicit destroy (kinds that allow close). */
  onClose?: () => void;
  onRectChange?: (next: FloatingPanelRect) => void;
  children?: ReactNode;
  className?: string;
};

function clampRect(
  rect: FloatingPanelRect,
  bounds: { width: number; height: number },
): FloatingPanelRect {
  const width = Math.max(
    FLOATING_PANEL_MIN_WIDTH,
    Math.min(rect.width, Math.max(FLOATING_PANEL_MIN_WIDTH, bounds.width)),
  );
  const height = Math.max(
    FLOATING_PANEL_MIN_HEIGHT,
    Math.min(rect.height, Math.max(FLOATING_PANEL_MIN_HEIGHT, bounds.height)),
  );
  const maxX = Math.max(0, bounds.width - width);
  const maxY = Math.max(0, bounds.height - height);
  return {
    x: Math.min(Math.max(0, rect.x), maxX),
    y: Math.min(Math.max(0, rect.y), maxY),
    width,
    height,
  };
}

/**
 * In-app float chrome (JetBrains Float spirit · UX §十): title · drag · focus
 * raise · dock · close. Geometry is session-level via `rect` / `onRectChange`.
 * Body is a slot — SidePanel / run body wiring is a separate block.
 */
export function FloatingPanelShell({
  id,
  title,
  rect,
  zIndex,
  focused = false,
  onFocus,
  onDock,
  onClose,
  onRectChange,
  children,
  className,
}: FloatingPanelShellProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const resizeRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originW: number;
    originH: number;
    originX: number;
    originY: number;
  } | null>(null);

  const hostBounds = useCallback(() => {
    const host = rootRef.current?.offsetParent as HTMLElement | null;
    if (!host) {
      return { width: window.innerWidth, height: window.innerHeight };
    }
    return { width: host.clientWidth, height: host.clientHeight };
  }, []);

  const onTitlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    // Ignore chrome control clicks (钉回 / 关闭).
    if ((e.target as HTMLElement).closest("button")) return;
    e.preventDefault();
    onFocus?.();
    const el = e.currentTarget;
    el.setPointerCapture?.(e.pointerId);
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: rect.x,
      originY: rect.y,
    };
  };

  const onTitlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const next = clampRect(
      {
        ...rect,
        x: drag.originX + (e.clientX - drag.startX),
        y: drag.originY + (e.clientY - drag.startY),
      },
      hostBounds(),
    );
    onRectChange?.(next);
  };

  const endDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    dragRef.current = null;
    try {
      e.currentTarget.releasePointerCapture?.(e.pointerId);
    } catch {
      /* already released */
    }
  };

  const onResizePointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    onFocus?.();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    resizeRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originW: rect.width,
      originH: rect.height,
      originX: rect.x,
      originY: rect.y,
    };
  };

  const onResizePointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== e.pointerId) return;
    const next = clampRect(
      {
        x: resize.originX,
        y: resize.originY,
        width: resize.originW + (e.clientX - resize.startX),
        height: resize.originH + (e.clientY - resize.startY),
      },
      hostBounds(),
    );
    onRectChange?.(next);
  };

  const endResize = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== e.pointerId) return;
    resizeRef.current = null;
    try {
      e.currentTarget.releasePointerCapture?.(e.pointerId);
    } catch {
      /* already released */
    }
  };

  const style: CSSProperties = {
    left: rect.x,
    top: rect.y,
    width: rect.width,
    height: rect.height,
    zIndex,
  };

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-label={title}
      data-floating-panel-id={id}
      data-focused={focused ? "true" : "false"}
      onPointerDown={() => onFocus?.()}
      className={cn(
        "pointer-events-auto absolute flex flex-col overflow-hidden rounded-xl border bg-card shadow-lg",
        focused ? "border-primary/50 shadow-xl" : "border-border",
        className,
      )}
      style={style}
    >
      <div
        data-testid={`floating-panel-title-${id}`}
        onPointerDown={onTitlePointerDown}
        onPointerMove={onTitlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="flex h-11 shrink-0 cursor-grab items-center gap-1 border-b border-border px-2 py-1.5 active:cursor-grabbing"
      >
        <div className="min-w-0 flex-1 truncate px-1 text-sm font-medium text-foreground">
          {title}
        </div>
        {onDock && (
          <SimpleTooltip label="钉回主坞">
            <IconButton
              aria-label="钉回主坞"
              onClick={(e) => {
                e.stopPropagation();
                onDock();
              }}
            >
              <Pin size={15} />
            </IconButton>
          </SimpleTooltip>
        )}
        {onClose && (
          <SimpleTooltip label="关闭浮窗">
            <IconButton
              aria-label="关闭浮窗"
              onClick={(e) => {
                e.stopPropagation();
                onClose();
              }}
            >
              <X size={15} />
            </IconButton>
          </SimpleTooltip>
        )}
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">{children}</div>

      <button
        type="button"
        aria-label="调整浮窗大小"
        data-testid={`floating-panel-resize-${id}`}
        onPointerDown={onResizePointerDown}
        onPointerMove={onResizePointerMove}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        className="absolute bottom-0 right-0 z-10 size-3 cursor-se-resize rounded-none border-0 bg-transparent p-0"
      />
    </div>
  );
}

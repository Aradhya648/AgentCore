import {
  FLOATING_PANEL_DEFAULT_HEIGHT,
  FLOATING_PANEL_DEFAULT_WIDTH,
  FloatingPanelShell,
  type FloatingPanelRect,
} from "@/components/layout/FloatingPanelShell";
import { type ReactNode, useCallback, useMemo, useState } from "react";

/** One float entry owned by the page-level host. */
export type FloatingPanelEntry = {
  id: string;
  title: string;
  rect: FloatingPanelRect;
  /** When set, host uses store stacking instead of a local focus stack. */
  zIndex?: number;
  /** When false, shell omits the destroy (X) control — workspace / changes. */
  closable?: boolean;
  /** Controlled focus ring from store focusSurface. */
  focused?: boolean;
};

export type FloatingPanelHostProps = {
  /**
   * Controlled panels. When omitted, host keeps a local demo entry so chrome
   * (drag / focus / dock / close) can be exercised without SidePanel body wiring.
   */
  panels?: FloatingPanelEntry[];
  /** Seed one empty demo shell when `panels` is omitted. Default true. */
  demo?: boolean;
  onDock?: (id: string) => void;
  onClose?: (id: string) => void;
  onFocus?: (id: string) => void;
  /** Controlled geometry updates (required for drag/resize when `panels` is set). */
  onRectChange?: (id: string, rect: FloatingPanelRect) => void;
  /** Body slot per float — run / workspace / file / changes. */
  renderBody?: (panel: FloatingPanelEntry) => ReactNode;
};

const DEMO_ID = "float-demo";

function defaultDemoRect(): FloatingPanelRect {
  return {
    x: 72,
    y: 64,
    width: FLOATING_PANEL_DEFAULT_WIDTH,
    height: FLOATING_PANEL_DEFAULT_HEIGHT,
  };
}

/**
 * Page-level float host (UX §十): lives beside SidePanel, **not** under
 * `SidePanel.open`. Closing the dock must not unmount this layer.
 */
export function FloatingPanelHost({
  panels: controlledPanels,
  demo = true,
  onDock,
  onClose,
  onFocus,
  onRectChange,
  renderBody,
}: FloatingPanelHostProps) {
  const controlled = controlledPanels !== undefined;
  const [localPanels, setLocalPanels] = useState<FloatingPanelEntry[]>(() =>
    demo && !controlled
      ? [
          {
            id: DEMO_ID,
            title: "浮窗（演示）",
            rect: defaultDemoRect(),
            closable: true,
          },
        ]
      : [],
  );
  const [focusStack, setFocusStack] = useState<string[]>([]);

  const panels = controlled ? controlledPanels : localPanels;
  const useStoreZ = controlled && panels.every((p) => p.zIndex != null);

  const focusedId = useMemo(() => {
    const controlledFocus = panels.find((p) => p.focused)?.id;
    if (controlledFocus) return controlledFocus;
    for (let i = focusStack.length - 1; i >= 0; i--) {
      if (panels.some((p) => p.id === focusStack[i])) return focusStack[i];
    }
    return panels[0]?.id ?? null;
  }, [focusStack, panels]);

  const zIndexFor = useCallback(
    (panel: FloatingPanelEntry) => {
      if (useStoreZ && panel.zIndex != null) {
        return 30 + panel.zIndex;
      }
      const idx = focusStack.indexOf(panel.id);
      return 30 + (idx === -1 ? 0 : idx + 1);
    },
    [focusStack, useStoreZ],
  );

  const raiseFocus = useCallback(
    (id: string) => {
      onFocus?.(id);
      setFocusStack((prev) => {
        if (prev[prev.length - 1] === id) return prev;
        return [...prev.filter((x) => x !== id), id];
      });
    },
    [onFocus],
  );

  const updateRect = useCallback(
    (id: string, rect: FloatingPanelRect) => {
      if (controlled) {
        onRectChange?.(id, rect);
        return;
      }
      setLocalPanels((prev) =>
        prev.map((p) => (p.id === id ? { ...p, rect } : p)),
      );
    },
    [controlled, onRectChange],
  );

  const removeLocal = useCallback((id: string) => {
    setLocalPanels((prev) => prev.filter((p) => p.id !== id));
    setFocusStack((prev) => prev.filter((x) => x !== id));
  }, []);

  const handleDock = useCallback(
    (id: string) => {
      onDock?.(id);
      if (!controlled) removeLocal(id);
    },
    [controlled, onDock, removeLocal],
  );

  const handleClose = useCallback(
    (id: string) => {
      onClose?.(id);
      if (!controlled) removeLocal(id);
    },
    [controlled, onClose, removeLocal],
  );

  if (panels.length === 0) {
    return (
      <div
        data-testid="floating-panel-host"
        data-empty="true"
        className="pointer-events-none absolute inset-0 z-30 overflow-hidden"
        aria-hidden
      />
    );
  }

  return (
    <div
      data-testid="floating-panel-host"
      className="pointer-events-none absolute inset-0 z-30 overflow-hidden"
    >
      {panels.map((panel) => (
        <FloatingPanelShell
          key={panel.id}
          id={panel.id}
          title={panel.title}
          rect={panel.rect}
          zIndex={zIndexFor(panel)}
          focused={panel.id === focusedId}
          onFocus={() => raiseFocus(panel.id)}
          onDock={() => handleDock(panel.id)}
          onClose={
            panel.closable === false ? undefined : () => handleClose(panel.id)
          }
          onRectChange={(next) => updateRect(panel.id, next)}
        >
          {renderBody?.(panel)}
        </FloatingPanelShell>
      ))}
    </div>
  );
}

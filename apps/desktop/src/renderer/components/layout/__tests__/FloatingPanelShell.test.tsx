// @vitest-environment jsdom
import {
  FLOATING_PANEL_DEFAULT_HEIGHT,
  FLOATING_PANEL_DEFAULT_WIDTH,
  FloatingPanelShell,
  type FloatingPanelRect,
} from "@/components/layout/FloatingPanelShell";
import {
  FloatingPanelHost,
  type FloatingPanelEntry,
} from "@/components/layout/FloatingPanelHost";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
});

function renderWithTooltip(ui: ReactElement) {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
}

function rect(partial?: Partial<FloatingPanelRect>): FloatingPanelRect {
  return {
    x: 40,
    y: 40,
    width: FLOATING_PANEL_DEFAULT_WIDTH,
    height: FLOATING_PANEL_DEFAULT_HEIGHT,
    ...partial,
  };
}

describe("FloatingPanelShell", () => {
  it("drags via title bar and reports rect", () => {
    const onRectChange = vi.fn();
    const { container } = renderWithTooltip(
      <div style={{ position: "relative", width: 800, height: 600 }}>
        <FloatingPanelShell
          id="a"
          title="Worker A"
          rect={rect()}
          zIndex={30}
          onRectChange={onRectChange}
        />
      </div>,
    );
    const title = screen.getByTestId("floating-panel-title-a");
    fireEvent.pointerDown(title, {
      button: 0,
      clientX: 100,
      clientY: 100,
      pointerId: 1,
    });
    fireEvent.pointerMove(title, {
      clientX: 140,
      clientY: 130,
      pointerId: 1,
    });
    fireEvent.pointerUp(title, { pointerId: 1 });
    expect(onRectChange).toHaveBeenCalled();
    const last = onRectChange.mock.calls.at(-1)?.[0] as FloatingPanelRect;
    expect(last.x).toBe(80);
    expect(last.y).toBe(70);
    expect(container.querySelector('[data-floating-panel-id="a"]')).toBeTruthy();
  });

  it("fires onFocus when the shell is pressed", () => {
    const onFocus = vi.fn();
    renderWithTooltip(
      <FloatingPanelShell
        id="a"
        title="Worker A"
        rect={rect()}
        zIndex={30}
        onFocus={onFocus}
      />,
    );
    fireEvent.pointerDown(screen.getByRole("dialog", { name: "Worker A" }));
    expect(onFocus).toHaveBeenCalledTimes(1);
  });

  it("fires dock and close callbacks", () => {
    const onDock = vi.fn();
    const onClose = vi.fn();
    renderWithTooltip(
      <FloatingPanelShell
        id="a"
        title="Worker A"
        rect={rect()}
        zIndex={30}
        onDock={onDock}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "钉回主坞" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭浮窗" }));
    expect(onDock).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("FloatingPanelHost", () => {
  it("keeps an empty host node mounted when there are no panels", () => {
    renderWithTooltip(<FloatingPanelHost demo={false} />);
    const host = screen.getByTestId("floating-panel-host");
    expect(host.getAttribute("data-empty")).toBe("true");
  });

  it("demo mode seeds a local empty shell", () => {
    renderWithTooltip(<FloatingPanelHost demo />);
    expect(screen.getByRole("dialog", { name: "浮窗（演示）" })).toBeTruthy();
  });

  it("raises z-index on focus among siblings", () => {
    function Harness() {
      const [panels] = useState<FloatingPanelEntry[]>([
        { id: "a", title: "A", rect: rect({ x: 10 }) },
        { id: "b", title: "B", rect: rect({ x: 200 }) },
      ]);
      return <FloatingPanelHost panels={panels} demo={false} />;
    }
    renderWithTooltip(<Harness />);
    const a = screen.getByRole("dialog", { name: "A" });
    const b = screen.getByRole("dialog", { name: "B" });
    fireEvent.pointerDown(b);
    expect(Number(b.style.zIndex)).toBeGreaterThan(Number(a.style.zIndex));
    fireEvent.pointerDown(a);
    expect(Number(a.style.zIndex)).toBeGreaterThan(Number(b.style.zIndex));
  });

  it("dock callback fires and removes demo panel", () => {
    const onDock = vi.fn();
    renderWithTooltip(<FloatingPanelHost demo onDock={onDock} />);
    fireEvent.click(screen.getByRole("button", { name: "钉回主坞" }));
    expect(onDock).toHaveBeenCalledWith("float-demo");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("close callback fires and removes demo panel", () => {
    const onClose = vi.fn();
    renderWithTooltip(<FloatingPanelHost demo onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭浮窗" }));
    expect(onClose).toHaveBeenCalledWith("float-demo");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

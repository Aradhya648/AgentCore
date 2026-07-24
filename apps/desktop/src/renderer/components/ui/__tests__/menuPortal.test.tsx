// @vitest-environment jsdom
/**
 * Regression: opening a dropdown / context menu must not crash.
 *
 * `*MenuContent` mounts a `<PreviewObstruct />` (null-rendering overlay marker)
 * alongside the Radix `Content` inside the menu Portal. Radix's `MenuPortal`
 * (unlike `DialogPortal`) does **not** `React.Children.map` — it forwards its
 * children straight into a single `asChild` `Primitive.div` Slot, which throws
 * "Primitive.div failed to slot onto its children" when handed more than one
 * element. Each obstruct marker therefore needs its own Portal. This test opens
 * both menus and asserts their items render (i.e. the Slot did not throw).
 */

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useOverlayStore } from "@/stores/overlay";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

// jsdom lacks the browser APIs Radix's floating menu content touches on open.
beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Element.prototype.scrollIntoView ??= () => {};
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.setPointerCapture ??= () => {};
  Element.prototype.releasePointerCapture ??= () => {};
});

afterEach(() => {
  cleanup();
  useOverlayStore.setState({ count: 0 });
});

describe("menu portals (PreviewObstruct sibling)", () => {
  it("opens a DropdownMenu without a Slot crash", () => {
    render(
      <DropdownMenu defaultOpen>
        <DropdownMenuTrigger>打开</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>菜单项</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    expect(screen.getByText("菜单项")).toBeTruthy();
    // The obstruct marker mounted inside the (now separate) Portal.
    expect(useOverlayStore.getState().count).toBeGreaterThan(0);
  });

  it("opens a ContextMenu without a Slot crash", () => {
    render(
      <ContextMenu>
        <ContextMenuTrigger>右键区域</ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem>右键项</ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>,
    );
    fireEvent.contextMenu(screen.getByText("右键区域"));
    expect(screen.getByText("右键项")).toBeTruthy();
  });
});

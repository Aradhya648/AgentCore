// @vitest-environment jsdom
/**
 * Local-only synced_pending / synced caption on optimistic bubbles.
 * The block comment keeps the @vitest-environment directive file-leading.
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PENDING_REVEAL_MS, SyncStatusHint } from "../SyncStatusHint";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
});

function wrap(ui: ReactNode) {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
}

describe("SyncStatusHint", () => {
  it("renders nothing when syncStatus is absent", () => {
    const { container } = wrap(<SyncStatusHint syncStatus={undefined} />);
    expect(container.childElementCount).toBe(0);
  });

  it("stays silent within the pending reveal threshold", () => {
    const { container } = wrap(<SyncStatusHint syncStatus="synced_pending" />);
    expect(screen.queryByTestId("sync-status-synced_pending")).toBeNull();
    expect(container.childElementCount).toBe(0);

    act(() => {
      vi.advanceTimersByTime(PENDING_REVEAL_MS - 1);
    });
    expect(screen.queryByTestId("sync-status-synced_pending")).toBeNull();
  });

  it("shows 待同步 after the pending reveal threshold", () => {
    wrap(<SyncStatusHint syncStatus="synced_pending" />);

    act(() => {
      vi.advanceTimersByTime(PENDING_REVEAL_MS);
    });

    const el = screen.getByTestId("sync-status-synced_pending");
    expect(el.textContent).toContain("待同步");
    expect(screen.getByLabelText("待同步")).toBeTruthy();
  });

  it("flashes 已同步 only when 待同步 was actually visible", () => {
    const { rerender } = wrap(<SyncStatusHint syncStatus="synced_pending" />);

    act(() => {
      vi.advanceTimersByTime(PENDING_REVEAL_MS);
    });
    expect(screen.getByTestId("sync-status-synced_pending")).toBeTruthy();

    rerender(
      <TooltipProvider>
        <SyncStatusHint syncStatus="synced" />
      </TooltipProvider>,
    );

    const el = screen.getByTestId("sync-status-synced");
    expect(el.textContent).toContain("已同步");
    expect(screen.getByLabelText("已同步")).toBeTruthy();
  });

  it("stays silent on synced when pending never became visible", () => {
    const { rerender, container } = wrap(
      <SyncStatusHint syncStatus="synced_pending" />,
    );

    act(() => {
      vi.advanceTimersByTime(PENDING_REVEAL_MS - 1);
    });
    expect(screen.queryByTestId("sync-status-synced_pending")).toBeNull();

    rerender(
      <TooltipProvider>
        <SyncStatusHint syncStatus="synced" />
      </TooltipProvider>,
    );

    expect(screen.queryByTestId("sync-status-synced")).toBeNull();
    expect(container.childElementCount).toBe(0);
  });
});

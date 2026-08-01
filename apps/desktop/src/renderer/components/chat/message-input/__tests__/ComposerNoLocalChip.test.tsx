// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { DESKTOP_DOWNLOAD_URL } from "@/lib/desktopDownload";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ComposerNoLocalChip } from "../ComposerNoLocalChip";

vi.mock("@/lib/capabilities", () => ({
  isWebRuntime: vi.fn(() => true),
}));

import { isWebRuntime } from "@/lib/capabilities";

const mockedIsWeb = vi.mocked(isWebRuntime);

function renderChip(ui: ReactElement) {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ComposerNoLocalChip", () => {
  beforeEach(() => {
    mockedIsWeb.mockReturnValue(true);
    vi.spyOn(window, "open").mockReturnValue(null);
  });

  it("shows web no-local chip with download CTA", () => {
    renderChip(<ComposerNoLocalChip />);
    expect(screen.getByTestId("composer-no-local-chip")).toBeTruthy();
    expect(screen.getByText("网页版 · 无本机")).toBeTruthy();
    expect(screen.getByText("下载")).toBeTruthy();
  });

  it("hides on desktop (non-web runtime)", () => {
    mockedIsWeb.mockReturnValue(false);
    const { container } = renderChip(<ComposerNoLocalChip />);
    expect(container.textContent).toBe("");
    expect(screen.queryByTestId("composer-no-local-chip")).toBeNull();
  });

  it("opens desktop download page on click", () => {
    renderChip(<ComposerNoLocalChip />);
    fireEvent.click(screen.getByTestId("composer-no-local-chip"));
    expect(window.open).toHaveBeenCalledWith(
      DESKTOP_DOWNLOAD_URL,
      "_blank",
      "noopener,noreferrer",
    );
  });
});

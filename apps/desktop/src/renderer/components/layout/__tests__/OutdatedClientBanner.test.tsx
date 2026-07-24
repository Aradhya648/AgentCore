// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  hasAutoUpdater: vi.fn(() => true),
}));

import { hasAutoUpdater } from "@/lib/capabilities";
import { useUpdatesStore } from "@/stores/updates";
import { OutdatedClientBanner } from "../OutdatedClientBanner";

const hasAutoUpdaterMock = vi.mocked(hasAutoUpdater);

beforeEach(() => {
  hasAutoUpdaterMock.mockReturnValue(true);
  useUpdatesStore.setState({
    outdatedMinVersion: "0.6.5",
    outdatedDismissed: false,
    check: vi.fn(() => Promise.resolve()),
    dismissOutdated: () =>
      useUpdatesStore.setState({ outdatedDismissed: true }),
  });
});

afterEach(() => {
  cleanup();
  useUpdatesStore.setState({
    outdatedMinVersion: null,
    outdatedDismissed: false,
  });
});

function renderBanner() {
  return render(
    <MemoryRouter>
      <OutdatedClientBanner />
    </MemoryRouter>,
  );
}

describe("OutdatedClientBanner", () => {
  it("renders soft copy and CTA when outdated and Electron", () => {
    renderBanner();
    expect(screen.getByText("当前版本过旧，请更新后继续使用")).toBeTruthy();
    expect(screen.getByRole("button", { name: "去更新" })).toBeTruthy();
  });

  it("hides on web clients", () => {
    hasAutoUpdaterMock.mockReturnValue(false);
    const { container } = renderBanner();
    expect(container.firstChild).toBeNull();
  });

  it("hides after session dismiss", () => {
    renderBanner();
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByText("当前版本过旧，请更新后继续使用")).toBeNull();
  });

  it("navigates to about and triggers check on CTA", () => {
    const check = vi.fn(() => Promise.resolve());
    useUpdatesStore.setState({ check });
    renderBanner();
    fireEvent.click(screen.getByRole("button", { name: "去更新" }));
    expect(check).toHaveBeenCalled();
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  hasAutoUpdater: vi.fn(() => true),
}));
vi.mock("@/lib/clientBuildInfo", () => ({
  clientVersion: vi.fn(() => "0.6.1"),
}));

import { hasAutoUpdater } from "@/lib/capabilities";
import { useUpdatesStore } from "@/stores/updates";
import { ForceUpdateGate } from "../ForceUpdateGate";

const hasAutoUpdaterMock = vi.mocked(hasAutoUpdater);

beforeEach(() => {
  hasAutoUpdaterMock.mockReturnValue(true);
  useUpdatesStore.setState({
    status: { phase: "idle" },
    outdatedMinVersion: "0.6.5",
    dialogOpen: false,
    check: vi.fn(() => Promise.resolve()),
    download: vi.fn(() => Promise.resolve()),
    install: vi.fn(() => Promise.resolve()),
    openUpdateDialog: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  useUpdatesStore.setState({
    outdatedMinVersion: null,
    status: { phase: "idle" },
    dialogOpen: false,
  });
});

describe("ForceUpdateGate", () => {
  it("renders hard-gate copy and min version when outdated and Electron", () => {
    render(<ForceUpdateGate />);
    expect(
      screen.getByText("当前版本过旧，须更新后才能继续使用"),
    ).toBeTruthy();
    expect(screen.getByText(/最低要求 0\.6\.5/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "检查更新" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "关闭" })).toBeNull();
  });

  it("hides on web clients", () => {
    hasAutoUpdaterMock.mockReturnValue(false);
    const { container } = render(<ForceUpdateGate />);
    expect(container.firstChild).toBeNull();
  });

  it("hides when outdatedMinVersion is null", () => {
    useUpdatesStore.setState({ outdatedMinVersion: null });
    const { container } = render(<ForceUpdateGate />);
    expect(container.firstChild).toBeNull();
  });

  it("triggers check on 检查更新", () => {
    const check = vi.fn(() => Promise.resolve());
    useUpdatesStore.setState({ check, status: { phase: "idle" } });
    render(<ForceUpdateGate />);
    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));
    expect(check).toHaveBeenCalled();
  });

  it("shows 立即更新 and downloads when a version is available", () => {
    const download = vi.fn(() => Promise.resolve());
    const openUpdateDialog = vi.fn();
    useUpdatesStore.setState({
      download,
      openUpdateDialog,
      status: { phase: "available", version: "0.7.0" },
    });
    render(<ForceUpdateGate />);
    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    expect(openUpdateDialog).toHaveBeenCalled();
    expect(download).toHaveBeenCalled();
  });

  it("shows 重启安装 when downloaded", () => {
    const install = vi.fn(() => Promise.resolve());
    useUpdatesStore.setState({
      install,
      status: { phase: "downloaded", version: "0.7.0" },
    });
    render(<ForceUpdateGate />);
    fireEvent.click(screen.getByRole("button", { name: "重启安装" }));
    expect(install).toHaveBeenCalled();
  });
});

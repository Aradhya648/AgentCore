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
import { UpdateAvailableDialog } from "../UpdateAvailableDialog";

const hasAutoUpdaterMock = vi.mocked(hasAutoUpdater);

beforeEach(() => {
  hasAutoUpdaterMock.mockReturnValue(true);
  useUpdatesStore.setState({
    status: {
      phase: "available",
      version: "0.7.0",
      releaseNotes: "重要修复",
      sizeBytes: 2048,
    },
    dialogOpen: true,
    download: vi.fn(() => Promise.resolve()),
    remindLater: vi.fn(),
    skipVersion: vi.fn(),
    closeUpdateDialog: vi.fn(),
    install: vi.fn(() => Promise.resolve()),
  });
});

afterEach(() => {
  cleanup();
  useUpdatesStore.setState({
    status: { phase: "idle" },
    dialogOpen: false,
  });
});

describe("UpdateAvailableDialog", () => {
  it("renders version, notes, size and three actions", () => {
    render(<UpdateAvailableDialog />);
    expect(screen.getByText("发现新版本 0.7.0")).toBeTruthy();
    expect(screen.getByText(/当前版本 0\.6\.1/)).toBeTruthy();
    expect(screen.getByText("重要修复")).toBeTruthy();
    expect(screen.getByRole("button", { name: "立即更新" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "稍后提醒" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "跳过此版本" })).toBeTruthy();
  });

  it("falls back to default notes when feed empty", () => {
    useUpdatesStore.setState({
      status: { phase: "available", version: "0.7.0", releaseNotes: null },
    });
    render(<UpdateAvailableDialog />);
    expect(screen.getByText("修复与体验改进")).toBeTruthy();
  });

  it("calls download on 立即更新", () => {
    const download = vi.fn(() => Promise.resolve());
    useUpdatesStore.setState({ download });
    render(<UpdateAvailableDialog />);
    fireEvent.click(screen.getByRole("button", { name: "立即更新" }));
    expect(download).toHaveBeenCalled();
  });

  it("shows progress while downloading", () => {
    useUpdatesStore.setState({
      status: {
        phase: "downloading",
        version: "0.7.0",
        percent: 42,
        bytesPerSecond: 524_288,
        transferred: 83_886_080,
        total: 198_180_864,
      },
      dialogOpen: true,
    });
    render(<UpdateAvailableDialog />);
    expect(
      screen.getByText(/下载进度 42% · 80 MB \/ 189 MB · 512 KB\/s/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "后台下载" })).toBeTruthy();
  });

  it("hides on web clients", () => {
    hasAutoUpdaterMock.mockReturnValue(false);
    const { container } = render(<UpdateAvailableDialog />);
    expect(container.firstChild).toBeNull();
  });
});

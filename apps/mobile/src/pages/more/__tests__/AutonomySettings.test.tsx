// @vitest-environment jsdom
/**
 * Render + interaction tests for mobile 新会话默认权限配方 (More → /more/autonomy).
 */

import { getAutonomy, setAutonomy } from "@/api/autonomy";
import { AutonomySettings } from "@/pages/more/AutonomySettings";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/autonomy", () => ({
  getAutonomy: vi.fn(),
  setAutonomy: vi.fn(),
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockGet = vi.mocked(getAutonomy);
const mockSet = vi.mocked(setAutonomy);

afterEach(cleanup);
beforeEach(() => {
  mockGet.mockReset();
  mockSet.mockReset();
  mockNavigate.mockReset();
  mockGet.mockResolvedValue({ policy: "less_interrupt" });
  mockSet.mockResolvedValue({ policy: "managed" });
});

describe("AutonomySettings", () => {
  it("loads and renders the three recipe options with the current selection", async () => {
    render(<AutonomySettings />);
    expect(screen.getByText("加载中…")).toBeTruthy();

    await waitFor(() =>
      expect(screen.getByText("少打断（推荐）")).toBeTruthy(),
    );
    expect(screen.getByText("谨慎")).toBeTruthy();
    expect(screen.getByText("托管")).toBeTruthy();
    expect(screen.queryByText(/写代码/)).toBeNull();
    expect(
      screen.getByText(
        /新会话默认：本会话信任改文件；自动执行；跳过组团卡；本机每次确认/,
      ),
    ).toBeTruthy();

    const selected = screen.getByRole("radio", {
      name: /少打断/,
    });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("PUTs the selected policy and shows inline success feedback", async () => {
    render(<AutonomySettings />);
    await waitFor(() => expect(screen.getByText("托管")).toBeTruthy());

    // less_interrupt → managed: both already command=auto, no confirm.
    fireEvent.click(screen.getByText("托管"));
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("managed"));
    await waitFor(() =>
      expect(screen.getByText("已更新默认配方")).toBeTruthy(),
    );

    const selected = screen.getByRole("radio", { name: /托管/ });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("shows an inline error when save fails and keeps the prior selection", async () => {
    mockSet.mockRejectedValue(new Error("设置失败 (500)"));
    render(<AutonomySettings />);
    await waitFor(() => expect(screen.getByText("谨慎")).toBeTruthy());

    fireEvent.click(screen.getByText("谨慎"));
    await waitFor(() =>
      expect(screen.getByText("设置失败 (500)")).toBeTruthy(),
    );

    const selected = screen.getByRole("radio", {
      name: /少打断/,
    });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("does not PUT when re-selecting the already-active policy", async () => {
    render(<AutonomySettings />);
    await waitFor(() =>
      expect(screen.getByText("少打断（推荐）")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("少打断（推荐）"));
    expect(mockSet).not.toHaveBeenCalled();
  });

  it("confirms when entering command=auto from cautious", async () => {
    mockGet.mockResolvedValue({ policy: "cautious" });
    mockSet.mockResolvedValue({ policy: "less_interrupt" });
    render(<AutonomySettings />);
    await waitFor(() => expect(screen.getByText("谨慎")).toBeTruthy());

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByText("少打断（推荐）"));
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("less_interrupt"));
    expect(window.confirm).toHaveBeenCalled();
  });
});

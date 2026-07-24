// @vitest-environment jsdom
/**
 * Render + interaction tests for mobile 新会话默认权限设置 (More → /more/autonomy).
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
  mockGet.mockResolvedValue({ policy: "first_grant" });
  mockSet.mockResolvedValue({ policy: "full_auto" });
});

describe("AutonomySettings", () => {
  it("loads and renders the three policy options with the current selection", async () => {
    render(<AutonomySettings />);
    expect(screen.getByText("加载中…")).toBeTruthy();

    await waitFor(() =>
      expect(screen.getByText("开工授权（推荐）")).toBeTruthy(),
    );
    expect(screen.getByText("只观察")).toBeTruthy();
    expect(screen.getByText("完全信任")).toBeTruthy();
    expect(screen.getByText(/新会话默认：开工卡一次授权/)).toBeTruthy();

    const selected = screen.getByRole("radio", {
      name: /开工授权/,
    });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("PUTs the selected policy and shows inline success feedback", async () => {
    render(<AutonomySettings />);
    await waitFor(() => expect(screen.getByText("完全信任")).toBeTruthy());

    fireEvent.click(screen.getByText("完全信任"));
    await waitFor(() => expect(mockSet).toHaveBeenCalledWith("full_auto"));
    await waitFor(() => expect(screen.getByText("已更新自主度")).toBeTruthy());

    const selected = screen.getByRole("radio", { name: /完全信任/ });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("shows an inline error when save fails and keeps the prior selection", async () => {
    mockSet.mockRejectedValue(new Error("设置失败 (500)"));
    render(<AutonomySettings />);
    await waitFor(() => expect(screen.getByText("只观察")).toBeTruthy());

    fireEvent.click(screen.getByText("只观察"));
    await waitFor(() =>
      expect(screen.getByText("设置失败 (500)")).toBeTruthy(),
    );

    const selected = screen.getByRole("radio", {
      name: /开工授权/,
    });
    expect((selected as HTMLInputElement).checked).toBe(true);
  });

  it("does not PUT when re-selecting the already-active policy", async () => {
    render(<AutonomySettings />);
    await waitFor(() =>
      expect(screen.getByText("开工授权（推荐）")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("开工授权（推荐）"));
    expect(mockSet).not.toHaveBeenCalled();
  });
});
